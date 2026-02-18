"""Integration tests for hifi API operations.

These tests make real network requests and require working API endpoints.
Run with: uv run pytest -m integration tests/test_hifi_integration.py
"""

from __future__ import annotations

import pytest

from spidal.config import Config, DEFAULTS
from spidal.download import download_track, download_tracks
from spidal.hifi import (
    _search_albums_page,
    _search_page,
    get_album_tracks,
    get_stream_url,
    get_track_info,
    match_track,
    search_albums,
    search_track,
)


@pytest.fixture()
def config():
    """Load a real config with API endpoints from the default instances file."""
    config = Config(hifi_api_file=DEFAULTS["hifi_api_file"])
    apis = config.get_apis()
    assert len(apis) > 0, "No API endpoints available — cannot run integration tests"
    return config


@pytest.mark.integration
class TestSearchTrackIntegration:
    def test_search_returns_results(self, config):
        results = search_track(config, "Bohemian Rhapsody")
        assert len(results) > 0
        track = results[0]
        assert "id" in track
        assert track["title"] is not None
        assert track["artist"] is not None

    def test_search_page_returns_total(self, config):
        tracks, total = _search_page(config, "Queen")
        assert len(tracks) > 0
        assert total > 0

    def test_search_no_results(self, config):
        results = search_track(config, "xyzzy_nonexistent_track_12345")
        assert results == []


@pytest.mark.integration
class TestSearchAlbumsIntegration:
    def test_search_returns_albums(self, config):
        results = search_albums(config, "A Night at the Opera")
        assert len(results) > 0
        album = results[0]
        assert "id" in album
        assert album["title"] is not None
        assert album["artist"] is not None
        assert album["numberOfTracks"] is not None
        assert album["numberOfTracks"] > 0

    def test_search_albums_page_returns_total(self, config):
        albums, total = _search_albums_page(config, "Queen")
        assert len(albums) > 0
        assert total > 0


@pytest.mark.integration
class TestMatchTrackIntegration:
    def test_match_by_isrc(self, config):
        # First search to find a track with a known ISRC
        results = search_track(config, "Bohemian Rhapsody Queen")
        tracks_with_isrc = [t for t in results if t.get("isrc")]
        assert len(tracks_with_isrc) > 0, "No tracks with ISRC found in search"

        target = tracks_with_isrc[0]
        isrc = target["isrc"]

        track = match_track(config, "Bohemian Rhapsody Queen", isrc)
        assert track is not None
        assert track["isrc"] == isrc
        assert track["id"] == target["id"]

    def test_no_match(self, config):
        result = match_track(config, "Queen Bohemian Rhapsody", "XXXXXXXXXXXX")
        assert result is None


@pytest.mark.integration
class TestGetAlbumTracksIntegration:
    def test_fetch_album_tracks(self, config):
        # First search for an album to get a valid ID
        albums = search_albums(config, "A Night at the Opera Queen")
        assert len(albums) > 0
        album = albums[0]

        title, tracks = get_album_tracks(config, album["id"])
        assert title is not None
        assert len(tracks) > 0
        for track in tracks:
            assert "id" in track
            assert track["title"] is not None
            assert track["artist"] is not None


@pytest.mark.integration
class TestGetTrackInfoIntegration:
    def test_fetch_track_info(self, config):
        # Search for a track to get a valid ID
        results = search_track(config, "Bohemian Rhapsody Queen")
        assert len(results) > 0
        track_id = results[0]["id"]

        info = get_track_info(config, track_id)
        assert info is not None
        assert info["id"] == track_id
        assert info["title"] is not None
        assert info["isrc"] is not None


@pytest.mark.integration
class TestGetStreamUrlIntegration:
    def test_fetch_stream_url(self, config):
        # Search for a track to get a valid ID
        results = search_track(config, "Bohemian Rhapsody Queen")
        assert len(results) > 0
        track_id = results[0]["id"]

        url = get_stream_url(config, track_id)
        assert url is not None
        if isinstance(url, str):
            assert url.startswith("http")
        else:
            # DASH segments
            assert len(url) > 0
            assert url[0].startswith("http")


@pytest.mark.integration
class TestDownloadTrackIntegration:
    def test_download_single_track(self, config, tmp_path):
        config.download_dir = str(tmp_path)

        # Search and pick a track
        results = search_track(config, "Bohemian Rhapsody Queen")
        assert len(results) > 0
        track = results[0]

        progress_calls = []

        def on_progress(current: int, total: int) -> None:
            progress_calls.append((current, total))

        status, path = download_track(
            config, track, track["artist"], track.get("album") or "Unknown", on_progress
        )
        assert status == "downloaded"
        assert path is not None
        assert path.endswith(".flac")

        from pathlib import Path

        file = Path(path)
        assert file.exists()
        assert file.stat().st_size > 50 * 1024  # MIN_FILE_SIZE
        assert len(progress_calls) > 0

    def test_download_skips_existing(self, config, tmp_path):
        config.download_dir = str(tmp_path)

        results = search_track(config, "Bohemian Rhapsody Queen")
        assert len(results) > 0
        track = results[0]

        # Download once
        status1, path1 = download_track(
            config, track, track["artist"], track.get("album") or "Unknown"
        )
        assert status1 == "downloaded"

        # Download again — should skip
        status2, path2 = download_track(
            config, track, track["artist"], track.get("album") or "Unknown"
        )
        assert status2 == "downloaded"
        assert path2 == path1

    def test_download_tracks_batch(self, config, tmp_path, mocker):
        config.download_dir = str(tmp_path)

        # Eliminate delay between downloads for faster tests
        mocker.patch("spidal.download.TRACK_DELAY", 0)

        # Search for an album and download first 2 tracks
        albums = search_albums(config, "A Night at the Opera Queen")
        assert len(albums) > 0
        _title, tracks = get_album_tracks(config, albums[0]["id"])
        assert len(tracks) >= 2
        batch = tracks[:2]

        progress_calls = []

        def on_progress(
            current: int, total: int, status: str, path: str | None
        ) -> None:
            progress_calls.append((current, total, status, path))

        counts = download_tracks(config, batch, on_progress)
        assert counts["downloaded"] >= 1
        assert len(progress_calls) == 2
        assert progress_calls[-1][0] == 2
        assert progress_calls[-1][1] == 2
