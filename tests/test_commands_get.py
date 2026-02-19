"""Tests for commands/get.py — CLI download routing and track matching."""
from __future__ import annotations

import click
import pytest
from typer.testing import CliRunner

from spidal.cli import app
from spidal.config import Config

runner = CliRunner()


def _config(apis=None):
    config = Config()
    config._apis_cache = apis or ["https://api.example.com"]
    config.spotify_token = "tok"
    config.spotify_api_url = "https://api.spotify.com/v1"
    return config


class TestGetCommandRouting:
    def test_liked_routes_to_liked_downloader(self, mocker):
        mock_liked = mocker.patch("spidal.commands.get._download_liked", return_value=None)
        result = runner.invoke(app, ["get", "liked"])
        assert result.exit_code == 0
        mock_liked.assert_called_once()

    def test_monochrome_track_url_routes_correctly(self, mocker):
        mock_fn = mocker.patch("spidal.commands.get._download_monochrome_track", return_value=None)
        result = runner.invoke(app, ["get", "https://monochrome.tf/track/123"])
        assert result.exit_code == 0
        mock_fn.assert_called_once()
        assert mock_fn.call_args[0][1] == 123

    def test_monochrome_album_url_routes_correctly(self, mocker):
        mock_fn = mocker.patch("spidal.commands.get._download_monochrome_album", return_value=None)
        result = runner.invoke(app, ["get", "https://monochrome.tf/album/456"])
        assert result.exit_code == 0
        mock_fn.assert_called_once()
        assert mock_fn.call_args[0][1] == 456

    def test_spotify_track_url_routes_correctly(self, mocker):
        mock_fn = mocker.patch("spidal.commands.get._download_spotify_track", return_value=None)
        url = "https://open.spotify.com/track/479v5EqlFiLGtMDpQx0e7T"
        result = runner.invoke(app, ["get", url])
        assert result.exit_code == 0
        mock_fn.assert_called_once()

    def test_spotify_album_url_routes_correctly(self, mocker):
        mock_fn = mocker.patch("spidal.commands.get._download_spotify_album", return_value=None)
        result = runner.invoke(app, ["get", "https://open.spotify.com/album/6dVIqQ8qmQ5GBnJ9shOYGE"])
        assert result.exit_code == 0
        mock_fn.assert_called_once()

    def test_spotify_playlist_url_routes_correctly(self, mocker):
        mock_fn = mocker.patch("spidal.commands.get._download_spotify_playlist", return_value=None)
        result = runner.invoke(app, ["get", "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"])
        assert result.exit_code == 0
        mock_fn.assert_called_once()

    def test_unsupported_url_exits_nonzero(self):
        result = runner.invoke(app, ["get", "https://example.com/unsupported"])
        assert result.exit_code != 0
        assert "Unsupported URL" in result.output


class TestMatchSpotifyTracks:
    """Tests for _match_spotify_tracks — ISRC matching and nomatch persistence."""

    from spidal.commands.get import _match_spotify_tracks

    def _spotify_track(self, isrc="USTEST123456", title="Song", artist="Artist"):
        return {
            "id": "sp123",
            "name": title,
            "artists": [{"name": artist}],
            "album": {"name": "Album"},
            "external_ids": {"isrc": isrc},
        }

    def test_matches_tracks_by_isrc(self, mocker):
        from spidal.commands.get import _match_spotify_tracks

        config = _config()
        hifi_track = {"id": 1, "title": "Song", "artist": "Artist", "album": "Album", "isrc": "USTEST123456"}

        mocker.patch("spidal.matcher.match_track", return_value=hifi_track)
        mocker.patch("spidal.persistence.get_db")
        mocker.patch("spidal.persistence.save_nomatch")

        result = _match_spotify_tracks(config, [self._spotify_track()])
        assert len(result) == 1
        assert result[0]["id"] == 1

    def test_skips_tracks_without_isrc(self, mocker):
        from spidal.commands.get import _match_spotify_tracks

        config = _config()
        mocker.patch("spidal.matcher.match_track")
        mocker.patch("spidal.persistence.get_db")
        mocker.patch("spidal.persistence.save_nomatch")

        track = self._spotify_track()
        track["external_ids"] = {}
        result = _match_spotify_tracks(config, [track])
        assert result == []

    def test_saves_unmatched_to_nomatch(self, mocker):
        from spidal.commands.get import _match_spotify_tracks

        config = _config()
        mocker.patch("spidal.matcher.match_track", return_value=None)
        mock_db = mocker.Mock()
        mocker.patch("spidal.persistence.get_db", return_value=mock_db)
        mock_save = mocker.patch("spidal.persistence.save_nomatch")

        _match_spotify_tracks(config, [self._spotify_track()])
        mock_save.assert_called_once()

    def test_returns_empty_when_all_unmatched(self, mocker):
        from spidal.commands.get import _match_spotify_tracks

        config = _config()
        mocker.patch("spidal.matcher.match_track", return_value=None)
        mocker.patch("spidal.persistence.get_db", return_value=mocker.Mock())
        mocker.patch("spidal.persistence.save_nomatch")

        result = _match_spotify_tracks(config, [self._spotify_track(), self._spotify_track(isrc="OTHER")])
        assert result == []

    def test_preserves_spotify_album_name(self, mocker):
        from spidal.commands.get import _match_spotify_tracks

        config = _config()
        hifi_track = {"id": 1, "title": "Song", "artist": "Artist", "album": "Hifi Album", "isrc": "USTEST123456"}
        mocker.patch("spidal.matcher.match_track", return_value=hifi_track)
        mocker.patch("spidal.persistence.get_db")
        mocker.patch("spidal.persistence.save_nomatch")

        track = self._spotify_track()
        track["album"] = {"name": "Spotify Album"}
        result = _match_spotify_tracks(config, [track])
        assert result[0]["album"] == "Spotify Album"


class TestDownloadMonochromeTrack:
    def test_success(self, mocker, tmp_path):
        from spidal.commands.get import _download_monochrome_track

        config = _config()
        config.download_dir = str(tmp_path)

        track_info = {"id": 123, "title": "Song", "artist": "Artist", "album": "Album", "track_number": 1}
        mocker.patch("spidal.hifi.get_track_info", return_value=track_info)
        mocker.patch("spidal.download.download_track", return_value=("downloaded", "/path/song.flac"))

        _download_monochrome_track(config, 123)

    def test_raises_on_not_found(self, mocker, tmp_path):
        from spidal.commands.get import _download_monochrome_track

        config = _config()
        mocker.patch("spidal.hifi.get_track_info", return_value=None)

        with pytest.raises(click.exceptions.Exit):
            _download_monochrome_track(config, 999)


class TestDownloadMonochromeAlbum:
    def test_success(self, mocker, tmp_path):
        from spidal.commands.get import _download_monochrome_album

        config = _config()
        config.download_dir = str(tmp_path)

        tracks = [
            {"id": 1, "title": "Track 1", "artist": "Artist", "album": "Album", "track_number": 1},
            {"id": 2, "title": "Track 2", "artist": "Artist", "album": "Album", "track_number": 2},
        ]
        mocker.patch("spidal.hifi.get_album_tracks", return_value=("My Album", tracks))
        mocker.patch("spidal.download.download_tracks", return_value={"downloaded": 2, "failed": 0})

        _download_monochrome_album(config, 456)

    def test_raises_on_empty_album(self, mocker, tmp_path):
        from spidal.commands.get import _download_monochrome_album

        config = _config()
        mocker.patch("spidal.hifi.get_album_tracks", return_value=("Empty Album", []))

        with pytest.raises(click.exceptions.Exit):
            _download_monochrome_album(config, 456)
