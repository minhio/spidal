from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path

import imageio_ffmpeg
import requests

from spidal.core.config import Config
from spidal.core.hifi import iter_stream_urls
from spidal.core.tagging import tag_flac, tag_m4a, tag_ogg, tag_webm
from spidal.core.track import Track

logger = logging.getLogger(__name__)

MIN_FILE_SIZE = 50 * 1024  # 50 KB
MAX_RETRIES = 3

TAGGERS = {
    ".flac": tag_flac,
    ".m4a": tag_m4a,
    ".ogg": tag_ogg,
    ".webm": tag_webm,
}


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


def _download_direct(url: str, file_path: Path) -> bool:
    """Download a file from a direct URL. Returns True on success."""
    resp = requests.get(url, stream=True, timeout=30)
    if not resp.ok:
        logger.warning("Download returned %s for %s", resp.status_code, url[:80])
        return False

    content_type = resp.headers.get("content-type", "")
    if any(t in content_type for t in ("xml", "html", "text")):
        logger.warning("Received %s instead of audio", content_type)
        return False

    with open(file_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            f.write(chunk)
    return True


def _download_dash(segments: list[str], file_path: Path) -> bool:
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


def _attempt_streams(streams: object, file_path: Path) -> bool:
    """Try each stream URL, cleaning up between attempts. Returns True on success."""
    for stream in streams:  # type: ignore[union-attr]
        if isinstance(stream, list):
            logger.info("Downloading %d DASH segments", len(stream))
            ok = _download_dash(stream, file_path)
        else:
            logger.info("Downloading from %s", stream[:80])
            ok = _download_direct(stream, file_path)

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


def _convert_m4a_to_flac(m4a_path: Path) -> Path:
    """Convert an M4A file to FLAC using ffmpeg. Returns the FLAC path."""
    flac_path = m4a_path.with_suffix(".flac")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [ffmpeg, "-i", str(m4a_path), "-c:a", "flac", str(flac_path)],
        check=True,
        capture_output=True,
    )
    m4a_path.unlink()
    logger.info("Converted M4A to FLAC: %s", flac_path.name)
    return flac_path


def _tag_file(file_path: Path, hifi_track: Track) -> None:
    """Tag the downloaded file using the appropriate tagger for its format."""
    tagger = TAGGERS.get(file_path.suffix)
    if tagger:
        tagger(str(file_path), hifi_track)
    else:
        logger.warning("No tagger for format %s: %s", file_path.suffix, file_path.name)


def download_track(config: Config, hifi_track: Track) -> tuple[str, str | None]:
    """Download a track from the hifi API.

    Args:
        config: Config with API endpoints and download_dir.
        hifi_track: Matched hifi Track (from match_tracks_by_isrc).

    Returns:
        Tuple of (status, file_path) where status is "downloaded", "existed",
        or "failed", and file_path is the path string (None on failure).
    """
    if not hifi_track.id or not hifi_track.artist or not hifi_track.album or not hifi_track.title:
        raise ValueError(f"Track missing required fields: {hifi_track}")

    stem = f"{int(hifi_track.track_number or 0):02d} - {_sanitize(hifi_track.title)}"

    download_dir = Path(config.download_dir)
    track_dir = download_dir / _sanitize(hifi_track.artist) / _sanitize(hifi_track.album)
    existing = next(track_dir.glob(f"{stem}.*"), None)
    if existing:
        logger.info("Already exists: %s", existing)
        return "existed", str(existing)

    try:
        streams = iter_stream_urls(config.get_apis(), hifi_track.id)
    except ConnectionError as e:
        logger.error("Failed to get stream URL for track %s: %s", hifi_track.id, e)
        return "failed", None

    tmp_path = track_dir / f"{stem}.tmp"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)

    if not _attempt_streams(streams, tmp_path):
        _cleanup(tmp_path)
        return "failed", None

    actual_ext = _sniff_extension(tmp_path)
    file_path = track_dir / f"{stem}{actual_ext}"
    tmp_path.rename(file_path)

    if file_path.suffix == ".m4a" and not config.disable_mp4_to_flac:
        file_path = _convert_m4a_to_flac(file_path)

    logger.info("Downloaded: %s", file_path)

    if not config.disable_tagging:
        _tag_file(file_path, hifi_track)

    return "downloaded", str(file_path)


def download_tracks(
    config: Config, hifi_tracks: list[Track]
) -> dict[str, list[tuple[Track, str | None]]]:
    """Download a list of tracks.

    Args:
        config: Config with API endpoints and download_dir.
        hifi_tracks: List of matched Track objects.

    Returns:
        Dict mapping status to list of (track, file_path) pairs:
        {"downloaded": [...], "existed": [...], "failed": [...]}.
        file_path is None for failed tracks.
    """
    results: dict[str, list[tuple[Track, str | None]]] = {
        "downloaded": [],
        "existed": [],
        "failed": [],
    }
    total = len(hifi_tracks)

    for i, hifi_track in enumerate(hifi_tracks):
        try:
            status, file_path = download_track(config, hifi_track)
        except Exception as e:
            logger.error("Unexpected error downloading track %s: %s", hifi_track.id, e)
            results["failed"].append((hifi_track, None))
            continue
        results[status].append((hifi_track, file_path))

        if i < total - 1 and status == "downloaded" and config.download_delay > 0:
            logger.debug("Waiting %ds before next track", config.download_delay)
            time.sleep(config.download_delay)

    return results
