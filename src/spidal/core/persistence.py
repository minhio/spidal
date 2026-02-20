from __future__ import annotations

import logging

from tinydb import TinyDB, where
from tinydb.table import Table

from spidal.core.config import STATE_DIR

logger = logging.getLogger(__name__)

DB_PATH = STATE_DIR / "db.json"

TRACKS_TABLE = "tracks"


def get_db() -> TinyDB:
    """Open (or create) the database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return TinyDB(DB_PATH)


def _tracks(db: TinyDB) -> Table:
    return db.table(TRACKS_TABLE)


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def save_track(
    db: TinyDB,
    track: dict,
    file_path: str | None = None,
) -> None:
    """Upsert a track record keyed by ISRC."""
    isrc = track.get("isrc")
    if not isrc:
        logger.warning("Track %s has no ISRC, skipping persistence", track.get("hifi_id"))
        return

    record = {
        "isrc": isrc,
        "spotify_id": track.get("spotify_id"),
        "hifi_id": track.get("hifi_id"),
        "hifi_title": track.get("hifi_title"),
        "hifi_artist": track.get("hifi_artist"),
        "hifi_album": track.get("hifi_album"),
        "hifi_track_number": track.get("hifi_track_number") or 0,
        "hifi_duration": track.get("hifi_duration"),
        "spotify_title": track.get("spotify_title"),
        "spotify_artist": track.get("spotify_artist"),
        "spotify_album": track.get("spotify_album"),
        "spotify_track_number": track.get("spotify_track_number"),
        "spotify_duration": track.get("spotify_duration"),
        "file_path": file_path,
    }
    _tracks(db).upsert(record, where("isrc") == isrc)
    logger.debug("Saved track %s (ISRC=%s, file=%s)", track.get("hifi_id"), isrc, file_path)



# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def get_track(db: TinyDB, isrc: str) -> dict | None:
    """Look up a track by ISRC. Returns None if not found."""
    results = _tracks(db).search(where("isrc") == isrc)
    return results[0] if results else None


def get_all_tracks(db: TinyDB) -> list[dict]:
    """Return all records."""
    return _tracks(db).all()


def get_downloaded_tracks(db: TinyDB) -> list[dict]:
    """Return records with a file_path (successfully downloaded)."""
    return _tracks(db).search(where("file_path").test(lambda v: v is not None))


def get_failed_tracks(db: TinyDB) -> list[dict]:
    """Return records where the hifi match was found but download failed."""
    return _tracks(db).search(
        where("hifi_id").test(lambda v: v is not None)
        & where("file_path").test(lambda v: v is None)
    )


def get_all_nomatch(db: TinyDB) -> list[dict]:
    """Return records with no hifi match."""
    return _tracks(db).search(where("hifi_id").test(lambda v: v is None))


# ---------------------------------------------------------------------------
# Playlists table
# ---------------------------------------------------------------------------

PLAYLISTS_TABLE = "playlists"


def _playlists(db: TinyDB) -> Table:
    return db.table(PLAYLISTS_TABLE)


def save_playlist_track(
    db: TinyDB, playlist_id: str, spotify_id: str, track_id: int | None = None
) -> None:
    """Upsert a track entry for a playlist, keyed by (playlist_id, spotify_id)."""
    _playlists(db).upsert(
        {"playlist_id": playlist_id, "spotify_id": spotify_id, "track_id": track_id},
        (where("playlist_id") == playlist_id) & (where("spotify_id") == spotify_id),
    )
    logger.debug("Saved playlist track: playlist=%s spotify=%s hifi=%s", playlist_id, spotify_id, track_id)


def get_playlist_tracks_db(db: TinyDB, playlist_id: str) -> list[dict]:
    """Return all track entries for a playlist."""
    return _playlists(db).search(where("playlist_id") == playlist_id)


def is_track_downloaded(db: TinyDB, spotify_id: str) -> bool:
    """Return True if the Spotify track has been successfully downloaded.

    Joins against the tracks table: looks for a record with matching
    spotify_id and a non-null file_path.
    """
    return bool(
        _tracks(db).search(
            (where("spotify_id") == spotify_id)
            & where("file_path").test(lambda v: v is not None)
        )
    )
