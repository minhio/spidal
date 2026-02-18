from __future__ import annotations

import musicbrainzngs
import pytest
from mutagen.flac import FLAC

from spidal.tagging import tag_flac


def _make_flac(path) -> None:
    """Write a minimal valid FLAC file (STREAMINFO-only, no audio frames)."""
    with open(path, "wb") as f:
        f.write(
            b"fLaC"
            + b"\x80\x00\x00\x22"  # STREAMINFO block header: last=1, type=0, length=34
            + b"\x10\x00"          # min_blocksize = 4096
            + b"\x10\x00"          # max_blocksize = 4096
            + b"\x00\x00\x00"      # min_framesize = 0
            + b"\x00\x00\x00"      # max_framesize = 0
            # packed: sample_rate=44100 (20b) + channels-1=0 (3b) + bps-1=15 (5b) + total_samples=0 (36b)
            + b"\x0A\xC4\x40\xF0\x00\x00\x00\x00"
            + b"\x00" * 16         # MD5 (all zeros)
        )


def _mb_result(recording_id="rec-id", release_id="rel-id", date="2023-06-15",
               artist_id="art-id"):
    """Build a minimal musicbrainzngs ISRC response."""
    return {
        "isrc": {
            "recording-list": [
                {
                    "id": recording_id,
                    "title": "My Song",
                    "release-list": [
                        {
                            "id": release_id,
                            "title": "Test Album",
                            "date": date,
                            "artist-credit": [
                                {
                                    "artist": {"id": artist_id, "name": "Test Artist"},
                                    "joinphrase": "",
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }


def _recording_result(genres=None, tags=None):
    """Build a minimal musicbrainzngs get_recording_by_id response."""
    return {
        "recording": {
            "genre-list": genres or [],
            "tag-list": tags or [],
        }
    }


def _release_result(recording_id="rec-id", disc_number=1, disc_total=1, track_total=10):
    """Build a minimal musicbrainzngs release response with media."""
    return {
        "release": {
            "medium-list": [
                {
                    "position": str(disc_number),
                    "track-count": track_total,
                    "track-list": [
                        {"position": "3", "recording": {"id": recording_id}}
                    ],
                }
            ]
            + [{"position": str(i), "track-count": 5, "track-list": []} for i in range(2, disc_total + 1)]
        }
    }


class TestTagFlac:
    def test_writes_basic_tags(self, mocker, tmp_path):
        flac_path = tmp_path / "track.flac"
        _make_flac(str(flac_path))

        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recordings_by_isrc",
            return_value={"isrc": {"recording-list": []}},
        )

        track = {"id": 1, "title": "My Song", "track_number": 3, "isrc": "USRC17607839"}
        tag_flac(str(flac_path), track, "Test Artist", "Test Album")

        audio = FLAC(str(flac_path))
        assert audio["TITLE"] == ["My Song"]
        assert audio["ARTIST"] == ["Test Artist"]
        assert audio["ALBUM"] == ["Test Album"]
        assert audio["TRACKNUMBER"] == ["3"]
        assert audio["ISRC"] == ["USRC17607839"]

    def test_enriches_with_musicbrainz_data(self, mocker, tmp_path):
        flac_path = tmp_path / "track.flac"
        _make_flac(str(flac_path))

        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recordings_by_isrc",
            return_value=_mb_result(
                recording_id="recording-mbid-123",
                release_id="release-mbid-456",
                artist_id="artist-mbid-789",
            ),
        )
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recording_by_id",
            return_value=_recording_result(genres=[{"name": "rock", "count": "10"}]),
        )
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_release_by_id",
            return_value=_release_result(
                recording_id="recording-mbid-123",
                disc_number=1,
                disc_total=1,
                track_total=12,
            ),
        )

        track = {"id": 1, "title": "My Song", "track_number": 3, "isrc": "USRC17607839"}
        tag_flac(str(flac_path), track, "Test Artist", "Test Album")

        audio = FLAC(str(flac_path))
        assert audio["MUSICBRAINZ_TRACKID"] == ["recording-mbid-123"]
        assert audio["MUSICBRAINZ_ALBUMID"] == ["release-mbid-456"]
        assert audio["MUSICBRAINZ_ARTISTID"] == ["artist-mbid-789"]
        assert audio["DATE"] == ["2023-06-15"]
        assert audio["ALBUMARTIST"] == ["Test Artist"]
        assert audio["GENRE"] == ["Rock"]
        assert audio["DISCNUMBER"] == ["1"]
        assert audio["DISCTOTAL"] == ["1"]
        assert audio["TRACKTOTAL"] == ["12"]

    def test_genre_falls_back_to_tag_list(self, mocker, tmp_path):
        flac_path = tmp_path / "track.flac"
        _make_flac(str(flac_path))

        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recordings_by_isrc",
            return_value=_mb_result(),
        )
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recording_by_id",
            return_value=_recording_result(tags=[
                {"name": "pop", "count": "3"},
                {"name": "indie", "count": "8"},
            ]),
        )
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_release_by_id",
            return_value=_release_result(),
        )

        track = {"id": 1, "title": "Song", "track_number": 1, "isrc": "ABCD1234567"}
        tag_flac(str(flac_path), track, "Artist", "Album")

        audio = FLAC(str(flac_path))
        assert audio["GENRE"] == ["Indie"]  # highest count wins

    def test_skips_missing_file(self, mocker, tmp_path):
        mock_mb = mocker.patch("spidal.tagging.musicbrainzngs.get_recordings_by_isrc")
        track = {"id": 1, "title": "Song", "track_number": 1, "isrc": "USRC17607839"}
        tag_flac(str(tmp_path / "nonexistent.flac"), track, "Artist", "Album")
        mock_mb.assert_not_called()

    def test_handles_musicbrainz_error_gracefully(self, mocker, tmp_path):
        flac_path = tmp_path / "track.flac"
        _make_flac(str(flac_path))

        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recordings_by_isrc",
            side_effect=musicbrainzngs.WebServiceError("timeout"),
        )

        track = {"id": 1, "title": "Song", "track_number": 1, "isrc": "USRC17607839"}
        tag_flac(str(flac_path), track, "Artist", "Album")

        audio = FLAC(str(flac_path))
        assert audio["TITLE"] == ["Song"]
        assert "MUSICBRAINZ_TRACKID" not in audio

    def test_handles_release_lookup_error_gracefully(self, mocker, tmp_path):
        flac_path = tmp_path / "track.flac"
        _make_flac(str(flac_path))

        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recordings_by_isrc",
            return_value=_mb_result(),
        )
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recording_by_id",
            return_value=_recording_result(),
        )
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_release_by_id",
            side_effect=musicbrainzngs.WebServiceError("timeout"),
        )

        track = {"id": 1, "title": "Song", "track_number": 1, "isrc": "ABCD1234567"}
        tag_flac(str(flac_path), track, "Artist", "Album")

        # Basic MB tags still written; disc/track counts absent
        audio = FLAC(str(flac_path))
        assert audio["MUSICBRAINZ_TRACKID"] == ["rec-id"]
        assert "DISCNUMBER" not in audio
        assert "TRACKTOTAL" not in audio

    def test_skips_musicbrainz_when_no_isrc(self, mocker, tmp_path):
        flac_path = tmp_path / "track.flac"
        _make_flac(str(flac_path))

        mock_mb = mocker.patch("spidal.tagging.musicbrainzngs.get_recordings_by_isrc")

        track = {"id": 1, "title": "Song", "track_number": 1}
        tag_flac(str(flac_path), track, "Artist", "Album")

        mock_mb.assert_not_called()
        audio = FLAC(str(flac_path))
        assert audio["TITLE"] == ["Song"]

    def test_prefers_release_with_date(self, mocker, tmp_path):
        flac_path = tmp_path / "track.flac"
        _make_flac(str(flac_path))

        mb_result = {
            "isrc": {
                "recording-list": [
                    {
                        "id": "rec-id",
                        "release-list": [
                            {"id": "no-date-release", "artist-credit": []},
                            {"id": "dated-release", "date": "2021-01-01", "artist-credit": []},
                        ],
                    }
                ]
            }
        }
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recordings_by_isrc",
            return_value=mb_result,
        )
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recording_by_id",
            return_value=_recording_result(),
        )
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_release_by_id",
            return_value=_release_result(),
        )

        track = {"id": 1, "title": "Song", "track_number": 1, "isrc": "ABCD1234567"}
        tag_flac(str(flac_path), track, "Artist", "Album")

        audio = FLAC(str(flac_path))
        assert audio["MUSICBRAINZ_ALBUMID"] == ["dated-release"]
        assert audio["DATE"] == ["2021-01-01"]

    def test_uses_tracktotal_not_totaltracks(self, mocker, tmp_path):
        flac_path = tmp_path / "track.flac"
        _make_flac(str(flac_path))

        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recordings_by_isrc",
            return_value=_mb_result(),
        )
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recording_by_id",
            return_value=_recording_result(),
        )
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_release_by_id",
            return_value=_release_result(track_total=10),
        )

        track = {"id": 1, "title": "Song", "track_number": 1, "isrc": "ABCD1234567"}
        tag_flac(str(flac_path), track, "Artist", "Album")

        audio = FLAC(str(flac_path))
        assert "TRACKTOTAL" in audio
        assert "TOTALTRACKS" not in audio

    def test_missing_title_writes_no_title_tag(self, mocker, tmp_path):
        flac_path = tmp_path / "track.flac"
        _make_flac(str(flac_path))
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recordings_by_isrc",
            return_value={"isrc": {"recording-list": []}},
        )
        track = {"id": 1, "track_number": 1, "isrc": "ABCD1234567"}
        tag_flac(str(flac_path), track, "Artist", "Album")
        audio = FLAC(str(flac_path))
        assert "TITLE" not in audio
        assert audio["ARTIST"] == ["Artist"]

    def test_no_genre_when_lists_empty(self, mocker, tmp_path):
        flac_path = tmp_path / "track.flac"
        _make_flac(str(flac_path))
        mb_result = {
            "isrc": {
                "recording-list": [
                    {
                        "id": "rec-id",
                        "release-list": [{"id": "rel-id", "date": "2020", "artist-credit": []}],
                    }
                ]
            }
        }
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recordings_by_isrc",
            return_value=mb_result,
        )
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recording_by_id",
            return_value=_recording_result(),
        )
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_release_by_id",
            return_value=_release_result(),
        )
        track = {"id": 1, "title": "Song", "track_number": 1, "isrc": "ABCD1234567"}
        tag_flac(str(flac_path), track, "Artist", "Album")
        audio = FLAC(str(flac_path))
        assert "GENRE" not in audio

    def test_artist_credit_with_join_phrase(self, mocker, tmp_path):
        flac_path = tmp_path / "track.flac"
        _make_flac(str(flac_path))
        mb_result = {
            "isrc": {
                "recording-list": [
                    {
                        "id": "rec-id",
                        "release-list": [
                            {
                                "id": "rel-id",
                                "date": "2020",
                                "artist-credit": [
                                    {"artist": {"id": "a1", "name": "Artist A"}, "joinphrase": " & "},
                                    {"artist": {"id": "a2", "name": "Artist B"}, "joinphrase": ""},
                                ],
                            }
                        ],
                    }
                ]
            }
        }
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recordings_by_isrc",
            return_value=mb_result,
        )
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recording_by_id",
            return_value=_recording_result(),
        )
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_release_by_id",
            return_value=_release_result(),
        )
        track = {"id": 1, "title": "Song", "track_number": 1, "isrc": "ABCD1234567"}
        tag_flac(str(flac_path), track, "Artist A & Artist B", "Album")
        audio = FLAC(str(flac_path))
        assert audio["ALBUMARTIST"] == ["Artist A & Artist B"]

    def test_genre_title_cased(self, mocker, tmp_path):
        flac_path = tmp_path / "track.flac"
        _make_flac(str(flac_path))
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recordings_by_isrc",
            return_value=_mb_result(),
        )
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_recording_by_id",
            return_value=_recording_result(genres=[{"name": "classic rock", "count": "5"}]),
        )
        mocker.patch(
            "spidal.tagging.musicbrainzngs.get_release_by_id",
            return_value=_release_result(),
        )
        track = {"id": 1, "title": "Song", "track_number": 1, "isrc": "ABCD1234567"}
        tag_flac(str(flac_path), track, "Artist", "Album")
        audio = FLAC(str(flac_path))
        assert audio["GENRE"] == ["Classic Rock"]
