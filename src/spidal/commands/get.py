import logging
import re
from collections.abc import Callable
from typing import Any

import typer

from spidal.commands import ensure_token, refresh_token
from spidal.core.config import Config

logger = logging.getLogger(__name__)

_MONOCHROME_TRACK_RE = re.compile(r"https?://monochrome\.tf/track/(\d+)")
_MONOCHROME_ALBUM_RE = re.compile(r"https?://monochrome\.tf/album/(\d+)")
_SPOTIFY_RE = re.compile(
    r"https?://open\.spotify\.com/(track|album|playlist)/([A-Za-z0-9]+)"
)


def _ensure_spotify_token(config: Config) -> None:
    ensure_token(config)


def _with_spotify_auth(config: Config, fn: Callable[..., Any], *args: Any) -> Any:
    """Call fn(config, *args), prompting for a new token on PermissionError."""
    _ensure_spotify_token(config)
    try:
        return fn(config, *args)
    except PermissionError:
        logger.warning("Spotify token expired, prompting for refresh")
        typer.echo("Spotify token expired. Please provide a new one.")
        refresh_token(config)
        return fn(config, *args)


def _get_spotify_track(config: Config, track_arg: str) -> dict:
    """Fetch Spotify track data, handling token refresh."""
    from spidal.core.spotify import get_track
    return _with_spotify_auth(config, get_track, track_arg)


def _download_monochrome_track(config: Config, track_id: int) -> None:
    """Download a single track by monochrome track ID."""
    from spidal.core.download import download_track
    from spidal.core.hifi import get_track_info

    info = get_track_info(config.get_apis(), track_id)
    if not info:
        typer.echo(f"Track not found: {track_id}")
        raise typer.Exit(code=1)

    artist = info.get("artist") or "Unknown"
    album = info.get("album") or "Unknown"
    typer.echo(f"Downloading: {artist} - {info.get('title')} (id={track_id})")

    status, path = download_track(config, info, artist, album)
    if status == "downloaded":
        typer.echo(f"Downloaded: {path}")
    else:
        typer.echo("Download failed.")
        raise typer.Exit(code=1)


def _download_monochrome_album(config: Config, album_id: int) -> None:
    """Download all tracks from a monochrome album."""
    from spidal.core.download import download_tracks
    from spidal.core.hifi import get_album_tracks

    typer.echo(f"Fetching album {album_id}...")
    album_title, tracks = get_album_tracks(config.get_apis(), album_id)
    if not tracks:
        typer.echo("No tracks found in album.")
        raise typer.Exit(code=1)

    typer.echo(f"Downloading album: {album_title} ({len(tracks)} tracks)")

    def on_progress(i: int, total: int, status: str, path: str | None) -> None:
        label = path or "failed"
        typer.echo(f"  [{i}/{total}] {status}: {label}")

    counts = download_tracks(config, tracks, on_progress=on_progress)
    typer.echo(f"Done: {counts['downloaded']} downloaded, {counts['failed']} failed")


def _download_spotify_track(config: Config, url: str) -> None:
    """Download a track by Spotify URL."""
    from spidal.core.download import download_track
    from spidal.core.hifi import match_track
    from spidal.core.persistence import get_db, save_track

    data = _get_spotify_track(config, url)

    title = data.get("name", "Unknown")
    artists = ", ".join(a["name"] for a in data.get("artists", []))
    album = data.get("album", {}).get("name", "Unknown")
    isrc = data.get("external_ids", {}).get("isrc")

    typer.echo(f"Searching: {artists} - {title} (ISRC: {isrc})")

    if not isrc:
        typer.echo("No ISRC found for this track.")
        raise typer.Exit(code=1)

    matched = match_track(config.get_apis(), f"{artists} {title}", isrc)
    if not matched:
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
        typer.echo("No matching track found on hifi API.")
        raise typer.Exit(code=1)

    typer.echo(
        f"Matched: {matched['title']} by {matched['artist']} (id={matched['id']})"
    )

    matched["spotify_id"] = data.get("id")
    matched["spotify_title"] = title
    matched["spotify_artist"] = artists
    matched["spotify_album"] = data.get("album", {}).get("name")
    matched["spotify_track_number"] = data.get("track_number")
    matched["spotify_duration"] = data.get("duration_ms")

    status, path = download_track(config, matched, artists, album)
    if status == "downloaded":
        typer.echo(f"Downloaded: {path}")
    else:
        typer.echo("Download failed.")
        raise typer.Exit(code=1)


def _match_spotify_tracks(config: Config, spotify_tracks: list[dict]) -> list[dict]:
    """Match Spotify tracks by ISRC, echoing results and saving unmatched to DB."""
    from spidal.core.matcher import match_tracks_by_isrc as _do_match
    from spidal.core.persistence import get_db, save_track

    matched, unmatched = _do_match(config.get_apis(), spotify_tracks)
    for st in unmatched:
        artists = st.get("spotify_artist", "")
        title = st.get("spotify_title", "Unknown")
        isrc = st.get("isrc")
        if not isrc:
            typer.echo(f"  Skipping (no ISRC): {artists} - {title}")
        else:
            typer.echo(f"  No match: {artists} - {title} (ISRC: {isrc})")
    if unmatched:
        db = get_db()
        for st in unmatched:
            save_track(db, st)
        db.close()
    return matched


def _download_spotify_album(config: Config, album_id: str) -> None:
    """Download all tracks from a Spotify album."""
    from spidal.core.download import download_tracks
    from spidal.core.spotify import get_album_tracks, get_tracks

    album_info, tracks = _with_spotify_auth(config, get_album_tracks, album_id)

    album_name = album_info.get("name", "Unknown")
    album_artists = ", ".join(a["name"] for a in album_info.get("artists", []))
    typer.echo(f"Album: {album_artists} - {album_name} ({len(tracks)} tracks)")

    # Album tracks endpoint returns simplified objects without external_ids (ISRC).
    # Fetch full track objects to get ISRCs for matching.
    track_ids = [t["id"] for t in tracks if t.get("id")]
    typer.echo("Fetching full track details...")
    full_tracks = get_tracks(config, track_ids)
    for t in full_tracks:
        t.setdefault("album", {})["name"] = album_name

    typer.echo("Matching tracks...")
    matched = _match_spotify_tracks(config, full_tracks)

    if not matched:
        typer.echo("No tracks could be matched.")
        raise typer.Exit(code=1)

    typer.echo(f"Matched {len(matched)}/{len(tracks)} tracks. Downloading...")

    def on_progress(i: int, total: int, status: str, path: str | None) -> None:
        label = path or "failed"
        typer.echo(f"  [{i}/{total}] {status}: {label}")

    counts = download_tracks(config, matched, on_progress=on_progress)
    typer.echo(f"Done: {counts['downloaded']} downloaded, {counts['failed']} failed")


def _download_spotify_playlist(config: Config, playlist_id: str) -> None:
    """Download all tracks from a Spotify playlist."""
    from spidal.core.download import download_tracks
    from spidal.core.spotify import get_playlist_tracks

    tracks = _with_spotify_auth(config, get_playlist_tracks, playlist_id)

    typer.echo(f"Playlist: {len(tracks)} tracks")
    typer.echo("Matching tracks...")
    matched = _match_spotify_tracks(config, tracks)

    if not matched:
        typer.echo("No tracks could be matched.")
        raise typer.Exit(code=1)

    typer.echo(f"Matched {len(matched)}/{len(tracks)} tracks. Downloading...")

    def on_progress(i: int, total: int, status: str, path: str | None) -> None:
        label = path or "failed"
        typer.echo(f"  [{i}/{total}] {status}: {label}")

    counts = download_tracks(config, matched, on_progress=on_progress)
    typer.echo(f"Done: {counts['downloaded']} downloaded, {counts['failed']} failed")


def _download_liked(config: Config) -> None:
    """Download all liked/saved tracks from Spotify."""
    from spidal.core.download import download_tracks
    from spidal.core.spotify import get_liked_tracks

    tracks = _with_spotify_auth(config, get_liked_tracks)

    typer.echo(f"Liked tracks: {len(tracks)}")
    typer.echo("Matching tracks...")
    matched = _match_spotify_tracks(config, tracks)

    if not matched:
        typer.echo("No tracks could be matched.")
        raise typer.Exit(code=1)

    typer.echo(f"Matched {len(matched)}/{len(tracks)} tracks. Downloading...")

    def on_progress(i: int, total: int, status: str, path: str | None) -> None:
        label = path or "failed"
        typer.echo(f"  [{i}/{total}] {status}: {label}")

    counts = download_tracks(config, matched, on_progress=on_progress)
    typer.echo(f"Done: {counts['downloaded']} downloaded, {counts['failed']} failed")


def get(
    ctx: typer.Context,
    url: str = typer.Argument(None, help="Spotify/Monochrome URL, or 'liked'"),
) -> None:
    """Download tracks, albums, playlists, or liked songs."""
    config: Config = ctx.obj

    if url is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()

    # Special case: liked songs
    if url == "liked":
        _download_liked(config)
        return

    # Monochrome track
    mono_track = _MONOCHROME_TRACK_RE.match(url)
    if mono_track:
        _download_monochrome_track(config, int(mono_track.group(1)))
        return

    # Monochrome album
    mono_album = _MONOCHROME_ALBUM_RE.match(url)
    if mono_album:
        _download_monochrome_album(config, int(mono_album.group(1)))
        return

    # Spotify URL
    spotify_match = _SPOTIFY_RE.match(url)
    if spotify_match:
        resource_type, resource_id = spotify_match.group(1), spotify_match.group(2)
        if resource_type == "track":
            _download_spotify_track(config, url)
        elif resource_type == "album":
            _download_spotify_album(config, resource_id)
        elif resource_type == "playlist":
            _download_spotify_playlist(config, resource_id)
        return

    typer.echo(
        "Unsupported URL. Provide a Spotify or Monochrome track/album/playlist URL, or 'liked'."
    )
    raise typer.Exit(code=1)
