import pytest

from spidal.hifi import (
    _parse_album,
    _parse_dash_manifest,
    get_album_tracks,
    get_track_info,
    iter_stream_urls,
    match_track,
    search_albums,
    search_tracks,
    search_tracks,
)



class TestSearchTrack:
    def test_success(self, mocker):
        apis = ["https://api1.example.com"]

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

        result, _ = search_tracks(apis, "Queen Bohemian Rhapsody")

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
        apis = ["https://api1.example.com"]

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

        result, _ = search_tracks(apis, "query")
        assert len(result) == 2

    def test_no_results(self, mocker):
        apis = ["https://api1.example.com"]

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"version": "1.0", "data": {"items": []}}
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert search_tracks(apis, "nonexistent")[0] == []

    def test_no_apis_raises(self):
        apis = []

        with pytest.raises(ConnectionError, match="No hifi API endpoints available"):
            search_tracks(apis, "query")

    def test_http_error_returns_empty(self, mocker):
        apis = ["https://api1.example.com"]

        mock_resp = mocker.Mock()
        mock_resp.ok = False
        mock_resp.status_code = 500
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert search_tracks(apis, "query")[0] == []

    def test_unwrapped_response(self, mocker):
        apis = ["https://api1.example.com"]

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "items": [{"id": 99, "title": "Track", "artists": [{"name": "Artist"}]}]
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        result, _ = search_tracks(apis, "query")
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
            "title": "Alt Name",
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
        apis = ["https://api1.example.com"]

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

        result, _ = search_albums(apis, "Queen Greatest Hits")
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
        apis = ["https://api1.example.com"]

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "data": {"albums": {"items": [], "totalNumberOfItems": 0}}
        }
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert search_albums(apis, "nonexistent")[0] == []

    def test_no_apis_raises(self):
        apis = []
        with pytest.raises(ConnectionError, match="No hifi API endpoints available"):
            search_albums(apis, "query")


class TestMatchTrack:
    def test_matches_by_isrc(self, mocker):
        apis = ["https://api1.example.com"]

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

        result = match_track(apis, "query", "US0000000002")
        assert result is not None
        assert result["id"] == 2
        assert result["title"] == "Right"

    def test_searches_once(self, mocker):
        """API ignores offset/limit, so match_track only fetches one page."""
        apis = ["https://api1.example.com"]

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

        result = match_track(apis, "query", "NOMATCH")
        assert result is None
        from spidal.hifi import requests

        assert requests.get.call_count == 1

    def test_no_isrc_match(self, mocker):
        apis = ["https://api1.example.com"]

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

        assert match_track(apis, "query", "NOMATCH") is None

    def test_empty_results(self, mocker):
        apis = ["https://api1.example.com"]

        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"data": {"totalNumberOfItems": 0, "items": []}}
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert match_track(apis, "query", "US0000000001") is None


class TestGetTrackInfo:
    def test_success(self, mocker):
        apis = ["https://api1.example.com"]

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

        result = get_track_info(apis, 12345)
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
        apis = ["https://api1.example.com"]

        mock_resp = mocker.Mock()
        mock_resp.ok = False
        mock_resp.status_code = 404
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        assert get_track_info(apis, 99999) is None


class TestParseDashManifest:
    def test_segment_template(self):
        manifest = """<?xml version="1.0"?>
        <MPD>
          <Period>
            <AdaptationSet mimeType="audio/mp4">
              <Representation id="audio" bandwidth="320000">
                <BaseURL>https://cdn.example.com/audio/</BaseURL>
                <SegmentTemplate initialization="init.mp4" media="seg-$Number$.m4s" startNumber="1">
                  <SegmentTimeline>
                    <S d="1024" r="2"/>
                  </SegmentTimeline>
                </SegmentTemplate>
              </Representation>
            </AdaptationSet>
          </Period>
        </MPD>"""
        segments = _parse_dash_manifest(manifest)
        assert len(segments) == 4  # init + 3 segments (r=2 means repeat 2 → 3 total)
        assert segments[0] == "https://cdn.example.com/audio/init.mp4"
        assert segments[1] == "https://cdn.example.com/audio/seg-1.m4s"
        assert segments[3] == "https://cdn.example.com/audio/seg-3.m4s"

    def test_absolute_urls(self):
        manifest = """<MPD>
          <Period>
            <AdaptationSet mimeType="audio/mp4">
              <Representation id="audio" bandwidth="128000">
                <SegmentTemplate initialization="https://cdn.example.com/init.mp4"
                                 media="https://cdn.example.com/seg-$Number$.m4s" startNumber="0">
                  <SegmentTimeline><S d="512"/></SegmentTimeline>
                </SegmentTemplate>
              </Representation>
            </AdaptationSet>
          </Period>
        </MPD>"""
        segments = _parse_dash_manifest(manifest)
        assert segments[0] == "https://cdn.example.com/init.mp4"
        assert segments[1] == "https://cdn.example.com/seg-0.m4s"

    def test_segment_url_fallback(self):
        manifest = """<MPD>
          <Period>
            <AdaptationSet mimeType="audio/mp4">
              <BaseURL>https://cdn.example.com/</BaseURL>
              <Representation id="audio" bandwidth="128000">
                <SegmentList>
                  <SegmentURL media="chunk1.m4s"/>
                  <SegmentURL media="chunk2.m4s"/>
                </SegmentList>
              </Representation>
            </AdaptationSet>
          </Period>
        </MPD>"""
        segments = _parse_dash_manifest(manifest)
        assert len(segments) == 2
        assert segments[0] == "https://cdn.example.com/chunk1.m4s"

    def test_empty_manifest(self):
        assert _parse_dash_manifest("<MPD></MPD>") == []

    def test_highest_bandwidth_selected(self):
        manifest = """<MPD>
          <Period>
            <AdaptationSet mimeType="audio/mp4">
              <Representation id="low" bandwidth="128000">
                <SegmentTemplate initialization="low-init.mp4" media="low-seg-$Number$.m4s" startNumber="1">
                  <SegmentTimeline><S d="1024"/></SegmentTimeline>
                </SegmentTemplate>
              </Representation>
              <Representation id="high" bandwidth="320000">
                <SegmentTemplate initialization="high-init.mp4" media="high-seg-$Number$.m4s" startNumber="1">
                  <SegmentTimeline><S d="1024"/></SegmentTimeline>
                </SegmentTemplate>
              </Representation>
            </AdaptationSet>
          </Period>
        </MPD>"""
        segments = _parse_dash_manifest(manifest)
        assert segments[0] == "high-init.mp4"
        assert segments[1] == "high-seg-1.m4s"

    def test_representation_id_template(self):
        manifest = """<MPD>
          <Period>
            <AdaptationSet mimeType="audio/mp4">
              <Representation id="audio-aac" bandwidth="128000">
                <SegmentTemplate initialization="$RepresentationID$-init.mp4"
                                 media="$RepresentationID$-seg-$Number$.m4s" startNumber="1">
                  <SegmentTimeline><S d="1024"/></SegmentTimeline>
                </SegmentTemplate>
              </Representation>
            </AdaptationSet>
          </Period>
        </MPD>"""
        segments = _parse_dash_manifest(manifest)
        assert segments[0] == "audio-aac-init.mp4"
        assert segments[1] == "audio-aac-seg-1.m4s"

    def test_time_template(self):
        manifest = """<MPD>
          <Period>
            <AdaptationSet mimeType="audio/mp4">
              <Representation id="audio" bandwidth="128000">
                <SegmentTemplate media="seg-$Time$.m4s">
                  <SegmentTimeline>
                    <S t="0" d="1000"/>
                    <S t="1000" d="1000"/>
                  </SegmentTimeline>
                </SegmentTemplate>
              </Representation>
            </AdaptationSet>
          </Period>
        </MPD>"""
        segments = _parse_dash_manifest(manifest)
        assert segments == ["seg-0.m4s", "seg-1000.m4s"]

    def test_zero_padded_number(self):
        manifest = """<MPD>
          <Period>
            <AdaptationSet mimeType="audio/mp4">
              <Representation id="audio" bandwidth="128000">
                <SegmentTemplate initialization="init.mp4" media="seg-$Number%05d$.m4s" startNumber="1">
                  <SegmentTimeline><S d="1024" r="1"/></SegmentTimeline>
                </SegmentTemplate>
              </Representation>
            </AdaptationSet>
          </Period>
        </MPD>"""
        segments = _parse_dash_manifest(manifest)
        assert segments[1] == "seg-00001.m4s"
        assert segments[2] == "seg-00002.m4s"

    def test_namespace_stripped(self):
        manifest = """<?xml version="1.0"?>
        <MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
          <Period>
            <AdaptationSet mimeType="audio/mp4">
              <Representation id="audio" bandwidth="128000">
                <SegmentTemplate initialization="init.mp4" media="seg-$Number$.m4s" startNumber="1">
                  <SegmentTimeline><S d="1024"/></SegmentTimeline>
                </SegmentTemplate>
              </Representation>
            </AdaptationSet>
          </Period>
        </MPD>"""
        segments = _parse_dash_manifest(manifest)
        assert len(segments) == 2
        assert segments[0] == "init.mp4"


    def test_multi_level_base_url(self):
        """Deepest BaseURL wins — Representation-level takes priority over MPD-level."""
        manifest = """<MPD>
          <BaseURL>https://mpd.example.com/</BaseURL>
          <Period>
            <AdaptationSet mimeType="audio/mp4">
              <Representation id="audio" bandwidth="128000">
                <BaseURL>https://cdn.example.com/audio/</BaseURL>
                <SegmentTemplate initialization="init.mp4" media="seg-$Number$.m4s" startNumber="1">
                  <SegmentTimeline><S d="1024"/></SegmentTimeline>
                </SegmentTemplate>
              </Representation>
            </AdaptationSet>
          </Period>
        </MPD>"""
        segments = _parse_dash_manifest(manifest)
        assert segments[0] == "https://cdn.example.com/audio/init.mp4"
        assert segments[1] == "https://cdn.example.com/audio/seg-1.m4s"



class TestGetAlbumTracks:
    def test_success(self, mocker):
        apis = ["https://api1.example.com"]
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

        album_title, tracks = get_album_tracks(apis, 42)
        assert album_title == "My Album"
        assert len(tracks) == 2
        assert tracks[0]["id"] == 1

    def test_raises_on_not_found(self, mocker):
        apis = ["https://api1.example.com"]
        mock_resp = mocker.Mock()
        mock_resp.ok = False
        mock_resp.status_code = 404
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        with pytest.raises(ValueError, match="Album not found"):
            get_album_tracks(apis, 999)

    def test_no_apis_raises(self):
        apis = []
        with pytest.raises(ConnectionError):
            get_album_tracks(apis, 42)

    def test_unwraps_item_wrapper(self, mocker):
        apis = ["https://api1.example.com"]
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
        _, tracks = get_album_tracks(apis, 1)
        assert tracks[0]["id"] == 5

    def test_pagination_loop_safeguard(self, mocker):
        """If the API ignores offset and returns page 1 again, stop paginating."""
        apis = ["https://api1.example.com"]
        page = {
            "data": {
                "title": "Album",
                "numberOfTracks": 10,
                "items": [{"id": 1, "title": "Track 1", "artist": {"name": "A"}, "trackNumber": 1}],
            }
        }
        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = page
        mocker.patch("spidal.hifi.requests.get", return_value=mock_resp)

        _, tracks = get_album_tracks(apis, 42)
        assert len(tracks) == 1


_JSON_MANIFEST = {"manifest": "eyJ1cmxzIjogWyJodHRwczovL2Nkbi5leGFtcGxlLmNvbS90cmFjay5mbGFjIl19"}
# base64 of: {"urls": ["https://cdn.example.com/track.flac"]}


class TestIterStreamUrls:
    def test_yields_url_per_endpoint_per_quality(self, mocker):
        apis = ["https://api1.example.com", "https://api2.example.com"]

        def mock_get(url, timeout=None):
            resp = mocker.Mock()
            resp.ok = True
            resp.json.return_value = {"data": _JSON_MANIFEST}
            return resp

        mocker.patch("spidal.hifi.requests.get", side_effect=mock_get)
        urls = list(iter_stream_urls(apis, 123))
        # 2 endpoints × 2 qualities (HI_RES_LOSSLESS, LOSSLESS) = 4 results
        assert len(urls) == 4
        assert all(u == "https://cdn.example.com/track.flac" for u in urls)

    def test_hi_res_lossless_tried_before_lossless(self, mocker):
        def mock_get(url, timeout=None):
            resp = mocker.Mock()
            resp.ok = True
            resp.json.return_value = {"data": _JSON_MANIFEST}
            return resp

        mock = mocker.patch("spidal.hifi.requests.get", side_effect=mock_get)
        list(iter_stream_urls(["https://api1.example.com"], 123))

        urls_called = [call[0][0] for call in mock.call_args_list]
        assert "quality=HI_RES_LOSSLESS" in urls_called[0]
        assert "quality=LOSSLESS" in urls_called[1]

    def test_skips_failed_endpoints(self, mocker):
        apis = ["https://api1.example.com", "https://api2.example.com"]

        def make_resp(ok):
            resp = mocker.Mock()
            resp.ok = ok
            resp.status_code = 200 if ok else 500
            resp.json.return_value = {"data": _JSON_MANIFEST}
            return resp

        # HI_RES pass: api1 fails, api2 ok; LOSSLESS pass: api1 fails, api2 ok
        mocker.patch(
            "spidal.hifi.requests.get",
            side_effect=[make_resp(False), make_resp(True), make_resp(False), make_resp(True)],
        )
        urls = list(iter_stream_urls(apis, 123))
        assert len(urls) == 2

    def test_no_apis_raises(self):
        with pytest.raises(ConnectionError):
            list(iter_stream_urls([], 123))
