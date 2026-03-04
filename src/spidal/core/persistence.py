from __future__ import annotations

from dataclasses import dataclass, fields
import logging

from tinydb import TinyDB, where
from tinydb.table import Table

from spidal.core.config import STATE_DIR
from spidal.core.track import Track

logger = logging.getLogger(__name__)

DB_PATH = STATE_DIR / "db.json"

TRACKS_TABLE = "tracks"

@dataclass
class TrackEntry:
    isrc: str | None = None
    spotify_id: str | None = None
    spotify_title: str | None = None
    spotify_artist: str | None = None
    spotify_album: str | None = None
    spotify_track_number: int | None = None
    spotify_duration: int | None = None
    hifi_id: int | None = None
    hifi_title: str | None = None
    hifi_artist: str | None = None
    hifi_album: str | None = None
    hifi_track_number: int = 0
    hifi_duration: float | None = None
    file_path: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> TrackEntry:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_tracks(cls, spotify: Track | None = None, hifi: Track | None = None, file_path: str | None = None) -> TrackEntry:
        spotify = spotify or Track()
        hifi = hifi or Track()
        return cls(
            isrc=spotify.isrc or hifi.isrc,
            spotify_id=spotify.id,
            spotify_title=spotify.title,
            spotify_artist=spotify.artist,
            spotify_album=spotify.album,
            spotify_track_number=spotify.track_number,
            spotify_duration=spotify.duration,
            hifi_id=hifi.id,
            hifi_title=hifi.title,
            hifi_artist=hifi.artist,
            hifi_album=hifi.album,
            hifi_track_number=hifi.track_number or 0,
            hifi_duration=hifi.duration,
            file_path=file_path,
        )


def get_db() -> TinyDB:
    """Open (or create) the database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return TinyDB(DB_PATH)


def _tracks(db: TinyDB) -> Table:
    return db.table(TRACKS_TABLE)


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def save_track(db: TinyDB, record: TrackEntry) -> None:
    """Upsert a track record keyed by ISRC."""
    if not record.isrc:
        logger.warning("Track %s has no ISRC, skipping persistence", record.hifi_id)
        return

    _tracks(db).upsert(record.__dict__, where("isrc") == record.isrc)
    logger.debug("Saved track %s (ISRC=%s, file=%s)", record.hifi_id, record.isrc, record.file_path)



# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def get_track(db: TinyDB, isrc: str) -> TrackEntry | None:
    """Look up a track by ISRC. Returns None if not found."""
    results = _tracks(db).search(where("isrc") == isrc)
    return TrackEntry.from_dict(results[0]) if results else None


def get_all_tracks(db: TinyDB) -> list[TrackEntry]:
    """Return all records."""
    return [TrackEntry.from_dict(r) for r in _tracks(db).all()]


def get_downloaded_tracks(db: TinyDB) -> list[TrackEntry]:
    """Return records with a file_path (successfully downloaded)."""
    return [TrackEntry.from_dict(r) for r in _tracks(db).search(where("file_path").test(lambda v: v is not None))]


def get_failed_tracks(db: TinyDB) -> list[TrackEntry]:
    """Return records where the hifi match was found but download failed."""
    return [TrackEntry.from_dict(r) for r in _tracks(db).search(
        where("hifi_id").test(lambda v: v is not None)
        & where("file_path").test(lambda v: v is None)
    )]


def get_all_nomatch(db: TinyDB) -> list[TrackEntry]:
    """Return records with no hifi match."""
    return [TrackEntry.from_dict(r) for r in _tracks(db).search(where("hifi_id").test(lambda v: v is None))]


# ---------------------------------------------------------------------------
# Playlists table
# ---------------------------------------------------------------------------

PLAYLISTS_TABLE = "playlists"


@dataclass
class PlaylistEntry:
    spotify_playlist_id: str
    spotify_track_id: str
    hifi_track_id: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> PlaylistEntry:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def _playlists(db: TinyDB) -> Table:
    return db.table(PLAYLISTS_TABLE)


def save_playlist_track(db: TinyDB, entry: PlaylistEntry) -> None:
    """Upsert a playlist entry keyed by (spotify_playlist_id, spotify_track_id)."""
    _playlists(db).upsert(
        entry.__dict__,
        (where("spotify_playlist_id") == entry.spotify_playlist_id) & (where("spotify_track_id") == entry.spotify_track_id),
    )
    logger.debug("Saved playlist track: playlist=%s spotify=%s hifi=%s", entry.spotify_playlist_id, entry.spotify_track_id, entry.hifi_track_id)


def get_playlist_tracks_db(db: TinyDB, spotify_playlist_id: str) -> list[PlaylistEntry]:
    """Return all track entries for a playlist."""
    return [PlaylistEntry.from_dict(r) for r in _playlists(db).search(where("spotify_playlist_id") == spotify_playlist_id)]


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
