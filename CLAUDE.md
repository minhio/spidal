# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install / sync dependencies
uv sync

# Run unit tests (integration tests excluded by default)
uv run pytest

# Run a single test file or test
uv run pytest tests/test_config.py
uv run pytest tests/test_config.py::TestGetApis::test_filters_unavailable_apis

# Run integration tests (makes real network requests)
uv run pytest -m integration

# Lint and format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Run the CLI
uv run spidal                    # launches TUI (default, no subcommand)
uv run spidal get <url>          # download track/album/playlist by URL
uv run spidal search "query"     # open search TUI with optional initial query
uv run spidal logs               # display last 50 log lines (color-coded)
uv run spidal config list        # show current configuration
uv run spidal config set <k> <v> # set a config value
uv run spidal where <loc>        # open config/logs/dl/db directory
```

## Architecture

Spidal is a FLAC downloader with a single `spidal` entrypoint:

- **`spidal`** → `src/spidal/cli.py` — Typer app; no subcommand launches the TUI, subcommands (`get`, `search`, `logs`, `config`, `where`) run CLI actions
- **`SpidalApp`** → `src/spidal/tui.py` — Textual app with tabbed layout: Spotify, Search, Library, Logs tabs
- **`SearchApp`/`SearchWidget`** → `src/spidal/commands/search.py` — search UI; `SearchWidget` is embedded in `SpidalApp`, `SearchApp` is a thin standalone wrapper for `spidal search`

The callback calls `setup_logging()` then `Config.load()` with CLI args as overrides. Config resolution priority: CLI args > config file (`$XDG_CONFIG_HOME/spidal/config.json`) > env vars (`SPIDAL_` prefix) > defaults. CLI args are persisted to the config file.

`Config.get_apis()` lazily fetches and health-checks API endpoints, caching the result. `Config.next_api()` round-robins through available endpoints via `itertools.cycle`.

`hifi_api` (single endpoint) and `hifi_api_file` (JSON list source, local or URL) are mutually exclusive.

### Download pipeline

`src/spidal/download.py` handles the full lifecycle of a single track:

1. `download_track()` — resolves dest path, checks for existing file (→ `"skipped"`), calls `iter_stream_urls()` to get candidate URLs, tries each with `_download_direct()` (single-file FLAC) or `_download_dash()` (DASH segments), validates size (>50KB), then calls `tag_flac()` and persists to db.
2. `download_tracks()` — iterates a list, calls `download_track()` for each, collects counts, fires `on_progress` callback, sleeps `download_delay` seconds between tracks (only when status is `"downloaded"`, not `"skipped"`).
3. Return values: `"downloaded"` (fresh download), `"skipped"` (file already exists), `"failed"` (error or size check). `download_tracks` maps `"skipped"` → `"downloaded"` for its counts.

### FLAC tagging

`src/spidal/tagging.py` enriches downloaded FLAC files with Vorbis Comment tags using the MusicBrainz API:

1. **Base tags** (from hifi data): `TITLE`, `ARTIST`, `ALBUM`, `TRACKNUMBER`, `ISRC`
2. **ISRC lookup** — `musicbrainzngs.get_recordings_by_isrc()` with `includes=["releases", "artists", "genres", "tags"]`: yields `MUSICBRAINZ_TRACKID`, `MUSICBRAINZ_ALBUMID`, `MUSICBRAINZ_ARTISTID`, `DATE`, `ALBUMARTIST`, `GENRE`
3. **Release detail lookup** — `musicbrainzngs.get_release_by_id()` with `includes=["recordings", "media"]`: yields `DISCNUMBER`, `DISCTOTAL`, `TRACKTOTAL`

Genre resolution: `genre-list` (curated, higher quality) preferred over `tag-list` (user tags); highest vote-count wins; title-cased on write.

Rate limiting: `musicbrainzngs.set_rate_limit(1.0)` enforces ~1 req/sec. Two MB calls per track add ~2s of natural delay, so `download-delay` defaults to `0`.

`tag_flac()` is always best-effort — all errors are logged and swallowed, never raised.

### TUI tab architecture

`SpidalApp` uses Textual `TabbedContent` with lazy mounting: `SearchWidget`, `LibraryWidget`, and `LogsWidget` are mounted on first tab visit (not at compose time) to prevent focus-stealing and ensure Spotify tab is active on startup. `SpotifyWidget` is composed eagerly.

Key pattern for tab activation in `SpidalApp.on_tabbed_content_tab_activated`: guard with `event.tabbed_content.id != "main-tabs"` and call `enable_focus()`/`focus_active_table()` on the newly activated widget.

`SearchWidget` has `can_focus_children = False` by default (prevents stealing focus when mounted); `enable_focus()` sets it to `True`. All DataTable mutations in worker threads must be called directly from the thread — never mix `call_from_thread` table ops with direct table ops (race condition).

### Persistence

`src/spidal/persistence.py` uses TinyDB at `~/.local/state/spidal/db.json` with tables:
- `"downloaded"` — tracks downloaded files keyed by ISRC; written on fresh downloads and skipped (already-exists) downloads; used by search UI for status display
- `"nomatch"` — Spotify tracks with no hifi match
- `"playlists"` — Spotify playlist download progress (`{playlist_id, downloaded, total}`)

## Testing

- Unit tests use `pytest-mock` (`MockerFixture`) — no `unittest.mock` or `monkeypatch`
- Env var mocking: `mocker.patch.dict(os.environ, {...})`
- Integration tests are marked with `@pytest.mark.integration`
- Network calls in unit tests must be mocked (`_is_available`, `requests.get`, `musicbrainzngs.*`)
- `download_track` returns `"skipped"` (not `"downloaded"`) when file already exists; `download_tracks` maps both to `"downloaded"` for counts and only sleeps between tracks when status is `"downloaded"` (raw), not `"skipped"`

### Lazy imports and mock paths

Several command functions use local imports inside the function body (to defer heavy imports). When patching these, target the **source module**, not the command module:

| What you're mocking | Correct patch path |
|---|---|
| `get_track_info`, `get_album_tracks`, `match_track` in `commands/get.py` | `spidal.hifi.<fn>` |
| `download_track`, `download_tracks` in `commands/get.py` | `spidal.download.<fn>` |
| `get_db`, `save_nomatch` in `commands/get.py` | `spidal.persistence.<fn>` |
| `load_config_file`, `save_config_file` in `commands/config.py` | `spidal.config.<fn>` |

### Typer exit exceptions

`typer.Exit` is `click.exceptions.Exit`, not `SystemExit`. Use `pytest.raises(click.exceptions.Exit)` when testing functions that call `raise typer.Exit(code=1)` directly (outside of `CliRunner`).

### FLAC test fixtures

To write a minimal valid FLAC file for tagging tests (so `mutagen.flac.FLAC()` can open it):

```python
def _make_flac(path) -> None:
    with open(path, "wb") as f:
        f.write(
            b"fLaC"
            + b"\x80\x00\x00\x22"                  # STREAMINFO: last=1, type=0, length=34
            + b"\x10\x00" + b"\x10\x00"             # min/max blocksize = 4096
            + b"\x00\x00\x00" + b"\x00\x00\x00"     # min/max framesize = 0
            + b"\x0A\xC4\x40\xF0\x00\x00\x00\x00"   # sr=44100, ch=1, bps=16, samples=0
            + b"\x00" * 16                           # MD5 (all zeros)
        )
```

Tests that call `download_track` and produce a real file path must also `mocker.patch("spidal.download.tag_flac")` to avoid mutagen failing on fake binary content.

## Conventions

- XDG paths for config: `~/.config/spidal/`, state/logs: `~/.local/state/spidal/`
- Module-level loggers: `logger = logging.getLogger(__name__)`
- Python 3.12+, managed with `uv`
- All tag field names follow MusicBrainz Picard Vorbis comment conventions: `TRACKTOTAL` (not `TOTALTRACKS`), `DISCTOTAL` (not `TOTALDISCS`)
