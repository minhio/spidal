from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from pathlib import Path

import requests

from spidal.core.config import Config
from spidal.core.hifi import iter_stream_urls
from spidal.core.persistence import get_db, save_track
from spidal.core.tagging import tag_flac, tag_m4a, tag_ogg, tag_webm

logger = logging.getLogger(__name__)

MIN_FILE_SIZE = 50 * 1024  # 50 KB
MAX_RETRIES = 3


def _sniff_extension(path: Path) -> str:
    """Return the correct file extension based on magic bytes."""
    try:
        with path.open("rb") as f:
            header = f.read(12)
        if header[:4] == b"fLaC":
            return ".flac"
        if header[4:8] == b"ftyp":
            return ".m4a"
        if header[:4] == b"OggS":
            return ".ogg"
        if header[:4] == b"\x1a\x45\xdf\xa3":
            return ".webm"
        if header[:3] == b"ID3" or header[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
            return ".mp3"
    except OSError:
        pass
    return path.suffix


def _sanitize(name: str) -> str:
    """Remove filesystem-unsafe characters from a name."""
    return re.sub(r'[/\\?%*:|"<>]', "", name)


def _cleanup(file_path: Path) -> None:
    """Delete a partial file and remove empty parent directories."""
    try:
        file_path.unlink(missing_ok=True)
        logger.debug("Removed partial file: %s", file_path)
    except OSError as e:
        logger.warning("Could not remove partial file %s: %s", file_path, e)
    # Walk up to remove empty dirs (album dir, then artist dir)
    for parent in (file_path.parent, file_path.parent.parent):
        try:
            parent.rmdir()  # only succeeds if empty
            logger.debug("Removed empty directory: %s", parent)
        except OSError:
            break


def _download_direct(
    url: str,
    file_path: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> bool:
    """Download a file from a direct URL. Returns True on success."""
    resp = requests.get(url, stream=True, timeout=30)
    if not resp.ok:
        logger.warning("Download returned %s for %s", resp.status_code, url[:80])
        return False

    content_type = resp.headers.get("content-type", "")
    if any(t in content_type for t in ("xml", "html", "text")):
        logger.warning("Received %s instead of audio", content_type)
        return False

    total = int(resp.headers.get("content-length") or 0)
    written = 0
    with open(file_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            f.write(chunk)
            if on_progress and total:
                written += len(chunk)
                on_progress(written, total)
    return True


def _download_dash(
    segments: list[str],
    file_path: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> bool:
    """Download DASH segments sequentially and concatenate. Returns True on success."""
    with open(file_path, "wb") as f:
        for i, url in enumerate(segments):
            success = False
            for attempt in range(MAX_RETRIES):
                try:
                    resp = requests.get(url, timeout=30)
                    if not resp.ok:
                        logger.warning(
                            "Segment %d/%d returned %s",
                            i + 1,
                            len(segments),
                            resp.status_code,
                        )
                        return False
                    if not resp.content:
                        logger.warning("Empty segment %d/%d", i + 1, len(segments))
                        return False
                    f.write(resp.content)
                    if on_progress:
                        on_progress(i + 1, len(segments))
                    success = True
                    break
                except requests.RequestException as e:
                    if attempt < MAX_RETRIES - 1:
                        delay = 2**attempt
                        logger.info(
                            "Segment %d retry %d after %ds: %s",
                            i + 1,
                            attempt + 1,
                            delay,
                            e,
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "Segment %d failed after %d retries: %s",
                            i + 1,
                            MAX_RETRIES,
                            e,
                        )
            if not success:
                return False
    return True


def _persist(track: dict, file_path: str | None = None) -> None:
    """Best-effort save of a track record to the database."""
    try:
        db = get_db()
        save_track(db, track, file_path)
        db.close()
    except Exception:
        logger.warning(
            "Failed to persist track %s", track.get("hifi_id") or track.get("id"), exc_info=True
        )


def _attempt_streams(
    streams: object,
    file_path: Path,
    on_progress: Callable[[int, int], None] | None,
) -> bool:
    """Try each stream URL, cleaning up between attempts. Returns True on success."""
    for stream in streams:  # type: ignore[union-attr]
        if isinstance(stream, list):
            logger.info("Downloading %d DASH segments", len(stream))
            ok = _download_dash(stream, file_path, on_progress)
        else:
            logger.info("Downloading from %s", stream[:80])
            ok = _download_direct(stream, file_path, on_progress)

        if ok and file_path.stat().st_size >= MIN_FILE_SIZE:
            return True

        if ok:
            logger.warning(
                "File too small (%d bytes), likely corrupted", file_path.stat().st_size
            )
        logger.info("Retrying with next API endpoint")
        _cleanup(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

    return False


def _tag_file(
    config: Config,
    file_path: Path,
    track: dict,
    artist: str,
    album: str,
) -> None:
    """Tag the downloaded file using the appropriate tagger for its format."""
    if config.disable_tagging and config.disable_tagging.lower() not in ("false", "0", ""):
        logger.info("Tagging disabled, skipping: %s", file_path.name)
        return
    _TAGGERS = {
        ".flac": tag_flac,
        ".m4a": tag_m4a,
        ".ogg": tag_ogg,
        ".webm": tag_webm,
    }
    tagger = _TAGGERS.get(file_path.suffix)
    if tagger:
        tagger(str(file_path), track, artist, album)
    else:
        logger.warning("No tagger for format %s: %s", file_path.suffix, file_path.name)


def download_track(
    config: Config,
    track: dict,
    artist: str,
    album: str,
    on_progress: Callable[[int, int], None] | None = None,
    on_error: Callable[[dict, Exception], None] | None = None,
) -> tuple[str, str | None]:
    """Download a FLAC track from the hifi API.

    Args:
        config: Config with API endpoints and download_dir.
        track: Matched hifi track dict (from match_track).
        artist: Artist name for directory structure.
        album: Album name for directory structure.

    Returns:
        Tuple of (status, file_path) where status is "downloaded" or
        "failed", and file_path is the path string (None on failure).
    """
    track_id = track.get("hifi_id")
    title = track.get("hifi_title") or "Unknown"
    track_number = track.get("hifi_track_number") or 0

    safe_artist = _sanitize(artist)
    safe_album = _sanitize(album)
    safe_title = _sanitize(title)
    filename = f"{int(track_number):02d} - {safe_title}.flac"

    download_dir = Path(config.download_dir or "downloads")
    file_path = download_dir / safe_artist / safe_album / filename

    if file_path.exists():
        logger.info("Already exists: %s", file_path)
        _persist(track, str(file_path))
        return "skipped", str(file_path)

    try:
        streams = iter_stream_urls(config.get_apis(), track_id)
    except ConnectionError as e:
        logger.error("Failed to get stream URL for track %s: %s", track_id, e)
        if on_error:
            on_error(track, e)
        _persist(track)
        return "failed", None

    file_path.parent.mkdir(parents=True, exist_ok=True)

    if not _attempt_streams(streams, file_path, on_progress):
        err = RuntimeError(f"All stream URLs failed for track {track_id}")
        if on_error:
            on_error(track, err)
        _cleanup(file_path)
        _persist(track)
        return "failed", None

    # Rename if the actual format doesn't match the .flac extension
    actual_ext = _sniff_extension(file_path)
    if actual_ext != file_path.suffix:
        new_path = file_path.with_suffix(actual_ext)
        file_path.rename(new_path)
        file_path = new_path
        logger.info("Renamed to %s (actual format: %s)", file_path.name, actual_ext)

    logger.info("Downloaded: %s", file_path)
    _persist(track, str(file_path))
    _tag_file(config, file_path, track, artist, album)

    return "downloaded", str(file_path)


TRACK_DELAY = 0  # seconds between downloads (MusicBrainz calls provide natural delay)


def download_tracks(
    config: Config,
    tracks: list[dict],
    on_progress: Callable[[int, int, str, str | None], None] | None = None,
    on_error: Callable[[dict, Exception], None] | None = None,
) -> dict[str, int]:
    """Download a list of tracks with a delay between each.

    Args:
        config: Config with API endpoints and download_dir.
        tracks: List of track dicts, each with at least 'id', 'artist', 'album'.
        on_progress: Optional callback called after each track with
            (current_index, total, status, file_path).

    Returns:
        Dict with counts: {"downloaded": N, "failed": N}.
    """
    counts: dict[str, int] = {"downloaded": 0, "failed": 0}
    total = len(tracks)

    for i, track in enumerate(tracks):
        artist = track.get("hifi_artist") or "Unknown"
        album = track.get("hifi_album") or "Unknown"
        try:
            status, path = download_track(config, track, artist, album, on_error=on_error)
        except Exception as e:
            logger.error("Unexpected error downloading track %s: %s", track.get("hifi_id"), e)
            if on_error:
                on_error(track, e)
            counts["failed"] = counts.get("failed", 0) + 1
            if on_progress:
                on_progress(i + 1, total, "failed", None)
            continue
        display_status = "downloaded" if status in ("downloaded", "skipped") else status
        counts[display_status] = counts.get(display_status, 0) + 1

        if on_progress:
            on_progress(i + 1, total, display_status, path)

        if i < total - 1 and status == "downloaded":
            delay = int(config.download_delay or TRACK_DELAY)
            if delay:
                logger.debug("Waiting %ds before next track", delay)
                time.sleep(delay)

    return counts
