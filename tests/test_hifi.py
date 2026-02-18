import base64

import pytest

from spidal.config import Config
from spidal.hifi import (
    _parse_album,
    _parse_dash_manifest,
    get_album_tracks,
    get_stream_url,
    get_track_info,
    iter_stream_urls,
    match_track,
    search_albums,
    search_track,
)


def _config(apis):
    config = Config()
    config._apis_cache = apis
    config.audio_quality = "HI_RES_LOSSLESS"
    return config


class TestSearchTrack:
    def test_success(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "version": "1.0",
            "data": {
                "items": [
                    {
                        "id": 12345,
                        "title": "Bohemian Rhapsody",
                        "artist": {"name": "Queen"},
                        "album": {"title": "A Night at the Opera"},
                        "trackNumber": 11,
                        "isrc": "GBAYE0601498",
                        "duration": 354,
                    }
                ]
            },
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        result = search_track(config, "Queen Bohemian Rhapsody")

        assert len(result) == 1
        assert result[0] == {
            "id": 12345,
            "title": "Bohemian Rhapsody",
            "artist": "Queen",
            "album": "A Night at the Opera",
            "track_number": 11,
            "isrc": "GBAYE0601498",
            "duration": 354,
        }

    def test_returns_multiple(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": {
                "items": [
                    {"id": 1, "title": "Song A", "artist": {"name": "A"}},
                    {"id": 2, "title": "Song B", "artist": {"name": "B"}},
                ]
            },
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        result = search_track(config, "query")
        assert len(result) == 2

    def test_no_results(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"version": "1.0", "data": {"items": []}}
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert search_track(config, "nonexistent") == []

    def test_no_apis_raises(self):
        config = _config([])

        with pytest.raises(ConnectionError, match="No hifi API endpoints available"):
            search_track(config, "query")

    def test_http_error_returns_empty(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = False
        mock_resp.status_code = 500
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert search_track(config, "query") == []

    def test_unwrapped_response(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "items": [{"id": 99, "name": "Track", "artists": [{"name": "Artist"}]}]
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        result = search_track(config, "query")
        assert result[0]["id"] == 99
        assert result[0]["title"] == "Track"
        assert result[0]["artist"] == "Artist"


class TestParseTrackEdgeCases:
    def test_null_artist_with_artists_list(self):
        from spidal.hifi import _parse_track

        raw = {"id": 1, "title": "Song", "artist": None, "artists": [{"name": "Bob"}]}
        assert _parse_track(raw)["artist"] == "Bob"

    def test_null_artist_empty_artists(self):
        from spidal.hifi import _parse_track

        raw = {"id": 1, "title": "Song", "artist": None, "artists": []}
        assert _parse_track(raw)["artist"] == "Unknown"

    def test_missing_artist_fields(self):
        from spidal.hifi import _parse_track

        raw = {"id": 1, "title": "Song"}
        assert _parse_track(raw)["artist"] == "Unknown"


class TestParseAlbum:
    def test_basic_fields(self):
        raw = {
            "id": 999,
            "title": "Some Album",
            "artist": {"name": "Some Artist"},
            "numberOfTracks": 12,
            "duration": 3600,
        }
        result = _parse_album(raw)
        assert result == {
            "id": 999,
            "title": "Some Album",
            "artist": "Some Artist",
            "numberOfTracks": 12,
            "duration": 3600,
        }

    def test_artists_list_fallback(self):
        raw = {
            "id": 1,
            "name": "Alt Name",
            "artists": [{"name": "List Artist"}],
        }
        result = _parse_album(raw)
        assert result["title"] == "Alt Name"
        assert result["artist"] == "List Artist"

    def test_null_artist_with_artists_list(self):
        raw = {
            "id": 1,
            "title": "Album",
            "artist": None,
            "artists": [{"name": "Bob"}],
        }
        assert _parse_album(raw)["artist"] == "Bob"

    def test_null_artist_empty_artists(self):
        raw = {"id": 1, "title": "Album", "artist": None, "artists": []}
        assert _parse_album(raw)["artist"] == "Unknown"


class TestSearchAlbums:
    def test_success(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": {
                "albums": {
                    "items": [
                        {
                            "id": 500,
                            "title": "Greatest Hits",
                            "artists": [{"name": "Queen"}],
                            "numberOfTracks": 17,
                            "duration": 4200,
                        }
                    ],
                    "totalNumberOfItems": 1,
                }
            }
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        result = search_albums(config, "Queen Greatest Hits")
        assert len(result) == 1
        assert result[0] == {
            "id": 500,
            "title": "Greatest Hits",
            "artist": "Queen",
            "numberOfTracks": 17,
            "duration": 4200,
        }
        from spidal.hifi import requests

        call_url = requests.get.call_args[0][0]
        assert "al=" in call_url

    def test_no_results(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": {"albums": {"items": [], "totalNumberOfItems": 0}}
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert search_albums(config, "nonexistent") == []

    def test_no_apis_raises(self):
        config = _config([])
        with pytest.raises(ConnectionError, match="No hifi API endpoints available"):
            search_albums(config, "query")


class TestMatchTrack:
    def test_matches_by_isrc(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": {
                "totalNumberOfItems": 3,
                "items": [
                    {
                        "id": 1,
                        "title": "Wrong",
                        "artist": {"name": "A"},
                        "isrc": "US0000000001",
                        "duration": 200,
                    },
                    {
                        "id": 2,
                        "title": "Right",
                        "artist": {"name": "B"},
                        "isrc": "US0000000002",
                        "duration": 180,
                    },
                    {
                        "id": 3,
                        "title": "Also Wrong",
                        "artist": {"name": "C"},
                        "isrc": "US0000000003",
                        "duration": 210,
                    },
                ],
            },
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        result = match_track(config, "query", "US0000000002")
        assert result is not None
        assert result["id"] == 2
        assert result["title"] == "Right"

    def test_searches_once(self, mocker):
        """API ignores offset/limit, so match_track only fetches one page."""
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": {
                "totalNumberOfItems": 100,
                "items": [
                    {
                        "id": 1,
                        "title": "Song",
                        "artist": {"name": "A"},
                        "isrc": "US0000000001",
                        "duration": 200,
                    },
                ],
            },
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        result = match_track(config, "query", "NOMATCH")
        assert result is None
        from spidal.hifi import requests

        assert requests.get.call_count == 1

    def test_no_isrc_match(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": {
                "totalNumberOfItems": 1,
                "items": [
                    {
                        "id": 1,
                        "title": "Song",
                        "artist": {"name": "A"},
                        "isrc": "US0000000001",
                        "duration": 200,
                    },
                ],
            },
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert match_track(config, "query", "NOMATCH") is None

    def test_empty_results(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"data": {"totalNumberOfItems": 0, "items": []}}
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert match_track(config, "query", "US0000000001") is None


class TestGetTrackInfo:
    def test_success(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": {
                "id": 12345,
                "title": "Song",
                "artist": {"name": "Artist"},
                "album": {"title": "Album"},
                "trackNumber": 5,
                "isrc": "US1234567890",
                "duration": 200,
            }
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        result = get_track_info(config, 12345)
        assert result == {
            "id": 12345,
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "track_number": 5,
            "isrc": "US1234567890",
            "duration": 200,
        }
        from spidal.hifi import requests

        requests.get.assert_called_once_with(
            "https://api1.example.com/info/?id=12345",
            timeout=10,
        )

    def test_not_found(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = False
        mock_resp.status_code = 404
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert get_track_info(config, 99999) is None


class TestParseDashManifest:
    def test_segment_template(self):
        manifest = """<?xml version="1.0"?>
        <MPD>
          <BaseURL>https://cdn.example.com/audio/</BaseURL>
          <SegmentTemplate initialization="init.mp4" media="seg-$Number$.m4s" startNumber="1"/>
          <SegmentTimeline>
            <S d="1024" r="2"/>
          </SegmentTimeline>
        </MPD>"""
        segments = _parse_dash_manifest(manifest)
        assert len(segments) == 4  # init + 3 segments (r=2 means repeat 2 → 3 total)
        assert segments[0] == "https://cdn.example.com/audio/init.mp4"
        assert segments[1] == "https://cdn.example.com/audio/seg-1.m4s"
        assert segments[3] == "https://cdn.example.com/audio/seg-3.m4s"

    def test_absolute_urls(self):
        manifest = """<MPD>
          <SegmentTemplate initialization="https://cdn.example.com/init.mp4"
                           media="https://cdn.example.com/seg-$Number$.m4s" startNumber="0"/>
          <SegmentTimeline><S d="512"/></SegmentTimeline>
        </MPD>"""
        segments = _parse_dash_manifest(manifest)
        assert segments[0] == "https://cdn.example.com/init.mp4"
        assert segments[1] == "https://cdn.example.com/seg-0.m4s"

    def test_segment_url_fallback(self):
        manifest = """<MPD>
          <BaseURL>https://cdn.example.com/</BaseURL>
          <SegmentURL media="chunk1.m4s"/>
          <SegmentURL media="chunk2.m4s"/>
        </MPD>"""
        segments = _parse_dash_manifest(manifest)
        assert len(segments) == 2
        assert segments[0] == "https://cdn.example.com/chunk1.m4s"

    def test_empty_manifest(self):
        assert _parse_dash_manifest("<MPD></MPD>") == []


class TestGetStreamUrl:
    def test_direct_url_field(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": {"streamUrl": "https://cdn.example.com/track.flac"}
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert get_stream_url(config, 123) == "https://cdn.example.com/track.flac"

    def test_original_track_url_preferred(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": {
                "originalTrackUrl": "https://cdn.example.com/original.flac",
                "streamUrl": "https://cdn.example.com/stream.flac",
            }
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert get_stream_url(config, 123) == "https://cdn.example.com/original.flac"

    def test_stream_nested_url(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": {"stream": {"url": "https://cdn.example.com/nested.flac"}}
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert get_stream_url(config, 123) == "https://cdn.example.com/nested.flac"

    def test_json_manifest(self, mocker):
        config = _config(["https://api1.example.com"])

        manifest = '{"urls": ["https://cdn.example.com/from-manifest.flac"]}'
        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"data": {"manifest": manifest}}
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert (
            get_stream_url(config, 123) == "https://cdn.example.com/from-manifest.flac"
        )

    def test_base64_json_manifest(self, mocker):
        config = _config(["https://api1.example.com"])

        manifest_json = '{"urls": ["https://cdn.example.com/b64.flac"]}'
        b64 = base64.b64encode(manifest_json.encode()).decode()
        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"data": {"manifest": b64}}
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert get_stream_url(config, 123) == "https://cdn.example.com/b64.flac"

    def test_dash_manifest(self, mocker):
        config = _config(["https://api1.example.com"])

        manifest = """<MPD>
          <BaseURL>https://cdn.example.com/</BaseURL>
          <SegmentTemplate initialization="init.mp4" media="seg-$Number$.m4s" startNumber="1"/>
          <SegmentTimeline><S d="1024"/></SegmentTimeline>
        </MPD>"""
        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"data": {"manifest": manifest}}
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        result = get_stream_url(config, 123)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_returns_any_url_without_filtering(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": {"streamUrl": "https://example.com/track/123"}
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert get_stream_url(config, 123) == "https://example.com/track/123"

    def test_uses_configured_quality(self, mocker):
        config = _config(["https://api1.example.com"])
        config.audio_quality = "LOSSLESS"

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": {"streamUrl": "https://cdn.example.com/track.flac"}
        }
        mock_get = mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        get_stream_url(config, 123)

        call_url = mock_get.call_args[0][0]
        assert "quality=LOSSLESS" in call_url

    def test_request_failure_raises(self, mocker):
        config = _config(["https://api1.example.com"])

        mock_resp = mocker.Mock()
        mock_resp.ok = False
        mock_resp.status_code = 500
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        with pytest.raises(ValueError, match="Failed to fetch stream data"):
            get_stream_url(config, 123)

    def test_tries_next_endpoint_on_failure(self, mocker):
        config = _config(["https://api1.example.com", "https://api2.example.com"])

        fail_resp = mocker.Mock()
        fail_resp.ok = False
        fail_resp.status_code = 403

        ok_resp = mocker.Mock()
        ok_resp.ok = True
        ok_resp.json.return_value = {
            "data": {"streamUrl": "https://cdn.example.com/track.flac"}
        }

        mocker.patch("spidal.hifi.requests.get", side_effect=[fail_resp, ok_resp])

        assert get_stream_url(config, 123) == "https://cdn.example.com/track.flac"

    def test_no_apis_raises_connection_error(self):
        config = _config([])

        with pytest.raises(ConnectionError, match="No hifi API endpoints available"):
            get_stream_url(config, 123)


class TestGetAlbumTracks:
    def test_success(self, mocker):
        config = _config(["https://api1.example.com"])
        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": {
                "title": "My Album",
                "numberOfTracks": 2,
                "items": [
                    {"id": 1, "title": "Track 1", "artist": {"name": "Artist"}, "trackNumber": 1},
                    {"id": 2, "title": "Track 2", "artist": {"name": "Artist"}, "trackNumber": 2},
                ],
            }
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        album_title, tracks = get_album_tracks(config, 42)
        assert album_title == "My Album"
        assert len(tracks) == 2
        assert tracks[0]["id"] == 1

    def test_raises_on_not_found(self, mocker):
        config = _config(["https://api1.example.com"])
        mock_resp = mocker.Mock()
        mock_resp.ok = False
        mock_resp.status_code = 404
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        with pytest.raises(ValueError, match="Album not found"):
            get_album_tracks(config, 999)

    def test_no_apis_raises(self):
        config = _config([])
        with pytest.raises(ConnectionError):
            get_album_tracks(config, 42)

    def test_unwraps_item_wrapper(self, mocker):
        config = _config(["https://api1.example.com"])
        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": {
                "title": "Album",
                "numberOfTracks": 1,
                "items": [
                    {"item": {"id": 5, "title": "Song", "artist": {"name": "A"}, "trackNumber": 1}, "type": "track"}
                ],
            }
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)
        _, tracks = get_album_tracks(config, 1)
        assert tracks[0]["id"] == 5


class TestIterStreamUrls:
    def test_yields_url_from_each_endpoint(self, mocker):
        config = _config(["https://api1.example.com", "https://api2.example.com"])

        def mock_get(url, timeout=None):
            resp = mocker.Mock()
            resp.ok = True
            resp.json.return_value = {"data": {"streamUrl": "https://cdn.example.com/track.flac"}}
            return resp

        mocker.patch("spidal.hifi.requests.get", side_effect=mock_get)
        urls = list(iter_stream_urls(config, 123))
        assert len(urls) == 2
        assert all(u == "https://cdn.example.com/track.flac" for u in urls)

    def test_skips_failed_endpoints(self, mocker):
        config = _config(["https://api1.example.com", "https://api2.example.com"])

        fail_resp = mocker.Mock()
        fail_resp.ok = False
        fail_resp.status_code = 500

        ok_resp = mocker.Mock()
        ok_resp.ok = True
        ok_resp.json.return_value = {"data": {"streamUrl": "https://cdn.example.com/track.flac"}}

        mocker.patch("spidal.hifi.requests.get", side_effect=[fail_resp, ok_resp])
        urls = list(iter_stream_urls(config, 123))
        assert len(urls) == 1

    def test_no_apis_raises(self):
        config = _config([])
        with pytest.raises(ConnectionError):
            list(iter_stream_urls(config, 123))
