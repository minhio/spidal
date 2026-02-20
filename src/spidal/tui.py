from __future__ import annotations

import logging
import webbrowser

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    RichLog,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from spidal.commands.search import ConfirmScreen, SearchWidget
from spidal.core.config import LOG_DIR, Config
from spidal.core.persistence import (
    get_all_nomatch,
    get_db,
    get_downloaded_tracks,
    get_failed_tracks,
    get_playlist_tracks_db,
    is_track_downloaded,
    save_playlist_track,
    save_track,
)
from spidal.core.spotify import get_playlist_tracks, get_user_playlists

logger = logging.getLogger(__name__)


def _match_and_save_nomatch(config: Config, spotify_tracks: list[dict]) -> list[dict]:
    """Match Spotify tracks by ISRC and save unmatched records to the DB."""
    from spidal.core.matcher import match_tracks_by_isrc

    matched, unmatched = match_tracks_by_isrc(config.get_apis(), spotify_tracks)
    if unmatched:
        db = get_db()
        for st in unmatched:
            save_track(db, st)
        db.close()
    return matched

_SPOTIFY_CONSOLE_URL = "https://developer.spotify.com"


def _playlist_dl_status(downloaded: int, total: int) -> str:
    if not downloaded:
        return ""
    if total and downloaded >= total:
        return "*"
    return f"{downloaded}/{total}" if total else str(downloaded)


class PlaylistActionScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    PlaylistActionScreen {
        align: center middle;
    }
    PlaylistActionScreen > Vertical {
        width: 60;
        max-height: 12;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    PlaylistActionScreen > Vertical > Label {
        width: 1fr;
        text-align: center;
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }
    PlaylistActionScreen > Vertical > OptionList {
        height: auto;
        max-height: 6;
    }
    """

    def __init__(self, playlist: dict) -> None:
        super().__init__()
        self.playlist = playlist

    def compose(self) -> ComposeResult:
        name = self.playlist.get("name") or "Untitled"
        with Vertical():
            yield Label(name)
            yield OptionList(
                Option("Download All", id="download"),
                Option("Open in Browser", id="open_url"),
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class LibraryTrackActionScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    LibraryTrackActionScreen {
        align: center middle;
    }
    LibraryTrackActionScreen > Vertical {
        width: 60;
        max-height: 12;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    LibraryTrackActionScreen > Vertical > Label {
        width: 1fr;
        text-align: center;
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }
    LibraryTrackActionScreen > Vertical > OptionList {
        height: auto;
        max-height: 6;
    }
    """

    def __init__(self, label: str, options: list[Option]) -> None:
        super().__init__()
        self._label = label
        self._options = options

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._label)
            yield OptionList(*self._options)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SpotifyWidget(Vertical):
    """Spotify integration widget."""

    BINDINGS = [
        Binding("a", "show_auth", "Auth"),
        Binding("r", "reload_playlists", "Reload"),
        Binding("escape", "dismiss_auth", "Dismiss", show=False),
    ]

    DEFAULT_CSS = """
    SpotifyWidget {
        height: 1fr;
        align: center middle;
    }

    /* --- token setup --- */
    #token-setup {
        width: 60;
        height: auto;
        align: center middle;
    }
    #token-setup Label {
        width: 1fr;
        text-align: center;
        margin-bottom: 1;
    }
    #token-setup #token-heading {
        text-style: bold;
        color: $warning;
    }
    #token-setup Button {
        width: 1fr;
        margin-bottom: 1;
    }
    #token-setup Input {
        width: 1fr;
    }

    /* --- no-token idle --- */
    #no-token-idle {
        width: 60;
        height: auto;
        align: center middle;
    }
    #no-token-idle Label {
        width: 1fr;
        text-align: center;
        text-style: dim;
    }

    /* --- playlist view --- */
    #playlist-view {
        height: 1fr;
    }
    #playlist-view DataTable {
        height: 1fr;
    }
    #playlist-status {
        height: 1;
        dock: bottom;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    """

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.playlists: list[dict] = []
        self._playlist_row_keys: dict[int, str] = {}
        self._dl_col_key: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="token-setup"):
            yield Label("Spotify token required", id="token-heading")
            yield Label(
                "Get your access token from the Spotify Developer Console.\n"
                "Press the button below to open it in your browser."
            )
            yield Button("Open Spotify Developer Console", id="open-portal")
            yield Input(
                placeholder="Paste your token here and press Enter...",
                id="token-input",
            )
        with Vertical(id="no-token-idle"):
            yield Label("Press 'a' to set up Spotify authentication")
        with Vertical(id="playlist-view"):
            yield DataTable(id="playlists-table", cursor_type="row", zebra_stripes=True)
            yield Label("", id="playlist-status")

    def on_mount(self) -> None:
        table = self.query_one("#playlists-table", DataTable)
        *_, self._dl_col_key = table.add_columns("#", "Name", "Tracks", "Owner", "Downloaded")
        self._refresh_view()

    def _refresh_view(self) -> None:
        has_token = bool(self.config.spotify_token)
        self.query_one("#token-setup").display = not has_token
        self.query_one("#no-token-idle").display = False
        self.query_one("#playlist-view").display = has_token
        self.refresh(layout=True)
        if has_token:
            self._load_playlists()

    def _show_token_setup(self, clear_token: bool = False) -> None:
        """Show the token setup prompt. Only clears the token on auth failure."""
        if clear_token:
            self.config.spotify_token = None
        self.query_one("#token-setup").display = True
        self.query_one("#no-token-idle").display = False
        self.query_one("#playlist-view").display = False
        self.refresh(layout=True)
        self.query_one("#token-input", Input).clear()
        self.query_one("#token-input", Input).focus()

    def _update_status(self, text: str) -> None:
        self.query_one("#playlist-status", Label).update(text)

    def _set_status(self, text: str) -> None:
        self.app.call_from_thread(self._update_status, text)

    def _show_progress(self, total: int, current: int) -> None:
        if total > 0:
            pct = current / total
            filled = int(pct * 30)
            text = f" [red][{'█' * filled}{'░' * (30 - filled)}] {current}/{total}[/red]"
        else:
            text = "[red] Downloading...[/red]"
        self._update_status(text)

    def focus_active(self) -> None:
        """Focus the appropriate child based on current view state."""
        if self.query_one("#token-setup").display:
            self.query_one("#token-input", Input).focus()
        elif self.query_one("#playlist-view").display:
            self.query_one("#playlists-table", DataTable).focus()

    def action_show_auth(self) -> None:
        self._show_token_setup()

    def action_reload_playlists(self) -> None:
        if self.config.spotify_token:
            self._load_playlists()

    def action_dismiss_auth(self) -> None:
        if self.query_one("#token-setup").display:
            self.query_one("#token-setup").display = False
            if self.config.spotify_token:
                self.query_one("#playlist-view").display = True
                self.query_one("#playlists-table", DataTable).focus()
            else:
                self.query_one("#no-token-idle").display = True

    @work(thread=True)
    def _load_playlists(self) -> None:
        logger.info("Loading Spotify playlists")
        self._set_status(" Loading playlists...")
        try:
            playlists = get_user_playlists(self.config)
        except PermissionError:
            logger.warning("Spotify token invalid when loading playlists")
            self.app.call_from_thread(self._show_token_setup, True)
            return

        self.playlists = playlists
        self._playlist_row_keys.clear()
        table = self.query_one("#playlists-table", DataTable)
        table.clear()
        db = get_db()
        for i, pl in enumerate(playlists):
            name = pl.get("name") or "Untitled"
            total = pl.get("tracks", {}).get("total") or 0
            owner = pl.get("owner", {}).get("display_name") or ""
            pl_tracks = get_playlist_tracks_db(db, pl.get("id", ""))
            downloaded = sum(
                1 for t in pl_tracks if is_track_downloaded(db, t["spotify_id"])
            )
            dl_status = _playlist_dl_status(downloaded, total)
            row_key = table.add_row(str(i + 1), name, str(total) if total else "", owner, dl_status)
            self._playlist_row_keys[i] = row_key
        db.close()

        self._set_status(f" {len(playlists)} playlists")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.data_table.cursor_row
        if 0 <= idx < len(self.playlists):
            playlist = self.playlists[idx]
            self.app.push_screen(
                PlaylistActionScreen(playlist),
                callback=lambda action: self._handle_playlist_action(action, playlist),
            )

    def _handle_playlist_action(self, action: str | None, playlist: dict) -> None:
        if action == "open_url":
            url = playlist.get("external_urls", {}).get("spotify") or ""
            if url:
                webbrowser.open(url)
        elif action == "download":
            total = playlist.get("tracks", {}).get("total") or 0
            msg = f"Download all {total} tracks from '{playlist.get('name')}'?"
            self.app.push_screen(
                ConfirmScreen(msg),
                callback=lambda confirmed: self._do_download_playlist(playlist)
                if confirmed
                else None,
            )

    @work(thread=True)
    def _do_download_playlist(self, playlist: dict) -> None:
        from spidal.core.download import download_tracks

        playlist_id = playlist.get("id", "")
        playlist_name = playlist.get("name") or "Untitled"
        logger.info("Starting playlist download: %r (id=%s)", playlist_name, playlist_id)

        self._set_status(f" Fetching tracks for '{playlist_name}'...")
        try:
            spotify_tracks = get_playlist_tracks(self.config, playlist_id)
        except PermissionError:
            self.app.call_from_thread(self._show_token_setup, True)
            return

        self._set_status(f" Matching {len(spotify_tracks)} tracks...")
        matched = _match_and_save_nomatch(self.config, spotify_tracks)

        if not matched:
            self._set_status(" No tracks could be matched.")
            return

        self._set_status(f" Matched {len(matched)}/{len(spotify_tracks)}. Downloading...")

        # Save per-track playlist associations before downloading
        matched_by_spotify = {t["spotify_id"]: t.get("hifi_id") or t.get("id") for t in matched if t.get("spotify_id")}
        db = get_db()
        for st in spotify_tracks:
            sp_id = st.get("id")
            if sp_id:
                save_playlist_track(db, playlist_id, sp_id, matched_by_spotify.get(sp_id))
        db.close()

        def _on_progress(
            current: int, total: int, status: str, _path: str | None
        ) -> None:
            self.app.call_from_thread(self._show_progress, total, current)

        counts = download_tracks(self.config, matched, _on_progress)
        total = playlist.get("tracks", {}).get("total") or len(spotify_tracks)
        self.app.call_from_thread(
            self._mark_playlist_downloaded, playlist, counts["downloaded"], total
        )
        msg = f" Done: {counts['downloaded']} downloaded, {counts['failed']} failed"
        self._set_status(msg)
        self.app.call_from_thread(self.app.notify, msg.strip())

    def _mark_playlist_downloaded(
        self, playlist: dict, downloaded: int, total: int
    ) -> None:
        playlist_id = playlist.get("id", "")
        db = get_db()
        pl_tracks = get_playlist_tracks_db(db, playlist_id)
        downloaded = sum(1 for t in pl_tracks if is_track_downloaded(db, t["spotify_id"]))
        db.close()
        idx = self.playlists.index(playlist)
        row_key = self._playlist_row_keys.get(idx)
        if row_key is not None and self._dl_col_key is not None:
            table = self.query_one("#playlists-table", DataTable)
            table.update_cell(
                row_key, self._dl_col_key, _playlist_dl_status(downloaded, total)
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open-portal":
            webbrowser.open(_SPOTIFY_CONSOLE_URL)
            self.query_one("#token-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "token-input":
            token = event.value.strip()
            if token:
                self.config.set_spotify_token(token)
                self._refresh_view()


class LibraryWidget(Vertical):
    """Library widget showing downloaded tracks and failed matches."""

    BINDINGS = [
        Binding("r", "reload", "Reload"),
        Binding("d", "switch_tab('downloaded')", "Downloaded"),
        Binding("n", "switch_tab('nomatch')", "No Match"),
        Binding("f", "switch_tab('failed')", "Failed"),
    ]

    DEFAULT_CSS = """
    LibraryWidget {
        height: 1fr;
    }
    LibraryWidget TabbedContent {
        height: 1fr;
    }
    LibraryWidget TabPane {
        padding: 0;
    }
    LibraryWidget DataTable {
        height: 1fr;
    }
    LibraryWidget #library-status {
        height: 1;
        dock: bottom;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    """

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self._downloaded_tracks: list[dict] = []
        self._nomatch_tracks: list[dict] = []
        self._failed_tracks: list[dict] = []

    def compose(self) -> ComposeResult:
        with TabbedContent(id="library-tabs"):
            with TabPane("Downloaded", id="downloaded"):
                yield DataTable(
                    id="downloaded-table", cursor_type="row", zebra_stripes=True
                )
            with TabPane("No Match", id="nomatch"):
                yield DataTable(
                    id="nomatch-table", cursor_type="row", zebra_stripes=True
                )
            with TabPane("Failed", id="failed"):
                yield DataTable(
                    id="failed-table", cursor_type="row", zebra_stripes=True
                )
        yield Label("", id="library-status")

    def on_mount(self) -> None:
        dl_table = self.query_one("#downloaded-table", DataTable)
        dl_table.add_columns("#", "Title", "Artist", "Album", "File")

        nomatch_table = self.query_one("#nomatch-table", DataTable)
        nomatch_table.add_columns("#", "Title", "Artist", "Album", "ISRC")

        fail_table = self.query_one("#failed-table", DataTable)
        fail_table.add_columns("#", "Title", "Artist", "Album", "ISRC")

        self._load()

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        if event.tabbed_content.id != "library-tabs":
            return
        event.stop()
        if event.pane.id == "nomatch":
            self.query_one("#nomatch-table", DataTable).focus()
        elif event.pane.id == "failed":
            self.query_one("#failed-table", DataTable).focus()
        else:
            self.query_one("#downloaded-table", DataTable).focus()

    def focus_active_table(self) -> None:
        tabs = self.query_one("#library-tabs", TabbedContent)
        active = tabs.active or "downloaded"
        if active == "nomatch":
            self.query_one("#nomatch-table", DataTable).focus()
        elif active == "failed":
            self.query_one("#failed-table", DataTable).focus()
        else:
            self.query_one("#downloaded-table", DataTable).focus()

    def _update_status(self, text: str) -> None:
        self.query_one("#library-status", Label).update(text)

    def _set_status(self, text: str) -> None:
        self.app.call_from_thread(self._update_status, text)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.data_table.cursor_row
        if event.data_table.id == "downloaded-table":
            if 0 <= idx < len(self._downloaded_tracks):
                rec = self._downloaded_tracks[idx]
                label = f"{rec.get('hifi_artist') or ''} - {rec.get('hifi_title') or ''}"
                self.app.push_screen(
                    LibraryTrackActionScreen(label, [Option("Open File Location", id="open")]),
                    callback=lambda action, r=rec: self._handle_downloaded_action(action, r),
                )
        elif event.data_table.id == "failed-table":
            if 0 <= idx < len(self._failed_tracks):
                rec = self._failed_tracks[idx]
                label = f"{rec.get('hifi_artist') or ''} - {rec.get('hifi_title') or ''}"
                self.app.push_screen(
                    LibraryTrackActionScreen(label, [Option("Reprocess", id="reprocess")]),
                    callback=lambda action, r=rec: self._reprocess_failed(r) if action else None,
                )
        elif event.data_table.id == "nomatch-table":
            if 0 <= idx < len(self._nomatch_tracks):
                rec = self._nomatch_tracks[idx]
                label = f"{rec.get('spotify_artist') or ''} - {rec.get('spotify_title') or ''}"
                self.app.push_screen(
                    LibraryTrackActionScreen(label, [Option("Reprocess", id="reprocess")]),
                    callback=lambda action, r=rec: self._reprocess_nomatch(r) if action else None,
                )

    def _handle_downloaded_action(self, action: str | None, rec: dict) -> None:
        if action != "open":
            return
        file_path = rec.get("file_path")
        if not file_path:
            self._update_status(" No file path recorded for this track")
            return
        import subprocess
        import sys
        from pathlib import Path
        folder = Path(file_path).parent
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    @work(thread=True)
    def _reprocess_failed(self, track: dict) -> None:
        from spidal.core.download import download_track
        title = track.get("hifi_title") or "Unknown"
        artist = track.get("hifi_artist") or "Unknown"
        album = track.get("hifi_album") or "Unknown"
        logger.info("Reprocessing failed track: %s - %s", artist, title)
        self._set_status(f" Retrying: {artist} - {title}...")
        status, path = download_track(self.config, track, artist, album)
        if status in ("downloaded", "skipped"):
            self._set_status(f" Downloaded: {path}")
            self._load()
        else:
            self._set_status(f" Failed again: {artist} - {title}")

    @work(thread=True)
    def _reprocess_nomatch(self, record: dict) -> None:
        from spidal.core.download import download_track
        from spidal.core.hifi import match_track
        title = record.get("spotify_title") or "Unknown"
        artist = record.get("spotify_artist") or "Unknown"
        album = record.get("spotify_album") or ""
        isrc = record.get("isrc") or ""
        logger.info("Reprocessing nomatch: %s - %s (ISRC=%s)", artist, title, isrc)
        self._set_status(f" Matching: {artist} - {title}...")
        track = match_track(self.config.get_apis(), f"{artist} {title}", isrc)
        if not track:
            self._set_status(f" Still no match: {artist} - {title}")
            return
        track["isrc"] = record.get("isrc")
        track["spotify_id"] = record.get("spotify_id")
        track["spotify_title"] = record.get("spotify_title")
        track["spotify_artist"] = record.get("spotify_artist")
        track["spotify_album"] = record.get("spotify_album")
        track["spotify_track_number"] = record.get("spotify_track_number")
        track["spotify_duration"] = record.get("spotify_duration")
        self._set_status(f" Downloading: {artist} - {title}...")
        status, path = download_track(self.config, track, artist, album or "Unknown")
        if status in ("downloaded", "skipped"):
            self._set_status(f" Downloaded: {path}")
            self._load()
        else:
            self._set_status(f" Download failed: {artist} - {title}")

    @work(thread=True)
    def _load(self) -> None:
        logger.info("Loading library from database")
        self._set_status(" Loading library...")
        db = get_db()
        tracks = get_downloaded_tracks(db)
        nomatch = get_all_nomatch(db)
        failed = get_failed_tracks(db)
        db.close()
        logger.info(
            "Library loaded: %d downloaded, %d nomatch, %d failed",
            len(tracks), len(nomatch), len(failed),
        )
        self._downloaded_tracks = tracks
        self._nomatch_tracks = nomatch
        self._failed_tracks = failed
        self._populate_downloaded_table(tracks)
        self._populate_nomatch_table(nomatch)
        self._populate_failed_table(failed)
        self._set_status(
            f" {len(tracks)} downloaded, {len(nomatch)} unmatched, {len(failed)} failed"
        )

    def _populate_downloaded_table(self, tracks: list[dict]) -> None:
        table = self.query_one("#downloaded-table", DataTable)
        table.clear()
        for i, rec in enumerate(tracks):
            table.add_row(
                str(i + 1),
                rec.get("hifi_title") or "",
                rec.get("hifi_artist") or "",
                rec.get("hifi_album") or "",
                rec.get("file_path") or "",
            )

    def _populate_nomatch_table(self, records: list[dict]) -> None:
        table = self.query_one("#nomatch-table", DataTable)
        table.clear()
        for i, rec in enumerate(records):
            table.add_row(
                str(i + 1),
                rec.get("spotify_title") or "",
                rec.get("spotify_artist") or "",
                rec.get("spotify_album") or "",
                rec.get("isrc") or "",
            )

    def _populate_failed_table(self, tracks: list[dict]) -> None:
        table = self.query_one("#failed-table", DataTable)
        table.clear()
        for i, rec in enumerate(tracks):
            table.add_row(
                str(i + 1),
                rec.get("hifi_title") or "",
                rec.get("hifi_artist") or "",
                rec.get("hifi_album") or "",
                rec.get("isrc") or "",
            )

    def action_reload(self) -> None:
        self._load()

    def action_switch_tab(self, tab_id: str) -> None:
        self.query_one("#library-tabs", TabbedContent).active = tab_id


class LogsWidget(Vertical):
    """Displays the spidal log file."""

    BINDINGS = [
        Binding("r", "reload", "Reload"),
        Binding("end", "scroll_end", "Bottom", show=False),
        Binding("home", "scroll_start", "Top", show=False),
    ]

    DEFAULT_CSS = """
    LogsWidget {
        height: 1fr;
    }
    LogsWidget RichLog {
        height: 1fr;
    }
    LogsWidget #log-status {
        height: 1;
        dock: bottom;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield RichLog(id="log-view", highlight=True, markup=False, wrap=True)
        yield Label("", id="log-status")

    def on_mount(self) -> None:
        self._load()

    def _load(self) -> None:
        log_view = self.query_one("#log-view", RichLog)
        log_view.clear()
        log_path = LOG_DIR / "spidal.log"
        if not log_path.exists():
            log_view.write("No log file found.")
            self.query_one("#log-status", Label).update(" No logs yet")
            return
        lines = log_path.read_text(errors="replace").splitlines()
        for line in lines:
            log_view.write(line)
        log_view.scroll_end(animate=False)
        self.query_one("#log-status", Label).update(f" {len(lines)} lines")

    def action_reload(self) -> None:
        self._load()

    def action_scroll_end(self) -> None:
        self.query_one("#log-view", RichLog).scroll_end(animate=False)

    def action_scroll_start(self) -> None:
        self.query_one("#log-view", RichLog).scroll_home(animate=False)


class GetWidget(Vertical):
    """Bulk URL download — paste up to 25 Monochrome or Spotify URLs and download them all."""

    NUM_INPUTS = 25

    BINDINGS = [
        Binding("ctrl+d", "download_all", "Download All"),
        Binding("escape", "unfocus_input", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    GetWidget {
        height: 1fr;
    }
    GetWidget VerticalScroll {
        height: 1fr;
    }
    GetWidget .url-input {
        width: 80;
        margin: 0 1;
    }
    GetWidget Button {
        width: 1fr;
        margin: 1 2;
    }
    GetWidget #get-status {
        height: 1;
        dock: bottom;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    """

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            for i in range(self.NUM_INPUTS):
                yield Input(
                    placeholder="Monochrome or Spotify URL...",
                    id=f"url-{i}",
                    classes="url-input",
                )
        yield Button("Download All", id="download-all-btn", variant="primary")
        yield Label("", id="get-status")

    def focus_first_input(self) -> None:
        self.query_one("#url-0", Input).focus()

    def _clear_inputs(self) -> None:
        for i in range(self.NUM_INPUTS):
            self.query_one(f"#url-{i}", Input).clear()

    def action_unfocus_input(self) -> None:
        if isinstance(self.app.focused, Input):
            self.query_one("#download-all-btn", Button).focus()

    def _update_status(self, text: str) -> None:
        self.query_one("#get-status", Label).update(text)

    def _set_status(self, text: str) -> None:
        self.app.call_from_thread(self._update_status, text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "download-all-btn":
            self.action_download_all()

    def action_download_all(self) -> None:
        urls = [
            self.query_one(f"#url-{i}", Input).value.strip()
            for i in range(self.NUM_INPUTS)
        ]
        urls = [u for u in urls if u]
        if not urls:
            self._update_status(" No URLs entered")
            return
        self._do_download_all(urls)

    @work(thread=True)
    def _do_download_all(self, urls: list[str]) -> None:
        from spidal.commands.get import (
            _MONOCHROME_ALBUM_RE,
            _MONOCHROME_TRACK_RE,
            _SPOTIFY_RE,
        )

        total = len(urls)
        downloaded = 0
        failed = 0

        for i, url in enumerate(urls):
            self._set_status(f" [{i + 1}/{total}] {url[:70]}")
            try:
                m = _MONOCHROME_TRACK_RE.match(url)
                if m:
                    d, f = self._handle_monochrome_track(int(m.group(1)))
                    downloaded += d
                    failed += f
                    continue

                m = _MONOCHROME_ALBUM_RE.match(url)
                if m:
                    d, f = self._handle_monochrome_album(int(m.group(1)))
                    downloaded += d
                    failed += f
                    continue

                m = _SPOTIFY_RE.match(url)
                if m:
                    if not self.config.spotify_token:
                        self._set_status(" Spotify token not set — skipping Spotify URLs")
                        failed += 1
                        continue
                    d, f = self._handle_spotify_url(url, m.group(1), m.group(2))
                    downloaded += d
                    failed += f
                    continue

                logger.warning("Unrecognized URL: %s", url)
                failed += 1

            except Exception as e:
                logger.error("Error processing %s: %s", url, e)
                failed += 1

        self._set_status(f" Done: {downloaded} downloaded, {failed} failed")
        self.app.call_from_thread(self._clear_inputs)

    def _handle_monochrome_track(self, track_id: int) -> tuple[int, int]:
        from spidal.core.download import download_track
        from spidal.core.hifi import get_track_info

        info = get_track_info(self.config.get_apis(), track_id)
        if not info:
            return 0, 1
        status, _ = download_track(
            self.config,
            info,
            info.get("artist") or "Unknown",
            info.get("album") or "Unknown",
        )
        return (1, 0) if status in ("downloaded", "skipped") else (0, 1)

    def _handle_monochrome_album(self, album_id: int) -> tuple[int, int]:
        from spidal.core.download import download_tracks
        from spidal.core.hifi import get_album_tracks

        _, tracks = get_album_tracks(self.config.get_apis(), album_id)
        counts = download_tracks(self.config, tracks)
        return counts["downloaded"], counts["failed"]

    def _handle_spotify_url(
        self, url: str, resource_type: str, resource_id: str
    ) -> tuple[int, int]:
        from spidal.core.download import download_track, download_tracks

        if resource_type == "track":
            from spidal.core.hifi import match_track
            from spidal.core.spotify import get_track

            data = get_track(self.config, url)
            title = data.get("name", "Unknown")
            artists = ", ".join(a["name"] for a in data.get("artists", []))
            isrc = data.get("external_ids", {}).get("isrc")
            if not isrc:
                return 0, 1
            track = match_track(self.config.get_apis(), f"{artists} {title}", isrc)
            if not track:
                db = get_db()
                save_track(db, {
                    "isrc": isrc,
                    "spotify_id": data.get("id"),
                    "spotify_title": title,
                    "spotify_artist": artists,
                    "spotify_album": data.get("album", {}).get("name"),
                    "spotify_track_number": data.get("track_number"),
                    "spotify_duration": data.get("duration_ms"),
                })
                db.close()
                return 0, 1
            album = data.get("album", {}).get("name", "Unknown")
            track["spotify_id"] = data.get("id")
            track["spotify_title"] = title
            track["spotify_artist"] = artists
            track["spotify_album"] = data.get("album", {}).get("name")
            track["spotify_track_number"] = data.get("track_number")
            track["spotify_duration"] = data.get("duration_ms")
            status, _ = download_track(self.config, track, artists, album)
            return (1, 0) if status in ("downloaded", "skipped") else (0, 1)

        if resource_type == "album":
            from spidal.core.spotify import get_album_tracks as sp_get_album_tracks, get_tracks

            album_info, tracks = sp_get_album_tracks(self.config, resource_id)
            album_name = album_info.get("name", "Unknown")
            track_ids = [t["id"] for t in tracks if t.get("id")]
            full_tracks = get_tracks(self.config, track_ids)
            for t in full_tracks:
                t.setdefault("album", {})["name"] = album_name
            matched = _match_and_save_nomatch(self.config, full_tracks)
            counts = download_tracks(self.config, matched)
            return counts["downloaded"], counts["failed"]

        if resource_type == "playlist":
            from spidal.core.spotify import get_playlist_tracks

            tracks = get_playlist_tracks(self.config, resource_id)
            matched = _match_and_save_nomatch(self.config, tracks)
            counts = download_tracks(self.config, matched)
            return counts["downloaded"], counts["failed"]

        return 0, 1


class SpidalApp(App):
    """Spidal TUI application."""

    TITLE = "spidal"
    theme = "catppuccin-mocha"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "switch_tab('search')", "Search"),
        Binding("e", "switch_tab('get')", "Get"),
        Binding("p", "switch_tab('spotify')", "Spotify"),
        Binding("l", "switch_tab('library')", "Library"),
        Binding("g", "switch_tab('logs')", "Logs"),
    ]

    def __init__(self, config: Config | None = None) -> None:
        super().__init__()
        self.config = config or Config.load()
        self._get_mounted = False
        self._spotify_mounted = False
        self._library_mounted = False
        self._logs_mounted = False

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="main-tabs"):
            with TabPane("Search", id="search"):
                yield SearchWidget(self.config)
            yield TabPane("Get", id="get")
            yield TabPane("Spotify", id="spotify")
            yield TabPane("Library", id="library")
            yield TabPane("Logs", id="logs")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(SearchWidget).focus_active_table()

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        if event.tabbed_content.id != "main-tabs":
            return
        if event.pane.id == "get":
            self.sub_title = "Get"
            if not self._get_mounted:
                self._get_mounted = True
                widget = GetWidget(self.config)
                event.pane.mount(widget)
            else:
                widget = self.query_one(GetWidget)
            widget.focus_first_input()
        elif event.pane.id == "spotify":
            self.sub_title = "Spotify Playlists"
            if not self._spotify_mounted:
                self._spotify_mounted = True
                widget = SpotifyWidget(self.config)
                event.pane.mount(widget)
            else:
                widget = self.query_one(SpotifyWidget)
            self.call_after_refresh(widget.focus_active)
        elif event.pane.id == "search":
            widget = self.query_one(SearchWidget)
            self.sub_title = f"search: {widget.query}" if widget.query else ""
            widget.focus_active_table()
        elif event.pane.id == "library":
            self.sub_title = "Library"
            if not self._library_mounted:
                self._library_mounted = True
                widget = LibraryWidget(self.config)
                event.pane.mount(widget)
            else:
                widget = self.query_one(LibraryWidget)
            widget.focus_active_table()
        elif event.pane.id == "logs":
            self.sub_title = "Logs"
            if not self._logs_mounted:
                self._logs_mounted = True
                event.pane.mount(LogsWidget())
            else:
                self.query_one(LogsWidget).query_one("#log-view", RichLog).focus()

    def action_switch_tab(self, tab_id: str) -> None:
        tabs = self.query_one("#main-tabs", TabbedContent)
        tabs.active = tab_id
