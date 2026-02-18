from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import requests

from spidal.config import Config

logger = logging.getLogger(__name__)

_BASE62_RE = re.compile(r"^[0-9A-Za-z]{22}$")


_SPOTIFY_RESOURCE_TYPES = {"track", "album", "playlist"}


def parse_spotify_url(url: str) -> tuple[str, str]:
    """Parse a Spotify URL into (resource_type, id).

    Supports track, album, and playlist URLs.

    Returns:
        Tuple of (resource_type, spotify_id).

    Raises:
        ValueError: If the URL is not a valid Spotify resource URL.
    """
    parsed = urlparse(url)
    if parsed.hostname != "open.spotify.com":
        raise ValueError(f"Not a Spotify URL: {url}")
    parts = parsed.path.rstrip("/").split("/")
    if len(parts) < 3 or parts[-2] not in _SPOTIFY_RESOURCE_TYPES:
        raise ValueError(f"Unsupported Spotify URL: {url}")
    return parts[-2], parts[-1]


def _validate_track_id(track_id: str) -> str:
    if not _BASE62_RE.match(track_id):
        logger.error("Invalid Spotify track ID: %s", track_id)
        raise ValueError(f"Invalid Spotify track ID: {track_id}")
    return track_id


def parse_track_id(track: str) -> str:
    parsed = urlparse(track)
    if parsed.scheme in ("http", "https"):
        if parsed.hostname != "open.spotify.com":
            logger.error("Invalid Spotify URL host: %s", parsed.hostname)
            raise ValueError(f"Not a Spotify URL: {track}")
        parts = parsed.path.rstrip("/").split("/")
        if len(parts) < 3 or parts[-2] != "track":
            logger.error("URL is not a Spotify track link: %s", track)
            raise ValueError(f"Not a Spotify track URL: {track}")
        return _validate_track_id(parts[-1])
    return _validate_track_id(track)


def _check_response(resp: requests.Response) -> None:
    if resp.status_code == 401:
        detail = ""
        try:
            detail = resp.json()["error"]["message"]
        except (KeyError, ValueError):
            pass
        msg = "Bad or expired Spotify token" + (f" ({detail})" if detail else "")
        logger.error(msg)
        raise PermissionError(msg)
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After")
        msg = "Spotify rate limit exceeded"
        if retry_after:
            msg += f", retry after {retry_after}s"
        logger.error(msg)
        raise ConnectionError(msg)
    resp.raise_for_status()


def get_track(config: Config, track: str) -> dict:
    track_id = parse_track_id(track)
    if not config.spotify_token:
        raise PermissionError("No Spotify token configured")
    token = config.spotify_token

    resp = requests.get(
        f"{config.spotify_api_url}/tracks/{track_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code in (400, 404):
        detail = ""
        try:
            detail = resp.json()["error"]["message"]
        except (KeyError, ValueError):
            pass
        msg = f"Track not found: {track_id}" + (f" ({detail})" if detail else "")
        logger.error(msg)
        raise LookupError(msg)
    _check_response(resp)
    return resp.json()


def _auth_headers(config: Config) -> dict[str, str]:
    if not config.spotify_token:
        raise PermissionError("No Spotify token configured")
    return {"Authorization": f"Bearer {config.spotify_token}"}


def _paginate(config: Config, url: str) -> list[dict]:
    """Follow Spotify pagination, collecting all items."""
    headers = _auth_headers(config)
    items: list[dict] = []
    page = 0
    while url:
        page += 1
        logger.debug("Fetching Spotify page %d: %s", page, url[:80])
        resp = requests.get(url, headers=headers)
        _check_response(resp)
        data = resp.json()
        items.extend(data.get("items", []))
        url = data.get("next")
    logger.debug("Pagination complete: %d items across %d page(s)", len(items), page)
    return items


def get_user_playlists(config: Config) -> list[dict]:
    """Fetch all playlists owned or followed by the current user."""
    logger.info("Fetching user playlists")
    url = f"{config.spotify_api_url}/me/playlists?limit=50"
    playlists = _paginate(config, url)
    logger.info("Fetched %d playlists", len(playlists))
    return playlists


def get_album(config: Config, album_id: str) -> dict:
    """Fetch album metadata from Spotify."""
    logger.info("Fetching Spotify album: %s", album_id)
    resp = requests.get(
        f"{config.spotify_api_url}/albums/{album_id}",
        headers=_auth_headers(config),
    )
    _check_response(resp)
    data = resp.json()
    logger.debug("Album: %r by %s", data.get("name"), ", ".join(a["name"] for a in data.get("artists", [])))
    return data


def get_album_tracks(config: Config, album_id: str) -> tuple[dict, list[dict]]:
    """Fetch album metadata and all tracks.

    Returns:
        Tuple of (album_info, list of track dicts).
    """
    album = get_album(config, album_id)
    url = f"{config.spotify_api_url}/albums/{album_id}/tracks?limit=50"
    tracks = _paginate(config, url)
    return album, tracks


def get_tracks(config: Config, track_ids: list[str]) -> list[dict]:
    """Fetch full track objects from Spotify in batches of 50.

    Returns:
        List of full track dicts (with external_ids/ISRC).
    """
    logger.info("Fetching %d Spotify track(s) in batches", len(track_ids))
    headers = _auth_headers(config)
    results: list[dict] = []
    for i in range(0, len(track_ids), 50):
        batch = track_ids[i : i + 50]
        logger.debug("Fetching track batch %d-%d", i + 1, i + len(batch))
        resp = requests.get(
            f"{config.spotify_api_url}/tracks",
            headers=headers,
            params={"ids": ",".join(batch)},
        )
        _check_response(resp)
        results.extend(t for t in resp.json().get("tracks", []) if t)
    logger.info("Fetched %d full track objects", len(results))
    return results


def get_playlist_tracks(config: Config, playlist_id: str) -> list[dict]:
    """Fetch all tracks from a Spotify playlist.

    Returns:
        List of track dicts (unwrapped from items[].track).
    """
    logger.info("Fetching tracks for playlist: %s", playlist_id)
    url = f"{config.spotify_api_url}/playlists/{playlist_id}/tracks?limit=100"
    items = _paginate(config, url)
    tracks = [item["track"] for item in items if item.get("track")]
    logger.info("Playlist %s: %d track(s)", playlist_id, len(tracks))
    return tracks


def get_liked_tracks(config: Config) -> list[dict]:
    """Fetch all liked/saved tracks from the user's library.

    Returns:
        List of track dicts (unwrapped from items[].track).
    """
    logger.info("Fetching liked tracks")
    url = f"{config.spotify_api_url}/me/tracks?limit=50"
    items = _paginate(config, url)
    tracks = [item["track"] for item in items if item.get("track")]
    logger.info("Liked tracks: %d", len(tracks))
    return tracks
