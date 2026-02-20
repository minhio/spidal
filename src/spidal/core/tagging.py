from __future__ import annotations

import logging
from pathlib import Path

import musicbrainzngs
from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.mp4 import MP4, MP4FreeForm
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

logger = logging.getLogger(__name__)

musicbrainzngs.set_useragent("spidal", "0.1", "https://github.com/minhio/spidal")
musicbrainzngs.set_rate_limit(limit_or_interval=1.0)


def _lookup_isrc(isrc: str) -> dict | None:
    """Look up a recording by ISRC on MusicBrainz.

    Returns the first matching recording dict, or None on failure/no match.
    """
    try:
        result = musicbrainzngs.get_recordings_by_isrc(
            isrc, includes=["releases", "artists"]
        )
    except musicbrainzngs.WebServiceError as e:
        logger.warning("MusicBrainz ISRC lookup failed for %s: %s", isrc, e)
        return None

    recordings = result.get("isrc", {}).get("recording-list", [])
    if not recordings:
        logger.info("No MusicBrainz recording found for ISRC %s", isrc)
        return None

    return recordings[0]


def _lookup_recording(recording_mbid: str) -> dict | None:
    """Fetch tag data for a recording by MBID."""
    try:
        result = musicbrainzngs.get_recording_by_id(
            recording_mbid, includes=["tags"]
        )
        return result.get("recording")
    except musicbrainzngs.WebServiceError as e:
        logger.warning("MusicBrainz recording lookup failed for %s: %s", recording_mbid, e)
        return None


def _lookup_release(release_id: str, recording_mbid: str) -> tuple[int | None, int | None, int | None]:
    """Fetch disc and track count data from a release.

    Returns:
        (disc_number, disc_total, track_total) — any may be None on failure.
    """
    try:
        result = musicbrainzngs.get_release_by_id(
            release_id, includes=["recordings", "media"]
        )
    except musicbrainzngs.WebServiceError as e:
        logger.warning("MusicBrainz release lookup failed for %s: %s", release_id, e)
        return None, None, None

    medium_list = result.get("release", {}).get("medium-list", [])
    disc_total = len(medium_list) if medium_list else None

    for medium in medium_list:
        for track in medium.get("track-list", []):
            if track.get("recording", {}).get("id") == recording_mbid:
                disc_number = medium.get("position")
                track_total = medium.get("track-count")
                return (
                    int(disc_number) if disc_number is not None else None,
                    int(disc_total) if disc_total is not None else None,
                    int(track_total) if track_total is not None else None,
                )

    return None, disc_total, None


def _best_release(recording: dict) -> dict | None:
    """Pick the most suitable release (prefer releases with dates)."""
    releases = recording.get("release-list", [])
    if not releases:
        return None
    for release in releases:
        if release.get("date"):
            return release
    return releases[0]


def _best_genre(recording: dict) -> str | None:
    """Pick the top genre from a recording's genre-list or tag-list."""
    genres = recording.get("genre-list", [])
    if genres:
        top = max(genres, key=lambda g: int(g.get("count", 0)))
        return top.get("name", "").title() or None

    tags = recording.get("tag-list", [])
    if tags:
        top = max(tags, key=lambda t: int(t.get("count", 0)))
        return top.get("name", "").title() or None

    return None


def _artist_credit_name(credits: list) -> str:
    """Flatten an artist-credit list into a display string."""
    parts: list[str] = []
    for credit in credits:
        if isinstance(credit, dict):
            parts.append(credit.get("artist", {}).get("name", ""))
            parts.append(credit.get("joinphrase", ""))
        else:
            parts.append(str(credit))
    return "".join(parts).strip()


def _build_base_tags(track: dict, artist: str, album: str) -> dict[str, str]:
    """Build tags from hifi data only (no MusicBrainz calls).

    Keys use VorbisComment naming (TITLE, ARTIST, TRACKNUMBER, etc.).
    Values are always strings.
    """
    title = track.get("title") or track.get("name") or ""
    track_number = track.get("track_number") or 0
    isrc = track.get("isrc") or ""

    tags: dict[str, str] = {}
    if title:
        tags["TITLE"] = title
    if artist:
        tags["ARTIST"] = artist
    if album:
        tags["ALBUM"] = album
    if track_number:
        tags["TRACKNUMBER"] = str(int(track_number))
    if isrc:
        tags["ISRC"] = isrc
    return tags


def _enrich_with_mb(tags: dict[str, str], isrc: str) -> None:
    """Enrich a tag dict in-place with MusicBrainz data."""
    recording = _lookup_isrc(isrc)
    if not recording:
        return

    recording_mbid = recording.get("id", "")
    if recording_mbid:
        tags["MUSICBRAINZ_TRACKID"] = recording_mbid

    recording_detail = _lookup_recording(recording_mbid) if recording_mbid else None
    genre = _best_genre(recording_detail or {})
    if genre:
        tags["GENRE"] = genre

    release = _best_release(recording)
    if not release:
        return

    date = release.get("date", "")
    if date:
        tags["DATE"] = date

    release_mbid = release.get("id", "")
    if release_mbid:
        tags["MUSICBRAINZ_ALBUMID"] = release_mbid

    credits = release.get("artist-credit", [])
    if credits:
        album_artist = _artist_credit_name(credits)
        if album_artist:
            tags["ALBUMARTIST"] = album_artist

        first = credits[0] if credits else {}
        if isinstance(first, dict):
            artist_mbid = first.get("artist", {}).get("id", "")
            if artist_mbid:
                tags["MUSICBRAINZ_ARTISTID"] = artist_mbid

    if release_mbid and recording_mbid:
        disc_num, disc_total, track_total = _lookup_release(release_mbid, recording_mbid)
        if disc_num is not None:
            tags["DISCNUMBER"] = str(disc_num)
        if disc_total is not None:
            tags["DISCTOTAL"] = str(disc_total)
        if track_total is not None:
            tags["TRACKTOTAL"] = str(track_total)


def _build_tags(track: dict, artist: str, album: str) -> dict[str, str]:
    """Build a neutral tag dict from hifi data enriched with MusicBrainz lookups."""
    tags = _build_base_tags(track, artist, album)
    isrc = tags.get("ISRC", "")
    if isrc:
        _enrich_with_mb(tags, isrc)
    return tags


# iTunes freeform tag keys for MusicBrainz IDs
_MP4_FREEFORM = {
    "ISRC": "----:com.apple.iTunes:ISRC",
    "MUSICBRAINZ_TRACKID": "----:com.apple.iTunes:MusicBrainz Track Id",
    "MUSICBRAINZ_ALBUMID": "----:com.apple.iTunes:MusicBrainz Album Id",
    "MUSICBRAINZ_ARTISTID": "----:com.apple.iTunes:MusicBrainz Artist Id",
}

# Simple string tag mapping from VorbisComment keys to iTunes MP4 keys
_MP4_SIMPLE = {
    "TITLE": "\xa9nam",
    "ARTIST": "\xa9ART",
    "ALBUM": "\xa9alb",
    "ALBUMARTIST": "aART",
    "DATE": "\xa9day",
    "GENRE": "\xa9gen",
}


def _write_vorbiscomment(audio: object, tags: dict[str, str], file_path: str) -> None:
    """Write a neutral tag dict to any mutagen VorbisComment-backed file."""
    for key, value in tags.items():
        audio[key] = value  # type: ignore[index]
    try:
        audio.save()  # type: ignore[attr-defined]
        logger.info("Tagged: %s (%d tags)", file_path, len(tags))
    except Exception as e:
        logger.warning("Failed to save tags for %s: %s", file_path, e)


def tag_flac(file_path: str, track: dict, artist: str, album: str) -> None:
    """Write VorbisComment tags to a FLAC file. Best-effort."""
    path = Path(file_path)
    if not path.exists():
        logger.warning("Cannot tag non-existent file: %s", file_path)
        return
    try:
        audio = FLAC(file_path)
    except Exception as e:
        logger.warning("Failed to open FLAC for tagging %s: %s", file_path, e)
        return
    _write_vorbiscomment(audio, _build_tags(track, artist, album), file_path)


def tag_ogg(file_path: str, track: dict, artist: str, album: str) -> None:
    """Write VorbisComment tags to an OGG file (Vorbis or Opus). Best-effort."""
    path = Path(file_path)
    if not path.exists():
        logger.warning("Cannot tag non-existent file: %s", file_path)
        return
    try:
        audio = MutagenFile(file_path)
    except Exception as e:
        logger.warning("Failed to open OGG for tagging %s: %s", file_path, e)
        return
    if not isinstance(audio, (OggVorbis, OggOpus)):
        logger.warning("Unexpected OGG type %s for %s", type(audio).__name__, file_path)
        return
    _write_vorbiscomment(audio, _build_tags(track, artist, album), file_path)


def tag_webm(file_path: str, track: dict, artist: str, album: str) -> None:
    """Tag a WebM file. mutagen has no native WebM support — logs a warning."""
    logger.warning("WebM tagging not supported, file will be untagged: %s", file_path)


def tag_m4a(file_path: str, track: dict, artist: str, album: str) -> None:
    """Write iTunes-style tags to an M4A file.

    Best-effort: tag errors are logged but never raise.
    """
    path = Path(file_path)
    if not path.exists():
        logger.warning("Cannot tag non-existent file: %s", file_path)
        return

    try:
        audio = MP4(file_path)
    except Exception as e:
        logger.warning("Failed to open M4A for tagging %s: %s", file_path, e)
        return

    tags = _build_tags(track, artist, album)

    for vorbis_key, mp4_key in _MP4_SIMPLE.items():
        if vorbis_key in tags:
            audio[mp4_key] = [tags[vorbis_key]]

    # Track number: trkn expects [(track_num, total_tracks)]
    if "TRACKNUMBER" in tags:
        track_num = int(tags["TRACKNUMBER"])
        track_total = int(tags["TRACKTOTAL"]) if "TRACKTOTAL" in tags else 0
        audio["trkn"] = [(track_num, track_total)]

    # Disc number: disk expects [(disc_num, disc_total)]
    if "DISCNUMBER" in tags:
        disc_num = int(tags["DISCNUMBER"])
        disc_total = int(tags["DISCTOTAL"]) if "DISCTOTAL" in tags else 0
        audio["disk"] = [(disc_num, disc_total)]

    # Freeform tags for ISRC and MusicBrainz IDs
    for vorbis_key, mp4_key in _MP4_FREEFORM.items():
        if vorbis_key in tags:
            audio[mp4_key] = [MP4FreeForm(tags[vorbis_key].encode())]

    try:
        audio.save()
        logger.info("Tagged: %s (%d tags)", file_path, len(tags))
    except Exception as e:
        logger.warning("Failed to save tags for %s: %s", file_path, e)
