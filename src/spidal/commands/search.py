from __future__ import annotations

import subprocess
import sys
import webbrowser
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

import logging

from spidal.core.config import Config
from spidal.core.download import _sanitize, download_track, download_tracks
from spidal.core.hifi import search_tracks, search_albums, get_album_tracks
from spidal.core.persistence import get_db, get_track

logger = logging.getLogger(__name__)


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


class TrackActionScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    TrackActionScreen {
        align: center middle;
    }
    TrackActionScreen > Vertical {
        width: 60;
        max-height: 12;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    TrackActionScreen > Vertical > Label {
        width: 1fr;
        text-align: center;
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }
    TrackActionScreen > Vertical > OptionList {
        height: auto;
        max-height: 6;
    }
    """

    def __init__(self, track: dict, file_path: str | None = None) -> None:
        super().__init__()
        self.track = track
        self.file_path = file_path

    def compose(self) -> ComposeResult:
        title = self.track.get("hifi_title") or "Unknown"
        artist = self.track.get("hifi_artist") or "Unknown"
        options = [
            Option("Download", id="download"),
            Option("Open in Monochrome", id="open_url"),
        ]
        if self.file_path:
            options.extend(
                [
                    Option("Open File", id="open_file"),
                    Option("Open File Location", id="open_file_location"),
                ]
            )
        with Vertical():
            yield Label(f"{artist} - {title}")
            yield OptionList(*options)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class AlbumActionScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    AlbumActionScreen {
        align: center middle;
    }
    AlbumActionScreen > Vertical {
        width: 60;
        max-height: 12;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    AlbumActionScreen > Vertical > Label {
        width: 1fr;
        text-align: center;
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }
    AlbumActionScreen > Vertical > OptionList {
        height: auto;
        max-height: 6;
    }
    """

    def __init__(self, album: dict, album_path: str | None = None) -> None:
        super().__init__()
        self.album = album
        self.album_path = album_path

    def compose(self) -> ComposeResult:
        title = self.album.get("title") or "Unknown"
        artist = self.album.get("artist") or "Unknown"
        options = [
            Option("Download", id="download"),
            Option("Open in Monochrome", id="open_url"),
        ]
        if self.album_path:
            options.append(Option("Open Album Location", id="open_album_location"))
        with Vertical():
            yield Label(f"{artist} - {title}")
            yield OptionList(*options)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    ConfirmScreen {
        align: center middle;
    }
    ConfirmScreen > Vertical {
        width: 60;
        max-height: 10;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    ConfirmScreen > Vertical > Label {
        width: 1fr;
        text-align: center;
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }
    ConfirmScreen > Vertical > OptionList {
        height: auto;
        max-height: 4;
    }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.message)
            yield OptionList(
                Option("Yes", id="yes"),
                Option("No", id="no"),
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id == "yes")

    def action_cancel(self) -> None:
        self.dismiss(False)


class NewSearchScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    NewSearchScreen {
        align: center middle;
    }
    NewSearchScreen > Vertical {
        width: 60;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    NewSearchScreen > Vertical > Label {
        width: 1fr;
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("New Search")
            yield Input(placeholder="Search query... (Esc to cancel)")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if query:
            self.dismiss(query)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SearchWidget(Vertical):
    """Reusable search widget that can be embedded in any Textual app."""

    BINDINGS = [
        Binding("d", "download_all", "Download All"),
        Binding("/", "new_search", "New Search"),
        Binding("t", "switch_tab('tracks')", "Tracks"),
        Binding("a", "switch_tab('albums')", "Albums"),
    ]

    DEFAULT_CSS = """
    SearchWidget {
        height: 1fr;
    }
    SearchWidget TabbedContent {
        height: 1fr;
    }
    SearchWidget TabPane {
        padding: 0;
    }
    SearchWidget DataTable {
        height: 1fr;
    }
    SearchWidget #status-bar {
        height: 1;
        dock: bottom;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    """

    def __init__(self, config: Config, query: str | None = None) -> None:
        super().__init__()
        self.config = config
        self.query = query
        self.tracks: list[dict] = []
        self.track_row_keys: dict[int, str] = {}
        self.albums: list[dict] = []
        self.album_row_keys: dict[int, str] = {}

    def compose(self) -> ComposeResult:
        with TabbedContent(id="search-tabs"):
            with TabPane("Tracks", id="tracks"):
                yield DataTable(
                    id="tracks-table", cursor_type="row", zebra_stripes=True
                )
            with TabPane("Albums", id="albums"):
                yield DataTable(
                    id="albums-table", cursor_type="row", zebra_stripes=True
                )
        yield Label("", id="status-bar")

    def enable_focus(self) -> None:
        """Allow children to receive focus (call when this widget's tab is activated)."""
        self.can_focus_children = True

    def focus_active_table(self) -> None:
        """Focus the DataTable in the currently active inner tab."""
        if self._active_tab_id() == "albums":
            self.query_one("#albums-table", DataTable).focus()
        else:
            self.query_one("#tracks-table", DataTable).focus()

    def on_mount(self) -> None:
        tracks_table = self.query_one("#tracks-table", DataTable)
        self._tracks_col_keys = tracks_table.add_columns(
            "#", "Title", "Artist", "Album", "Duration", "Downloaded"
        )

        albums_table = self.query_one("#albums-table", DataTable)
        self._albums_col_keys = albums_table.add_columns(
            "#", "Title", "Artist", "Tracks", "Duration", "Downloaded"
        )

        if self.query:
            self.app.sub_title = f"search: {self.query}"
            self._load_results()

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        """Focus the DataTable inside the newly activated tab."""
        if event.tabbed_content.id != "search-tabs":
            return
        event.stop()
        if event.pane.id == "albums":
            self.query_one("#albums-table", DataTable).focus()
        else:
            self.query_one("#tracks-table", DataTable).focus()

    @work(thread=True)
    def _load_results(self) -> None:
        # Fetch tracks
        tracks, _total = search_tracks(self.config.get_apis(), self.query)
        tracks_table = self.query_one("#tracks-table", DataTable)
        db = get_db()
        for track in tracks:
            idx = len(self.tracks)
            self.tracks.append(track)
            isrc = track.get("isrc")
            downloaded = "*" if isrc and get_track(db, isrc) else ""
            row_key = tracks_table.add_row(
                str(idx + 1),
                track.get("hifi_title") or "",
                track.get("hifi_artist") or "",
                track.get("hifi_album") or "",
                _format_duration(track.get("hifi_duration")),
                downloaded,
            )
            self.track_row_keys[idx] = row_key
        db.close()

        # Fetch albums
        albums, _total = search_albums(self.config.get_apis(), self.query)
        albums_table = self.query_one("#albums-table", DataTable)
        for album in albums:
            idx = len(self.albums)
            self.albums.append(album)
            row_key = albums_table.add_row(
                str(idx + 1),
                album.get("title") or "",
                album.get("artist") or "",
                str(album.get("numberOfTracks") or ""),
                _format_duration(album.get("duration")),
                self._album_dl_status(album),
            )
            self.album_row_keys[idx] = row_key

        status = self.query_one("#status-bar", Label)
        self.app.call_from_thread(
            status.update,
            f" {len(self.tracks)} tracks, {len(self.albums)} albums",
        )

    def _active_tab_id(self) -> str:
        tabs = self.query_one("#search-tabs", TabbedContent)
        return tabs.active or "tracks"

    def _selected_track(self) -> dict | None:
        table = self.query_one("#tracks-table", DataTable)
        idx = table.cursor_row
        if 0 <= idx < len(self.tracks):
            return self.tracks[idx]
        return None

    def _selected_album(self) -> dict | None:
        table = self.query_one("#albums-table", DataTable)
        idx = table.cursor_row
        if 0 <= idx < len(self.albums):
            return self.albums[idx]
        return None

    def _get_file_path(self, track: dict) -> str | None:
        """Return the file path if the track is downloaded, else None."""
        isrc = track.get("isrc")
        if not isrc:
            return None
        db = get_db()
        record = get_track(db, isrc)
        db.close()
        return record["file_path"] if record else None

    def _album_dir(self, album: dict) -> Path:
        """Return the expected album directory path."""
        artist = _sanitize(album.get("artist") or "Unknown")
        title = _sanitize(album.get("title") or "Unknown")
        return Path(self.config.download_dir or "downloads") / artist / title

    def _album_dl_status(self, album: dict) -> str:
        """Return download status string for an album."""
        album_dir = self._album_dir(album)
        if not album_dir.is_dir():
            return ""
        flac_count = len(list(album_dir.glob("*.flac")))
        if flac_count == 0:
            return ""
        total = album.get("numberOfTracks") or 0
        if total and flac_count >= total:
            return "*"
        return f"{flac_count}/{total}" if total else str(flac_count)

    def _get_album_path(self, album: dict) -> str | None:
        """Return the album directory if it exists on disk."""
        album_dir = self._album_dir(album)
        if album_dir.is_dir():
            return str(album_dir)
        return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if self._active_tab_id() == "albums":
            album = self._selected_album()
            if album:
                album_path = self._get_album_path(album)
                self.app.push_screen(
                    AlbumActionScreen(album, album_path),
                    callback=self._handle_album_action,
                )
        else:
            track = self._selected_track()
            if track:
                file_path = self._get_file_path(track)
                self.app.push_screen(
                    TrackActionScreen(track, file_path),
                    callback=self._handle_action,
                )

    def _handle_action(self, action: str | None) -> None:
        if action is None:
            return
        track = self._selected_track()
        if not track:
            return
        if action == "download":
            self._do_download(track)
        elif action == "open_url":
            webbrowser.open(f"https://monochrome.tf/track/{track['hifi_id']}")
        elif action in ("open_file", "open_file_location"):
            file_path = self._get_file_path(track)
            if not file_path:
                return
            if action == "open_file":
                self._open_path(file_path)
            else:
                self._open_path(str(Path(file_path).parent))

    def _handle_album_action(self, action: str | None) -> None:
        if action is None:
            return
        album = self._selected_album()
        if not album:
            return
        if action == "download":
            self._do_download_album(album)
        elif action == "open_url":
            webbrowser.open(f"https://monochrome.tf/album/{album['id']}")
        elif action == "open_album_location":
            album_path = self._get_album_path(album)
            if album_path:
                self._open_path(album_path)

    @staticmethod
    def _open_path(path: str) -> None:
        """Open a file or directory with the OS default handler."""
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def _mark_downloaded(self, track: dict) -> None:
        """Update the DL column for a track in the table."""
        idx = self.tracks.index(track)
        row_key = self.track_row_keys.get(idx)
        if row_key is not None:
            table = self.query_one("#tracks-table", DataTable)
            dl_col = self._tracks_col_keys[-1]
            table.update_cell(row_key, dl_col, "*")

    def _update_status(self, text: str) -> None:
        self.query_one("#status-bar", Label).update(text)

    def _show_progress(self, total: int, current: int) -> None:
        if total > 0:
            pct = current / total
            filled = int(pct * 30)
            text = f" [red][{'█' * filled}{'░' * (30 - filled)}] {current}/{total}[/red]"
        else:
            text = "[red] Downloading...[/red]"
        self._update_status(text)

    def _hide_progress(self) -> None:
        self._update_status("")

    @work(thread=True)
    def _do_download(self, track: dict) -> None:
        def _on_progress(current: int, total: int) -> None:
            logger.info("on_progress callback: %d/%d", current, total)
            self.app.call_from_thread(self._show_progress, total, current)

        logger.info("_do_download started, showing initial progress")
        self.app.call_from_thread(self._show_progress, 1, 0)
        artist = track.get("hifi_artist") or "Unknown"
        album = track.get("hifi_album") or "Unknown"
        status, path = download_track(self.config, track, artist, album, _on_progress)
        if status == "downloaded":
            self.app.call_from_thread(self._show_progress, 1, 1)
            self.app.call_from_thread(self.app.notify, f"Downloaded: {path}")
            self.app.call_from_thread(self._mark_downloaded, track)
        else:
            self.app.call_from_thread(self.app.notify, "Download failed", severity="error")
        self.app.call_from_thread(self._hide_progress)

    @work(thread=True)
    def _do_download_album(self, album: dict) -> None:
        album_id = album["id"]
        self.app.call_from_thread(self._update_status, " Fetching album tracks...")
        try:
            _album_title, tracks = get_album_tracks(self.config.get_apis(), album_id)
        except (ConnectionError, ValueError) as e:
            self.app.call_from_thread(self.app.notify, f"Failed: {e}", severity="error")
            self.app.call_from_thread(self._hide_progress)
            return

        def _on_progress(
            current: int, total: int, status: str, _path: str | None
        ) -> None:
            self.app.call_from_thread(self._show_progress, total, current)

        counts = download_tracks(self.config, tracks, _on_progress)
        self.app.call_from_thread(self._hide_progress)
        self.app.call_from_thread(self._mark_album_downloaded, album)
        msg = f" Done: {counts['downloaded']} downloaded, {counts['failed']} failed"
        self.app.call_from_thread(self._update_status, msg)
        self.app.call_from_thread(self.app.notify, msg.strip())

    def _mark_album_downloaded(self, album: dict) -> None:
        """Update the DL column for an album in the table."""
        idx = self.albums.index(album)
        row_key = self.album_row_keys.get(idx)
        if row_key is not None:
            table = self.query_one("#albums-table", DataTable)
            dl_col = self._albums_col_keys[-1]
            table.update_cell(row_key, dl_col, self._album_dl_status(album))

    def action_switch_tab(self, tab_id: str) -> None:
        tabs = self.query_one("#search-tabs", TabbedContent)
        tabs.active = tab_id

    def action_new_search(self) -> None:
        self.app.push_screen(NewSearchScreen(), callback=self._handle_new_search)

    def _handle_new_search(self, query: str | None) -> None:
        if not query:
            return
        self.query = query
        self.app.sub_title = f"search: {self.query}"
        self.tracks.clear()
        self.track_row_keys.clear()
        self.albums.clear()
        self.album_row_keys.clear()
        self.query_one("#tracks-table", DataTable).clear()
        self.query_one("#albums-table", DataTable).clear()
        self.query_one("#status-bar", Label).update("")
        self._load_results()

    def action_download_all(self) -> None:
        if self._active_tab_id() == "albums":
            if self.albums:
                total_tracks = sum(a.get("numberOfTracks") or 0 for a in self.albums)
                msg = (
                    f"Download all {len(self.albums)} albums"
                    f" (~{total_tracks} tracks)?"
                )
                self.app.push_screen(
                    ConfirmScreen(msg),
                    callback=self._handle_download_all_albums_confirm,
                )
        else:
            if self.tracks:
                msg = f"Download all {len(self.tracks)} tracks?"
                self.app.push_screen(
                    ConfirmScreen(msg),
                    callback=self._handle_download_all_tracks_confirm,
                )

    def _handle_download_all_tracks_confirm(self, confirmed: bool) -> None:
        if confirmed:
            self._do_download_all()

    def _handle_download_all_albums_confirm(self, confirmed: bool) -> None:
        if confirmed:
            self._do_download_all_albums()

    @work(thread=True, exclusive=True)
    def _do_download_all(self) -> None:
        tracks = list(self.tracks)

        def _on_progress(
            current: int, total: int, status: str, _path: str | None
        ) -> None:
            self.app.call_from_thread(self._show_progress, total, current)
            track = tracks[current - 1]
            if status == "downloaded":
                self.app.call_from_thread(self._mark_downloaded, track)

        counts = download_tracks(self.config, tracks, _on_progress)
        self.app.call_from_thread(self._hide_progress)
        msg = f" Done: {counts['downloaded']} downloaded, {counts['failed']} failed"
        self.app.call_from_thread(self._update_status, msg)
        self.app.call_from_thread(self.app.notify, msg.strip())

    @work(thread=True, exclusive=True)
    def _do_download_all_albums(self) -> None:
        albums = list(self.albums)
        total_downloaded = 0
        total_failed = 0
        for i, album in enumerate(albums, 1):
            self.app.call_from_thread(
                self._update_status,
                f" Album {i}/{len(albums)}: fetching tracks...",
            )
            try:
                _title, tracks = get_album_tracks(self.config.get_apis(), album["id"])
            except (ConnectionError, ValueError) as e:
                logger.warning("Failed to fetch album %s: %s", album["id"], e)
                total_failed += 1
                continue

            def _on_progress(
                current: int, total: int, status: str, _path: str | None
            ) -> None:
                self.app.call_from_thread(self._show_progress, total, current)

            counts = download_tracks(self.config, tracks, _on_progress)
            total_downloaded += counts["downloaded"]
            total_failed += counts["failed"]

        self.app.call_from_thread(self._hide_progress)
        msg = f" Done: {total_downloaded} downloaded, {total_failed} failed"
        self.app.call_from_thread(self._update_status, msg)
        self.app.call_from_thread(self.app.notify, msg.strip())


class SearchApp(App):
    TITLE = "spidal"
    theme = "catppuccin-mocha"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, config: Config, query: str | None = None) -> None:
        super().__init__()
        self.config = config
        self.query = query

    def compose(self) -> ComposeResult:
        yield Header()
        yield SearchWidget(self.config, self.query)
        yield Footer()

    def on_mount(self) -> None:
        self._search_widget.enable_focus()
        if not self.query:
            self._search_widget.action_new_search()

    @property
    def _search_widget(self) -> SearchWidget:
        return self.query_one(SearchWidget)

    @property
    def tracks(self) -> list[dict]:
        return self._search_widget.tracks

    @property
    def albums(self) -> list[dict]:
        return self._search_widget.albums
