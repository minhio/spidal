from __future__ import annotations

from tinydb import TinyDB

from spidal.persistence import (
    LIBRARY_TABLE,
    NOMATCH_TABLE,
    get_all_nomatch,
    get_all_tracks,
    get_downloaded_tracks,
    get_failed_tracks,
    get_playlist_download,
    get_track,
    save_nomatch,
    save_playlist_download,
    save_track,
)


def _make_track(**overrides: object) -> dict:
    base = {
        "isrc": "USRC12345678",
        "id": 123,
        "title": "Test Song",
        "artist": "Test Artist",
        "album": "Test Album",
        "track_number": 1,
        "duration": 240,
    }
    base.update(overrides)
    return base


class TestSaveAndGetTrack:
    def test_save_and_retrieve(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        track = _make_track()
        save_track(db, track, "downloaded", "/music/test.flac")

        result = get_track(db, "USRC12345678")
        assert result is not None
        assert result["isrc"] == "USRC12345678"
        assert result["title"] == "Test Song"
        assert result["status"] == "downloaded"
        assert result["file_path"] == "/music/test.flac"

    def test_upsert_updates_existing(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        track = _make_track()
        save_track(db, track, "downloaded", "/music/v1.flac")
        save_track(db, track, "downloaded", "/music/v2.flac")

        result = get_track(db, "USRC12345678")
        assert result["file_path"] == "/music/v2.flac"
        # Only one record should exist
        assert len(db.table(LIBRARY_TABLE).all()) == 1

    def test_get_missing_isrc(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        assert get_track(db, "NONEXISTENT") is None

    def test_skip_track_without_isrc(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        track = _make_track()
        del track["isrc"]
        save_track(db, track, "downloaded", "/music/test.flac")

        assert len(db.table(LIBRARY_TABLE).all()) == 0

    def test_save_failed_track(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        track = _make_track()
        save_track(db, track, "failed")

        result = get_track(db, "USRC12345678")
        assert result is not None
        assert result["status"] == "failed"
        assert result["file_path"] is None


def _make_spotify_track(**overrides: object) -> dict:
    base = {
        "id": "spotify123",
        "name": "Test Song",
        "artists": [{"name": "Test Artist"}],
        "album": {"name": "Test Album"},
        "external_ids": {"isrc": "USRC12345678"},
    }
    base.update(overrides)
    return base


class TestSaveNomatch:
    def test_save_and_retrieve(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        st = _make_spotify_track()
        save_nomatch(db, st)

        records = db.table(NOMATCH_TABLE).all()
        assert len(records) == 1
        assert records[0]["isrc"] == "USRC12345678"
        assert records[0]["title"] == "Test Song"
        assert records[0]["artist"] == "Test Artist"
        assert records[0]["album"] == "Test Album"
        assert records[0]["spotify_id"] == "spotify123"

    def test_upsert_by_isrc(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        save_nomatch(db, _make_spotify_track())
        save_nomatch(db, _make_spotify_track(name="Updated Song"))

        records = db.table(NOMATCH_TABLE).all()
        assert len(records) == 1
        assert records[0]["title"] == "Updated Song"

    def test_skip_without_isrc(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        st = _make_spotify_track(external_ids={})
        save_nomatch(db, st)

        assert len(db.table(NOMATCH_TABLE).all()) == 0


class TestQueryFunctions:
    def test_get_all_tracks_empty(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        assert get_all_tracks(db) == []

    def test_get_all_tracks_returns_all(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        save_track(db, _make_track(isrc="ISRC1", id=1), "downloaded", "/a.flac")
        save_track(db, _make_track(isrc="ISRC2", id=2), "failed")
        assert len(get_all_tracks(db)) == 2

    def test_get_downloaded_tracks(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        save_track(db, _make_track(isrc="ISRC1", id=1), "downloaded", "/a.flac")
        save_track(db, _make_track(isrc="ISRC2", id=2), "failed")
        results = get_downloaded_tracks(db)
        assert len(results) == 1
        assert results[0]["isrc"] == "ISRC1"

    def test_get_failed_tracks(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        save_track(db, _make_track(isrc="ISRC1", id=1), "downloaded", "/a.flac")
        save_track(db, _make_track(isrc="ISRC2", id=2), "failed")
        save_track(db, _make_track(isrc="ISRC3", id=3), "failed")
        results = get_failed_tracks(db)
        assert len(results) == 2
        assert all(r["status"] == "failed" for r in results)

    def test_get_all_nomatch(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        assert get_all_nomatch(db) == []
        save_nomatch(db, _make_spotify_track(external_ids={"isrc": "ISRC1"}))
        save_nomatch(db, _make_spotify_track(id="sp2", external_ids={"isrc": "ISRC2"}))
        assert len(get_all_nomatch(db)) == 2


class TestPlaylistDownload:
    def test_save_and_retrieve(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        save_playlist_download(db, "pl123", 10, 50)
        result = get_playlist_download(db, "pl123")
        assert result is not None
        assert result["playlist_id"] == "pl123"
        assert result["downloaded"] == 10
        assert result["total"] == 50

    def test_upsert_updates_progress(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        save_playlist_download(db, "pl123", 5, 50)
        save_playlist_download(db, "pl123", 30, 50)
        result = get_playlist_download(db, "pl123")
        assert result["downloaded"] == 30

    def test_get_nonexistent_returns_none(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        assert get_playlist_download(db, "nonexistent") is None

    def test_multiple_playlists_independent(self, tmp_path):
        db = TinyDB(tmp_path / "db.json")
        save_playlist_download(db, "pl1", 10, 20)
        save_playlist_download(db, "pl2", 5, 100)
        assert get_playlist_download(db, "pl1")["downloaded"] == 10
        assert get_playlist_download(db, "pl2")["downloaded"] == 5
