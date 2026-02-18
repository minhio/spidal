from spidal.config import Config
from spidal.download import _cleanup, _download_dash, _download_direct, _sanitize, download_track, download_tracks


class TestSanitize:
    def test_removes_unsafe_chars(self):
        assert _sanitize('Track: "Best" Song?') == "Track Best Song"

    def test_preserves_safe_chars(self):
        assert (
            _sanitize("Hello World 123 - (feat. Artist)")
            == "Hello World 123 - (feat. Artist)"
        )

    def test_removes_slashes(self):
        assert _sanitize("AC/DC\\Path") == "ACDCPath"


class TestDownloadTrack:
    def _config(self, tmp_path):
        config = Config()
        config._apis_cache = ["https://api1.example.com"]
        config.download_dir = str(tmp_path)
        return config

    def test_skips_existing_file(self, mocker, tmp_path):
        config = self._config(tmp_path)
        track = {"id": 1, "title": "Song", "track_number": 1}

        # Create the file so it exists
        dest = tmp_path / "Artist" / "Album" / "01 - Song.flac"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"existing")

        result = download_track(config, track, "Artist", "Album")
        assert result == ("skipped", str(dest))

    def test_direct_download_success(self, mocker, tmp_path):
        config = self._config(tmp_path)

        track = {"id": 42, "title": "Good Song", "track_number": 3}

        mocker.patch(
            "spidal.download.iter_stream_urls",
            return_value=iter(["https://cdn.example.com/audio.flac"]),
        )

        # Mock requests.get for the file download
        fake_content = b"x" * (60 * 1024)  # > 50KB
        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.headers = {"content-type": "audio/flac"}
        mock_resp.iter_content.return_value = [fake_content]
        mocker.patch("spidal.download.requests.get", return_value=mock_resp)
        mocker.patch("spidal.download.tag_flac")

        status, path = download_track(config, track, "Artist", "Album")
        assert status == "downloaded"
        expected = tmp_path / "Artist" / "Album" / "03 - Good Song.flac"
        assert path == str(expected)
        assert expected.exists()

    def test_fails_on_small_file(self, mocker, tmp_path):
        config = self._config(tmp_path)

        track = {"id": 42, "title": "Tiny", "track_number": 1}

        mocker.patch(
            "spidal.download.iter_stream_urls",
            return_value=iter(["https://cdn.example.com/audio.flac"]),
        )

        fake_content = b"x" * 100  # way under 50KB
        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.headers = {"content-type": "audio/flac"}
        mock_resp.iter_content.return_value = [fake_content]
        mocker.patch("spidal.download.requests.get", return_value=mock_resp)

        status, path = download_track(config, track, "Artist", "Album")
        assert status == "failed"
        assert path is None
        assert not (tmp_path / "Artist" / "Album" / "01 - Tiny.flac").exists()

    def test_fails_on_stream_url_error(self, mocker, tmp_path):
        config = self._config(tmp_path)

        track = {"id": 42, "title": "Song", "track_number": 1}

        mocker.patch(
            "spidal.download.iter_stream_urls",
            side_effect=ConnectionError("No hifi API endpoints available"),
        )

        status, path = download_track(config, track, "Artist", "Album")
        assert status == "failed"
        assert path is None

    def test_dash_download_success(self, mocker, tmp_path):
        config = self._config(tmp_path)

        track = {"id": 42, "title": "DASH Song", "track_number": 5}

        mocker.patch(
            "spidal.download.iter_stream_urls",
            return_value=iter(
                [
                    [
                        "https://cdn.example.com/init.mp4",
                        "https://cdn.example.com/seg-1.m4s",
                    ]
                ]
            ),
        )

        segment_data = b"x" * (30 * 1024)  # each segment 30KB, total > 50KB
        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.content = segment_data
        mocker.patch("spidal.download.requests.get", return_value=mock_resp)
        mocker.patch("spidal.download.tag_flac")

        status, path = download_track(config, track, "Artist", "Album")
        assert status == "downloaded"
        assert path is not None

    def test_cleans_up_on_http_error(self, mocker, tmp_path):
        config = self._config(tmp_path)

        track = {"id": 42, "title": "Fail", "track_number": 1}

        mocker.patch(
            "spidal.download.iter_stream_urls",
            return_value=iter(["https://cdn.example.com/audio.flac"]),
        )

        mock_resp = mocker.Mock()
        mock_resp.ok = False
        mock_resp.status_code = 500
        mock_resp.headers = {}
        mocker.patch("spidal.download.requests.get", return_value=mock_resp)

        status, path = download_track(config, track, "Artist", "Album")
        assert status == "failed"
        assert path is None
        # Directory should be cleaned up (empty dirs removed)
        assert not (tmp_path / "Artist" / "Album").exists()

    def test_sanitizes_filenames(self, mocker, tmp_path):
        config = self._config(tmp_path)

        track = {"id": 42, "title": 'What? "Yes": No', "track_number": 1}

        mocker.patch(
            "spidal.download.iter_stream_urls",
            return_value=iter(["https://cdn.example.com/audio.flac"]),
        )

        fake_content = b"x" * (60 * 1024)
        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.headers = {"content-type": "audio/flac"}
        mock_resp.iter_content.return_value = [fake_content]
        mocker.patch("spidal.download.requests.get", return_value=mock_resp)
        mocker.patch("spidal.download.tag_flac")

        status, path = download_track(config, track, "AC/DC", "Back*In:Black")
        assert status == "downloaded"
        expected = tmp_path / "ACDC" / "BackInBlack" / "01 - What Yes No.flac"
        assert path == str(expected)
        assert expected.exists()

    def test_falls_back_to_second_stream_url(self, mocker, tmp_path):
        config = self._config(tmp_path)
        track = {"id": 42, "title": "Song", "track_number": 1}

        # First URL fails (small file), second succeeds
        mocker.patch(
            "spidal.download.iter_stream_urls",
            return_value=iter([
                "https://cdn.example.com/bad.flac",
                "https://cdn.example.com/good.flac",
            ]),
        )

        small_content = b"x" * 100
        big_content = b"x" * (60 * 1024)

        responses = iter([small_content, big_content])

        def side_effect(url, stream=False, timeout=None):
            resp = mocker.Mock()
            resp.ok = True
            resp.headers = {"content-type": "audio/flac", "content-length": "0"}
            resp.iter_content.return_value = [next(responses)]
            return resp

        mocker.patch("spidal.download.requests.get", side_effect=side_effect)
        mocker.patch("spidal.download.tag_flac")

        status, path = download_track(config, track, "Artist", "Album")
        assert status == "downloaded"
        assert path is not None

    def test_on_progress_callback_called(self, mocker, tmp_path):
        config = self._config(tmp_path)
        track = {"id": 42, "title": "Song", "track_number": 1}

        mocker.patch(
            "spidal.download.iter_stream_urls",
            return_value=iter(["https://cdn.example.com/audio.flac"]),
        )

        chunk = b"x" * (60 * 1024)
        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.headers = {"content-type": "audio/flac", "content-length": str(len(chunk))}
        mock_resp.iter_content.return_value = [chunk]
        mocker.patch("spidal.download.requests.get", return_value=mock_resp)
        mocker.patch("spidal.download.tag_flac")

        calls = []
        download_track(config, track, "Artist", "Album", on_progress=lambda w, t: calls.append((w, t)))
        assert len(calls) == 1
        assert calls[0] == (len(chunk), len(chunk))


class TestCleanup:
    def test_removes_file_and_empty_dirs(self, tmp_path):
        parent = tmp_path / "Artist" / "Album"
        parent.mkdir(parents=True)
        f = parent / "track.flac"
        f.write_bytes(b"data")

        _cleanup(f)
        assert not f.exists()
        assert not parent.exists()
        assert not (tmp_path / "Artist").exists()

    def test_leaves_nonempty_dirs(self, tmp_path):
        parent = tmp_path / "Artist" / "Album"
        parent.mkdir(parents=True)
        f = parent / "track.flac"
        other = parent / "other.flac"
        f.write_bytes(b"data")
        other.write_bytes(b"other")

        _cleanup(f)
        assert not f.exists()
        assert parent.exists()  # not removed because other.flac is still there

    def test_tolerates_missing_file(self, tmp_path):
        # Should not raise
        _cleanup(tmp_path / "nonexistent.flac")


class TestDownloadDirect:
    def test_rejects_html_content_type(self, mocker, tmp_path):
        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.headers = {"content-type": "text/html"}
        mocker.patch("spidal.download.requests.get", return_value=mock_resp)
        result = _download_direct("https://example.com/track", tmp_path / "out.flac")
        assert result is False

    def test_no_content_length_still_downloads(self, mocker, tmp_path):
        chunk = b"x" * 1024
        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.headers = {"content-type": "audio/flac"}  # no content-length
        mock_resp.iter_content.return_value = [chunk]
        mocker.patch("spidal.download.requests.get", return_value=mock_resp)

        out = tmp_path / "out.flac"
        result = _download_direct("https://example.com/track", out)
        assert result is True
        assert out.read_bytes() == chunk

    def test_returns_false_on_http_error(self, mocker, tmp_path):
        mock_resp = mocker.Mock()
        mock_resp.ok = False
        mock_resp.status_code = 403
        mock_resp.headers = {}
        mocker.patch("spidal.download.requests.get", return_value=mock_resp)
        result = _download_direct("https://example.com/track", tmp_path / "out.flac")
        assert result is False


class TestDownloadDash:
    def test_returns_false_on_segment_http_error(self, mocker, tmp_path):
        mock_resp = mocker.Mock()
        mock_resp.ok = False
        mock_resp.status_code = 403
        mocker.patch("spidal.download.requests.get", return_value=mock_resp)
        result = _download_dash(["https://example.com/seg1"], tmp_path / "out.flac")
        assert result is False

    def test_returns_false_on_empty_segment(self, mocker, tmp_path):
        mock_resp = mocker.Mock()
        mock_resp.ok = True
        mock_resp.content = b""
        mocker.patch("spidal.download.requests.get", return_value=mock_resp)
        result = _download_dash(["https://example.com/seg1"], tmp_path / "out.flac")
        assert result is False

    def test_retries_on_request_exception(self, mocker, tmp_path):
        import requests as req
        good_resp = mocker.Mock()
        good_resp.ok = True
        good_resp.content = b"data"
        mocker.patch(
            "spidal.download.requests.get",
            side_effect=[req.RequestException("timeout"), good_resp],
        )
        mocker.patch("spidal.download.time.sleep")
        result = _download_dash(["https://example.com/seg1"], tmp_path / "out.flac")
        assert result is True


class TestDownloadTracks:
    def _config(self, tmp_path):
        config = Config()
        config._apis_cache = ["https://api1.example.com"]
        config.download_dir = str(tmp_path)
        config.download_delay = "0"
        return config

    def _make_track(self, **overrides):
        base = {"id": 1, "title": "Song", "track_number": 1, "artist": "Artist", "album": "Album"}
        base.update(overrides)
        return base

    def test_empty_list_returns_zero_counts(self, mocker, tmp_path):
        config = self._config(tmp_path)
        mocker.patch("spidal.download.tag_flac")
        counts = download_tracks(config, [])
        assert counts == {"downloaded": 0, "failed": 0}

    def test_counts_downloaded_and_failed(self, mocker, tmp_path):
        config = self._config(tmp_path)

        mocker.patch("spidal.download.tag_flac")

        def fake_download(cfg, track, artist, album, on_progress=None):
            if track["id"] == 1:
                return "downloaded", "/path/to/1.flac"
            return "failed", None

        mocker.patch("spidal.download.download_track", side_effect=fake_download)

        tracks = [self._make_track(id=1), self._make_track(id=2)]
        counts = download_tracks(config, tracks)
        assert counts["downloaded"] == 1
        assert counts["failed"] == 1

    def test_skipped_counts_as_downloaded(self, mocker, tmp_path):
        config = self._config(tmp_path)
        mocker.patch(
            "spidal.download.download_track",
            return_value=("skipped", "/path/to/file.flac"),
        )
        counts = download_tracks(config, [self._make_track()])
        assert counts["downloaded"] == 1
        assert counts.get("failed", 0) == 0

    def test_on_progress_called_for_each_track(self, mocker, tmp_path):
        config = self._config(tmp_path)
        mocker.patch(
            "spidal.download.download_track",
            return_value=("downloaded", "/path/to/file.flac"),
        )

        calls = []
        download_tracks(
            config,
            [self._make_track(id=1), self._make_track(id=2)],
            on_progress=lambda i, total, status, path: calls.append((i, total, status)),
        )
        assert calls == [(1, 2, "downloaded"), (2, 2, "downloaded")]

    def test_uses_unknown_for_missing_artist_album(self, mocker, tmp_path):
        config = self._config(tmp_path)
        captured = {}

        def fake_download(cfg, track, artist, album, on_progress=None):
            captured["artist"] = artist
            captured["album"] = album
            return "failed", None

        mocker.patch("spidal.download.download_track", side_effect=fake_download)
        download_tracks(config, [{"id": 1, "title": "Song", "track_number": 1}])
        assert captured["artist"] == "Unknown"
        assert captured["album"] == "Unknown"
