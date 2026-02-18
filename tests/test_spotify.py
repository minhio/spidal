import pytest

from spidal.config import Config
from spidal.spotify import (
    get_album,
    get_album_tracks,
    get_liked_tracks,
    get_playlist_tracks,
    get_track,
    get_tracks,
    get_user_playlists,
    parse_spotify_url,
    parse_track_id,
)

VALID_ID = "479v5EqlFiLGtMDpQx0e7T"
VALID_URL = f"https://open.spotify.com/track/{VALID_ID}"


class TestParseTrackId:
    def test_from_url(self):
        assert parse_track_id(VALID_URL) == VALID_ID

    def test_from_url_with_query(self):
        assert parse_track_id(f"{VALID_URL}?si=abc123") == VALID_ID

    def test_bare_id(self):
        assert parse_track_id(VALID_ID) == VALID_ID

    def test_rejects_non_spotify_url(self):
        with pytest.raises(ValueError, match="Not a Spotify URL"):
            parse_track_id("https://example.com/track/abc")

    def test_rejects_non_track_spotify_url(self):
        with pytest.raises(ValueError, match="Not a Spotify track URL"):
            parse_track_id("https://open.spotify.com/album/abc")

    def test_rejects_invalid_bare_id(self):
        with pytest.raises(ValueError, match="Invalid Spotify track ID"):
            parse_track_id("abcd")

    def test_rejects_invalid_id_in_url(self):
        with pytest.raises(ValueError, match="Invalid Spotify track ID"):
            parse_track_id("https://open.spotify.com/track/abcd")


class TestParseSpotifyUrl:
    def test_track_url(self):
        resource_type, resource_id = parse_spotify_url(
            "https://open.spotify.com/track/479v5EqlFiLGtMDpQx0e7T"
        )
        assert resource_type == "track"
        assert resource_id == "479v5EqlFiLGtMDpQx0e7T"

    def test_album_url(self):
        resource_type, resource_id = parse_spotify_url(
            "https://open.spotify.com/album/6dVIqQ8qmQ5GBnJ9shOYGE"
        )
        assert resource_type == "album"
        assert resource_id == "6dVIqQ8qmQ5GBnJ9shOYGE"

    def test_playlist_url(self):
        resource_type, resource_id = parse_spotify_url(
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        )
        assert resource_type == "playlist"
        assert resource_id == "37i9dQZF1DXcBWIGoYBM5M"

    def test_url_with_query_params(self):
        resource_type, resource_id = parse_spotify_url(
            "https://open.spotify.com/track/479v5EqlFiLGtMDpQx0e7T?si=abc123"
        )
        assert resource_type == "track"
        assert resource_id == "479v5EqlFiLGtMDpQx0e7T"

    def test_url_with_trailing_slash(self):
        resource_type, resource_id = parse_spotify_url(
            "https://open.spotify.com/album/6dVIqQ8qmQ5GBnJ9shOYGE/"
        )
        assert resource_type == "album"
        assert resource_id == "6dVIqQ8qmQ5GBnJ9shOYGE"

    def test_rejects_non_spotify(self):
        with pytest.raises(ValueError, match="Not a Spotify URL"):
            parse_spotify_url("https://example.com/track/abc")

    def test_rejects_unsupported_type(self):
        with pytest.raises(ValueError, match="Unsupported Spotify URL"):
            parse_spotify_url("https://open.spotify.com/artist/abc123")


class TestGetTrack:
    def test_success(self, mocker):
        config = Config(
            spotify_token="tok", spotify_api_url="https://api.spotify.com/v1"
        )
        track_data = {"id": VALID_ID, "name": "Song"}

        mock_resp = mocker.Mock()
        mock_resp.json.return_value = track_data
        mock_resp.raise_for_status = mocker.Mock()
        mocker.patch("spidal.spotify.requests.get", return_value=mock_resp)

        result = get_track(config, f"{VALID_URL}?si=x")

        assert result == track_data
        from spidal.spotify import requests

        requests.get.assert_called_once_with(
            f"https://api.spotify.com/v1/tracks/{VALID_ID}",
            headers={"Authorization": "Bearer tok"},
        )

    def test_no_token_raises(self):
        config = Config(
            spotify_token=None, spotify_api_url="https://api.spotify.com/v1"
        )

        with pytest.raises(PermissionError, match="No Spotify token configured"):
            get_track(config, VALID_ID)

    def test_track_not_found_with_detail(self, mocker):
        config = Config(
            spotify_token="tok", spotify_api_url="https://api.spotify.com/v1"
        )

        mock_resp = mocker.Mock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = {
            "error": {"status": 404, "message": "non existing id"}
        }
        mocker.patch("spidal.spotify.requests.get", return_value=mock_resp)

        with pytest.raises(
            LookupError, match=rf"Track not found: {VALID_ID} \(non existing id\)"
        ):
            get_track(config, VALID_ID)

    def test_track_not_found_no_detail(self, mocker):
        config = Config(
            spotify_token="tok", spotify_api_url="https://api.spotify.com/v1"
        )

        mock_resp = mocker.Mock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = {}
        mocker.patch("spidal.spotify.requests.get", return_value=mock_resp)

        with pytest.raises(LookupError, match=rf"Track not found: {VALID_ID}$"):
            get_track(config, VALID_ID)

    def test_expired_token_with_detail(self, mocker):
        config = Config(
            spotify_token="expired", spotify_api_url="https://api.spotify.com/v1"
        )

        mock_resp = mocker.Mock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {
            "error": {"status": 401, "message": "The access token expired"}
        }
        mocker.patch("spidal.spotify.requests.get", return_value=mock_resp)

        with pytest.raises(
            PermissionError,
            match=r"Bad or expired Spotify token \(The access token expired\)",
        ):
            get_track(config, VALID_ID)

    def test_invalid_token_no_detail(self, mocker):
        config = Config(
            spotify_token="bad", spotify_api_url="https://api.spotify.com/v1"
        )

        mock_resp = mocker.Mock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {}
        mocker.patch("spidal.spotify.requests.get", return_value=mock_resp)

        with pytest.raises(PermissionError, match="Bad or expired Spotify token$"):
            get_track(config, VALID_ID)

    def test_rate_limit_exceeded(self, mocker):
        config = Config(
            spotify_token="tok", spotify_api_url="https://api.spotify.com/v1"
        )

        mock_resp = mocker.Mock()
        mock_resp.status_code = 429
        mock_resp.headers = {"Retry-After": "30"}
        mocker.patch("spidal.spotify.requests.get", return_value=mock_resp)

        with pytest.raises(
            ConnectionError, match="Spotify rate limit exceeded, retry after 30s"
        ):
            get_track(config, VALID_ID)

    def test_rate_limit_no_retry_after(self, mocker):
        config = Config(
            spotify_token="tok", spotify_api_url="https://api.spotify.com/v1"
        )

        mock_resp = mocker.Mock()
        mock_resp.status_code = 429
        mock_resp.headers = {}
        mocker.patch("spidal.spotify.requests.get", return_value=mock_resp)

        with pytest.raises(ConnectionError, match="Spotify rate limit exceeded$"):
            get_track(config, VALID_ID)


class TestGetTracks:
    def test_single_batch(self, mocker):
        config = Config(
            spotify_token="tok", spotify_api_url="https://api.spotify.com/v1"
        )

        mock_resp = mocker.Mock()
        mock_resp.raise_for_status = mocker.Mock()
        mock_resp.json.return_value = {
            "tracks": [
                {"id": "a", "name": "Track A", "external_ids": {"isrc": "US001"}},
                {"id": "b", "name": "Track B", "external_ids": {"isrc": "US002"}},
            ]
        }
        mocker.patch("spidal.spotify.requests.get", return_value=mock_resp)

        result = get_tracks(config, ["a", "b"])
        assert len(result) == 2
        assert result[0]["name"] == "Track A"

    def test_filters_null_tracks(self, mocker):
        config = Config(
            spotify_token="tok", spotify_api_url="https://api.spotify.com/v1"
        )

        mock_resp = mocker.Mock()
        mock_resp.raise_for_status = mocker.Mock()
        mock_resp.json.return_value = {
            "tracks": [
                {"id": "a", "name": "Track A"},
                None,
            ]
        }
        mocker.patch("spidal.spotify.requests.get", return_value=mock_resp)

        result = get_tracks(config, ["a", "invalid"])
        assert len(result) == 1

    def test_batches_over_50(self, mocker):
        config = Config(
            spotify_token="tok", spotify_api_url="https://api.spotify.com/v1"
        )

        ids = [f"id{i}" for i in range(75)]

        def mock_get(url, headers=None, params=None):
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            batch_ids = params["ids"].split(",")
            resp.json.return_value = {
                "tracks": [{"id": tid, "name": f"Track {tid}"} for tid in batch_ids]
            }
            return resp

        mocker.patch("spidal.spotify.requests.get", side_effect=mock_get)

        result = get_tracks(config, ids)
        assert len(result) == 75
        from spidal.spotify import requests

        assert requests.get.call_count == 2


class TestGetAlbumTracks:
    def test_single_page(self, mocker):
        config = Config(
            spotify_token="tok", spotify_api_url="https://api.spotify.com/v1"
        )
        album_data = {"name": "Album", "artists": [{"name": "Artist"}]}
        tracks_page = {
            "items": [{"name": "Track 1"}, {"name": "Track 2"}],
            "next": None,
        }

        def mock_get(url, headers=None):
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            if "/albums/" in url and "/tracks" not in url:
                resp.json.return_value = album_data
            else:
                resp.json.return_value = tracks_page
            return resp

        mocker.patch("spidal.spotify.requests.get", side_effect=mock_get)

        album_info, tracks = get_album_tracks(config, "abc123")
        assert album_info["name"] == "Album"
        assert len(tracks) == 2

    def test_pagination(self, mocker):
        config = Config(
            spotify_token="tok", spotify_api_url="https://api.spotify.com/v1"
        )
        album_data = {"name": "Album", "artists": [{"name": "Artist"}]}
        page1 = {
            "items": [{"name": "Track 1"}],
            "next": "https://api.spotify.com/v1/albums/abc/tracks?offset=1",
        }
        page2 = {
            "items": [{"name": "Track 2"}],
            "next": None,
        }

        responses = iter([album_data, page1, page2])

        def mock_get(url, headers=None):
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            resp.json.return_value = next(responses)
            return resp

        mocker.patch("spidal.spotify.requests.get", side_effect=mock_get)

        album_info, tracks = get_album_tracks(config, "abc123")
        assert len(tracks) == 2


class TestGetPlaylistTracks:
    def test_single_page(self, mocker):
        config = Config(
            spotify_token="tok", spotify_api_url="https://api.spotify.com/v1"
        )
        page = {
            "items": [
                {"track": {"name": "Track 1"}},
                {"track": {"name": "Track 2"}},
                {"track": None},  # removed track
            ],
            "next": None,
        }

        mock_resp = mocker.Mock()
        mock_resp.raise_for_status = mocker.Mock()
        mock_resp.json.return_value = page
        mocker.patch("spidal.spotify.requests.get", return_value=mock_resp)

        tracks = get_playlist_tracks(config, "playlist123")
        assert len(tracks) == 2
        assert tracks[0]["name"] == "Track 1"

    def test_pagination(self, mocker):
        config = Config(
            spotify_token="tok", spotify_api_url="https://api.spotify.com/v1"
        )
        page1 = {
            "items": [{"track": {"name": "Track 1"}}],
            "next": "https://api.spotify.com/v1/playlists/p/tracks?offset=1",
        }
        page2 = {
            "items": [{"track": {"name": "Track 2"}}],
            "next": None,
        }

        responses = iter([page1, page2])

        def mock_get(url, headers=None):
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            resp.json.return_value = next(responses)
            return resp

        mocker.patch("spidal.spotify.requests.get", side_effect=mock_get)

        tracks = get_playlist_tracks(config, "playlist123")
        assert len(tracks) == 2


class TestGetLikedTracks:
    def test_single_page(self, mocker):
        config = Config(
            spotify_token="tok", spotify_api_url="https://api.spotify.com/v1"
        )
        page = {
            "items": [
                {"track": {"name": "Liked 1"}},
                {"track": {"name": "Liked 2"}},
            ],
            "next": None,
        }

        mock_resp = mocker.Mock()
        mock_resp.raise_for_status = mocker.Mock()
        mock_resp.json.return_value = page
        mocker.patch("spidal.spotify.requests.get", return_value=mock_resp)

        tracks = get_liked_tracks(config)
        assert len(tracks) == 2
        assert tracks[0]["name"] == "Liked 1"

    def test_pagination(self, mocker):
        config = Config(
            spotify_token="tok", spotify_api_url="https://api.spotify.com/v1"
        )
        page1 = {
            "items": [{"track": {"name": "Liked 1"}}],
            "next": "https://api.spotify.com/v1/me/tracks?offset=1",
        }
        page2 = {
            "items": [{"track": {"name": "Liked 2"}}],
            "next": None,
        }

        responses = iter([page1, page2])

        def mock_get(url, headers=None):
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            resp.json.return_value = next(responses)
            return resp

        mocker.patch("spidal.spotify.requests.get", side_effect=mock_get)

        tracks = get_liked_tracks(config)
        assert len(tracks) == 2


class TestGetUserPlaylists:
    def test_returns_all_playlists(self, mocker):
        config = Config(spotify_token="tok", spotify_api_url="https://api.spotify.com/v1")
        page = {
            "items": [
                {"id": "pl1", "name": "Playlist 1", "tracks": {"total": 10}},
                {"id": "pl2", "name": "Playlist 2", "tracks": {"total": 5}},
            ],
            "next": None,
        }
        mock_resp = mocker.Mock()
        mock_resp.raise_for_status = mocker.Mock()
        mock_resp.json.return_value = page
        mocker.patch("spidal.spotify.requests.get", return_value=mock_resp)

        playlists = get_user_playlists(config)
        assert len(playlists) == 2
        assert playlists[0]["id"] == "pl1"

    def test_paginates(self, mocker):
        config = Config(spotify_token="tok", spotify_api_url="https://api.spotify.com/v1")
        page1 = {
            "items": [{"id": "pl1", "name": "P1"}],
            "next": "https://api.spotify.com/v1/me/playlists?offset=1",
        }
        page2 = {"items": [{"id": "pl2", "name": "P2"}], "next": None}
        responses = iter([page1, page2])

        def mock_get(url, headers=None):
            resp = mocker.Mock()
            resp.raise_for_status = mocker.Mock()
            resp.json.return_value = next(responses)
            return resp

        mocker.patch("spidal.spotify.requests.get", side_effect=mock_get)
        playlists = get_user_playlists(config)
        assert len(playlists) == 2

    def test_raises_on_expired_token(self, mocker):
        config = Config(spotify_token="expired", spotify_api_url="https://api.spotify.com/v1")
        mock_resp = mocker.Mock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {}
        mocker.patch("spidal.spotify.requests.get", return_value=mock_resp)
        with pytest.raises(PermissionError):
            get_user_playlists(config)


class TestGetAlbum:
    def test_returns_album_metadata(self, mocker):
        config = Config(spotify_token="tok", spotify_api_url="https://api.spotify.com/v1")
        album_data = {
            "id": "abc123",
            "name": "Test Album",
            "artists": [{"name": "Test Artist"}],
            "release_date": "2023-01-01",
        }
        mock_resp = mocker.Mock()
        mock_resp.raise_for_status = mocker.Mock()
        mock_resp.json.return_value = album_data
        mocker.patch("spidal.spotify.requests.get", return_value=mock_resp)

        result = get_album(config, "abc123")
        assert result["name"] == "Test Album"
        assert result["id"] == "abc123"

    def test_raises_on_expired_token(self, mocker):
        config = Config(spotify_token="expired", spotify_api_url="https://api.spotify.com/v1")
        mock_resp = mocker.Mock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {}
        mocker.patch("spidal.spotify.requests.get", return_value=mock_resp)
        with pytest.raises(PermissionError):
            get_album(config, "abc123")


class TestGetTracksEdgeCases:
    def test_empty_list_returns_empty(self, mocker):
        config = Config(spotify_token="tok", spotify_api_url="https://api.spotify.com/v1")
        mock_get = mocker.patch("spidal.spotify.requests.get")
        result = get_tracks(config, [])
        assert result == []
        mock_get.assert_not_called()

    def test_400_raises_http_error(self, mocker):
        config = Config(spotify_token="tok", spotify_api_url="https://api.spotify.com/v1")
        mock_resp = mocker.Mock()
        mock_resp.status_code = 400
        mock_resp.raise_for_status.side_effect = Exception("400 Bad Request")
        mock_resp.json.return_value = {}
        mocker.patch("spidal.spotify.requests.get", return_value=mock_resp)
        with pytest.raises(Exception):
            get_track(config, VALID_ID)
