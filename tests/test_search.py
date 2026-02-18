import pytest

from spidal.commands.search import SearchApp, TrackActionScreen, _format_duration
from spidal.config import Config


def _config():
    config = Config()
    config._apis_cache = ["https://api.example.com"]
    return config


SAMPLE_TRACKS = [
    {
        "id": 100 + i,
        "title": f"Track {i}",
        "artist": {"name": f"Artist {i}"},
        "album": {"title": f"Album {i}"},
        "trackNumber": i,
        "isrc": f"ISRC{i:08d}",
        "duration": 180 + i,
    }
    for i in range(1, 6)
]


class TestFormatDuration:
    def test_basic(self):
        assert _format_duration(185) == "3:05"

    def test_zero(self):
        assert _format_duration(0) == "0:00"

    def test_none(self):
        assert _format_duration(None) == "-"

    def test_exact_minute(self):
        assert _format_duration(120) == "2:00"


class TestSearchAppMount:
    @pytest.mark.asyncio
    async def test_loads_first_page(self, mocker):
        mock_search = mocker.patch(
            "spidal.commands.search._search_page",
            return_value=(
                [
                    {
                        "id": 1,
                        "title": "Song",
                        "artist": "Art",
                        "album": "Alb",
                        "duration": 200,
                    }
                ],
                1,
            ),
        )
        mocker.patch(
            "spidal.commands.search._search_albums_page",
            return_value=([], 0),
        )

        async with SearchApp(_config(), "test query").run_test() as pilot:
            app = pilot.app
            await pilot.pause()
            assert len(app.tracks) == 1
            assert app.tracks[0]["title"] == "Song"
            table = app.query_one("#tracks-table")
            assert table.row_count == 1
            mock_search.assert_called_once_with(app.config, "test query")

    @pytest.mark.asyncio
    async def test_loads_albums(self, mocker):
        mocker.patch(
            "spidal.commands.search._search_page",
            return_value=([], 0),
        )
        mocker.patch(
            "spidal.commands.search._search_albums_page",
            return_value=(
                [
                    {
                        "id": 500,
                        "title": "Album",
                        "artist": "Art",
                        "numberOfTracks": 10,
                        "duration": 3000,
                    }
                ],
                1,
            ),
        )

        async with SearchApp(_config(), "test query").run_test() as pilot:
            app = pilot.app
            await pilot.pause()
            assert len(app.albums) == 1
            assert app.albums[0]["title"] == "Album"
            table = app.query_one("#albums-table")
            assert table.row_count == 1

    @pytest.mark.asyncio
    async def test_enter_shows_action_screen(self, mocker):
        mocker.patch(
            "spidal.commands.search._search_page",
            return_value=(
                [
                    {
                        "id": 42,
                        "title": "Song",
                        "artist": "Art",
                        "album": "Alb",
                        "duration": 100,
                    }
                ],
                1,
            ),
        )
        mocker.patch(
            "spidal.commands.search._search_albums_page",
            return_value=([], 0),
        )

        async with SearchApp(_config(), "q").run_test() as pilot:
            await pilot.pause()
            pilot.app.query_one("#tracks-table").focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(pilot.app.screen, TrackActionScreen)

    @pytest.mark.asyncio
    async def test_action_screen_open_url(self, mocker):
        mocker.patch(
            "spidal.commands.search._search_page",
            return_value=(
                [
                    {
                        "id": 42,
                        "title": "Song",
                        "artist": "Art",
                        "album": "Alb",
                        "duration": 100,
                    }
                ],
                1,
            ),
        )
        mocker.patch(
            "spidal.commands.search._search_albums_page",
            return_value=([], 0),
        )
        mock_open = mocker.patch("spidal.commands.search.webbrowser.open")

        async with SearchApp(_config(), "q").run_test() as pilot:
            await pilot.pause()
            pilot.app.query_one("#tracks-table").focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            # Navigate to "Open in Monochrome" (second option) and select
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
            mock_open.assert_called_once_with("https://monochrome.tf/track/42")

    @pytest.mark.asyncio
    async def test_action_screen_download(self, mocker):
        mocker.patch(
            "spidal.commands.search._search_page",
            return_value=(
                [
                    {
                        "id": 10,
                        "title": "Song",
                        "artist": "Art",
                        "album": "Alb",
                        "duration": 100,
                    }
                ],
                1,
            ),
        )
        mocker.patch(
            "spidal.commands.search._search_albums_page",
            return_value=([], 0),
        )
        mock_dl = mocker.patch(
            "spidal.commands.search.download_track",
            return_value=("downloaded", "/tmp/song.flac"),
        )

        async with SearchApp(_config(), "q").run_test() as pilot:
            await pilot.pause()
            pilot.app.query_one("#tracks-table").focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            # First option is download, select it
            await pilot.press("enter")
            await pilot.app.workers.wait_for_complete()
            mock_dl.assert_called_once()

    @pytest.mark.asyncio
    async def test_action_screen_escape(self, mocker):
        mocker.patch(
            "spidal.commands.search._search_page",
            return_value=(
                [
                    {
                        "id": 42,
                        "title": "Song",
                        "artist": "Art",
                        "album": "Alb",
                        "duration": 100,
                    }
                ],
                1,
            ),
        )
        mocker.patch(
            "spidal.commands.search._search_albums_page",
            return_value=([], 0),
        )

        async with SearchApp(_config(), "q").run_test() as pilot:
            await pilot.pause()
            pilot.app.query_one("#tracks-table").focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(pilot.app.screen, TrackActionScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(pilot.app.screen, TrackActionScreen)

    @pytest.mark.asyncio
    async def test_empty_results(self, mocker):
        mocker.patch(
            "spidal.commands.search._search_page",
            return_value=([], 0),
        )
        mocker.patch(
            "spidal.commands.search._search_albums_page",
            return_value=([], 0),
        )

        async with SearchApp(_config(), "nonexistent").run_test() as pilot:
            app = pilot.app
            await pilot.pause()
            assert len(app.tracks) == 0
            assert len(app.albums) == 0
            table = app.query_one("#tracks-table")
            assert table.row_count == 0
            albums_table = app.query_one("#albums-table")
            assert albums_table.row_count == 0
