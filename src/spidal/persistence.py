from __future__ import annotations

import logging

from tinydb import TinyDB, where
from tinydb.table import Table

from spidal.config import STATE_DIR

logger = logging.getLogger(__name__)

DB_PATH = STATE_DIR / "db.json"


LIBRARY_TABLE = "library"


def get_db() -> TinyDB:
    """Open (or create) the database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return TinyDB(DB_PATH)


def _library(db: TinyDB) -> Table:
    """Return the 'library' table."""
    return db.table(LIBRARY_TABLE)


def save_track(
    db: TinyDB,
    track: dict,
    status: str,
    file_path: str | None = None,
) -> None:
    """Upsert a track record keyed by ISRC."""
    isrc = track.get("isrc")
    if not isrc:
        logger.warning("Track %s has no ISRC, skipping persistence", track.get("id"))
        return

    record = {
        "isrc": isrc,
        "id": track.get("id"),
        "title": track.get("title") or track.get("name"),
        "artist": track.get("artist"),
        "album": track.get("album"),
        "track_number": track.get("track_number"),
        "duration": track.get("duration"),
        "status": status,
        "file_path": file_path,
    }
    _library(db).upsert(record, where("isrc") == isrc)
    logger.debug("Saved track %s (ISRC=%s, status=%s)", track.get("id"), isrc, status)


def get_all_tracks(db: TinyDB) -> list[dict]:
    """Return all records from the library table."""
    return _library(db).all()


def get_downloaded_tracks(db: TinyDB) -> list[dict]:
    """Return library records with status 'downloaded'."""
    return _library(db).search(where("status") == "downloaded")


def get_failed_tracks(db: TinyDB) -> list[dict]:
    """Return library records with status 'failed' (download errors)."""
    return _library(db).search(where("status") == "failed")


def get_track(db: TinyDB, isrc: str) -> dict | None:
    """Look up a track by ISRC. Returns None if not found."""
    results = _library(db).search(where("isrc") == isrc)
    return results[0] if results else None


NOMATCH_TABLE = "nomatch"


def _nomatch(db: TinyDB) -> Table:
    """Return the 'nomatch' table."""
    return db.table(NOMATCH_TABLE)


def get_all_nomatch(db: TinyDB) -> list[dict]:
    """Return all records from the nomatch table."""
    return _nomatch(db).all()


PLAYLISTS_TABLE = "playlists"


def _playlists(db: TinyDB) -> Table:
    return db.table(PLAYLISTS_TABLE)


def save_playlist_download(
    db: TinyDB, playlist_id: str, downloaded: int, total: int
) -> None:
    """Upsert a playlist download record keyed by playlist_id."""
    _playlists(db).upsert(
        {"playlist_id": playlist_id, "downloaded": downloaded, "total": total},
        where("playlist_id") == playlist_id,
    )
    logger.debug("Saved playlist progress: %s (%d/%d)", playlist_id, downloaded, total)


def get_playlist_download(db: TinyDB, playlist_id: str) -> dict | None:
    """Return the persisted download record for a playlist, or None."""
    results = _playlists(db).search(where("playlist_id") == playlist_id)
    return results[0] if results else None


def save_nomatch(db: TinyDB, spotify_track: dict) -> None:
    """Persist a Spotify track that couldn't be matched, keyed by ISRC."""
    isrc = spotify_track.get("external_ids", {}).get("isrc")
    if not isrc:
        logger.warning(
            "Nomatch track %s has no ISRC, skipping persistence",
            spotify_track.get("id"),
        )
        return
    artists = ", ".join(
        a["name"] for a in spotify_track.get("artists", [])
    )
    record = {
        "isrc": isrc,
        "title": spotify_track.get("name"),
        "artist": artists,
        "album": spotify_track.get("album", {}).get("name"),
        "spotify_id": spotify_track.get("id"),
    }
    _nomatch(db).upsert(record, where("isrc") == isrc)
    logger.debug("Saved nomatch: %s - %s (ISRC=%s)", artists, spotify_track.get("name"), isrc)
