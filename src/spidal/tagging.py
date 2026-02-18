from __future__ import annotations

import logging
from pathlib import Path

import musicbrainzngs
from mutagen.flac import FLAC

logger = logging.getLogger(__name__)

musicbrainzngs.set_useragent("spidal", "0.1", "https://github.com/spidal/spidal")
musicbrainzngs.set_rate_limit(limit_or_interval=1.0)


def _lookup_isrc(isrc: str) -> dict | None:
    """Look up a recording by ISRC on MusicBrainz.

    Returns the first matching recording dict, or None on failure/no match.
    Includes releases, artists, and genre/tag data.
    """
    try:
        result = musicbrainzngs.get_recordings_by_isrc(
            isrc, includes=["releases", "artists", "genres", "tags"]
        )
    except musicbrainzngs.WebServiceError as e:
        logger.warning("MusicBrainz ISRC lookup failed for %s: %s", isrc, e)
        return None

    recordings = result.get("isrc", {}).get("recording-list", [])
    if not recordings:
        logger.info("No MusicBrainz recording found for ISRC %s", isrc)
        return None

    return recordings[0]


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


def tag_flac(file_path: str, track: dict, artist: str, album: str) -> None:
    """Write VorbisComment tags to a FLAC file.

    Uses hifi track data as the primary source, enriched with two MusicBrainz
    API calls (ISRC lookup + release detail) for date, genre, disc/track
    counts, and MusicBrainz IDs.
    Best-effort: tag errors are logged but never raise.
    """
    path = Path(file_path)
    if not path.exists():
        logger.warning("Cannot tag non-existent file: %s", file_path)
        return

    try:
        audio = FLAC(file_path)
    except Exception as e:
        logger.warning("Failed to open FLAC for tagging %s: %s", file_path, e)
        return

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

    if isrc:
        recording = _lookup_isrc(isrc)
        if recording:
            recording_mbid = recording.get("id", "")
            if recording_mbid:
                tags["MUSICBRAINZ_TRACKID"] = recording_mbid

            genre = _best_genre(recording)
            if genre:
                tags["GENRE"] = genre

            release = _best_release(recording)
            if release:
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
                    disc_num, disc_total, track_total = _lookup_release(
                        release_mbid, recording_mbid
                    )
                    if disc_num is not None:
                        tags["DISCNUMBER"] = str(disc_num)
                    if disc_total is not None:
                        tags["DISCTOTAL"] = str(disc_total)
                    if track_total is not None:
                        tags["TRACKTOTAL"] = str(track_total)

    for key, value in tags.items():
        audio[key] = value

    try:
        audio.save()
        logger.info("Tagged: %s (%d tags)", file_path, len(tags))
    except Exception as e:
        logger.warning("Failed to save tags for %s: %s", file_path, e)
