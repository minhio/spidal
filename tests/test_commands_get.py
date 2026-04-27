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
    config.audio_quality = "HI_RES_LOSSLESS"
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


class TestDownloadSpotifyTracks:
    """Tests for download_spotify_tracks — interleaved match + download per track."""

    def _spotify_track(self, isrc="USTEST123456", title="Song", artist="Artist", sp_id="sp123"):
        return {
            "id": sp_id,
            "name": title,
            "artists": [{"name": artist}],
            "album": {"name": "Album"},
            "external_ids": {"isrc": isrc},
        }

    def test_matched_tracks_are_downloaded(self, mocker):
        from spidal.download import download_spotify_tracks

        config = _config()
        hifi_track = {"id": 1, "title": "Song", "artist": "Artist", "album": "Album", "isrc": "USTEST123456"}

        mocker.patch("spidal.hifi.match_track", return_value=hifi_track)
        mocker.patch("spidal.download.get_db")
        mocker.patch("spidal.download.save_nomatch")
        mock_dl = mocker.patch(
            "spidal.download.download_track", return_value=("downloaded", "/p.flac")
        )

        counts = download_spotify_tracks(config, [self._spotify_track()])
        assert counts == {"downloaded": 1, "failed": 0, "no_match": 0}
        mock_dl.assert_called_once()

    def test_skipped_tracks_count_as_downloaded(self, mocker):
        from spidal.download import download_spotify_tracks

        config = _config()
        hifi_track = {"id": 1, "title": "Song", "artist": "Artist", "album": "Album", "isrc": "USTEST123456"}
        mocker.patch("spidal.hifi.match_track", return_value=hifi_track)
        mocker.patch("spidal.download.get_db")
        mocker.patch("spidal.download.save_nomatch")
        mocker.patch(
            "spidal.download.download_track", return_value=("skipped", "/p.flac")
        )

        counts = download_spotify_tracks(config, [self._spotify_track()])
        assert counts["downloaded"] == 1

    def test_tracks_without_isrc_count_as_no_match(self, mocker):
        from spidal.download import download_spotify_tracks

        config = _config()
        mocker.patch("spidal.hifi.match_track")
        mock_db = mocker.Mock()
        mocker.patch("spidal.download.get_db", return_value=mock_db)
        mock_save = mocker.patch("spidal.download.save_nomatch")
        mock_dl = mocker.patch("spidal.download.download_track")

        track = self._spotify_track()
        track["external_ids"] = {}
        counts = download_spotify_tracks(config, [track])
        assert counts == {"downloaded": 0, "failed": 0, "no_match": 1}
        mock_save.assert_called_once()
        mock_dl.assert_not_called()

    def test_unmatched_tracks_saved_to_nomatch(self, mocker):
        from spidal.download import download_spotify_tracks

        config = _config()
        mocker.patch("spidal.hifi.match_track", return_value=None)
        mock_db = mocker.Mock()
        mocker.patch("spidal.download.get_db", return_value=mock_db)
        mock_save = mocker.patch("spidal.download.save_nomatch")
        mock_dl = mocker.patch("spidal.download.download_track")

        counts = download_spotify_tracks(config, [self._spotify_track()])
        assert counts["no_match"] == 1
        mock_save.assert_called_once()
        mock_dl.assert_not_called()

    def test_failed_downloads_count_as_failed(self, mocker):
        from spidal.download import download_spotify_tracks

        config = _config()
        hifi_track = {"id": 1, "title": "Song", "artist": "Artist", "album": "Album", "isrc": "USTEST123456"}
        mocker.patch("spidal.hifi.match_track", return_value=hifi_track)
        mocker.patch("spidal.download.get_db")
        mocker.patch("spidal.download.save_nomatch")
        mocker.patch("spidal.download.download_track", return_value=("failed", None))

        counts = download_spotify_tracks(config, [self._spotify_track()])
        assert counts == {"downloaded": 0, "failed": 1, "no_match": 0}

    def test_interleaves_match_and_download(self, mocker):
        """Ensure download_track is called between match_track calls, not after all matches."""
        from spidal.download import download_spotify_tracks

        config = _config()
        order: list[str] = []

        def fake_match(cfg, query, isrc):
            order.append(f"match:{isrc}")
            return {"id": 1, "title": "Song", "artist": "Artist", "album": "Album", "isrc": isrc}

        def fake_dl(cfg, track, artist, album, on_progress=None):
            order.append(f"download:{track['isrc']}")
            return "downloaded", "/p.flac"

        mocker.patch("spidal.hifi.match_track", side_effect=fake_match)
        mocker.patch("spidal.download.download_track", side_effect=fake_dl)
        mocker.patch("spidal.download.get_db")
        mocker.patch("spidal.download.save_nomatch")

        tracks = [
            self._spotify_track(isrc="ISRC_A", sp_id="a"),
            self._spotify_track(isrc="ISRC_B", sp_id="b"),
        ]
        download_spotify_tracks(config, tracks)
        assert order == [
            "match:ISRC_A",
            "download:ISRC_A",
            "match:ISRC_B",
            "download:ISRC_B",
        ]

    def test_on_progress_fires_per_track(self, mocker):
        from spidal.download import download_spotify_tracks

        config = _config()
        hifi_track = {"id": 1, "title": "Song", "artist": "Artist", "album": "Album", "isrc": "USTEST123456"}
        mocker.patch(
            "spidal.hifi.match_track",
            side_effect=[hifi_track, None],
        )
        mocker.patch("spidal.download.get_db", return_value=mocker.Mock())
        mocker.patch("spidal.download.save_nomatch")
        mocker.patch(
            "spidal.download.download_track", return_value=("downloaded", "/p.flac")
        )

        calls: list[tuple[int, int, str]] = []
        download_spotify_tracks(
            config,
            [self._spotify_track(isrc="A"), self._spotify_track(isrc="B")],
            on_progress=lambda i, total, status, path: calls.append((i, total, status)),
        )
        assert calls == [(1, 2, "downloaded"), (2, 2, "no_match")]

    def test_preserves_spotify_album_name_when_downloading(self, mocker):
        from spidal.download import download_spotify_tracks

        config = _config()
        hifi_track = {"id": 1, "title": "Song", "artist": "Artist", "album": "Hifi Album", "isrc": "USTEST123456"}
        mocker.patch("spidal.hifi.match_track", return_value=hifi_track)
        mocker.patch("spidal.download.get_db")
        mocker.patch("spidal.download.save_nomatch")

        captured: dict[str, str] = {}

        def fake_dl(cfg, track, artist, album, on_progress=None):
            captured["album"] = album
            return "downloaded", "/p.flac"

        mocker.patch("spidal.download.download_track", side_effect=fake_dl)

        track = self._spotify_track()
        track["album"] = {"name": "Spotify Album"}
        download_spotify_tracks(config, [track])
        assert captured["album"] == "Spotify Album"


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
