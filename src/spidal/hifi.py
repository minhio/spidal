from __future__ import annotations

import base64
import json
import logging
import random
import re
from collections.abc import Generator
from urllib.parse import quote, urljoin

import requests

from spidal.config import Config

logger = logging.getLogger(__name__)


def _parse_track(track: dict) -> dict:
    artists_list = track.get("artists") or []
    artist = (track.get("artist") or {}).get("name") or (
        artists_list[0].get("name", "Unknown") if artists_list else "Unknown"
    )
    return {
        "id": track["id"],
        "title": track.get("title") or track.get("name"),
        "artist": artist,
        "album": (track.get("album") or {}).get("title")
        or (track.get("album") or {}).get("name"),
        "track_number": track.get("trackNumber") or track.get("track_number"),
        "isrc": track.get("isrc"),
        "duration": track.get("duration"),
    }


def _parse_album(album: dict) -> dict:
    artists_list = album.get("artists") or []
    artist = (album.get("artist") or {}).get("name") or (
        artists_list[0].get("name", "Unknown") if artists_list else "Unknown"
    )
    return {
        "id": album["id"],
        "title": album.get("title") or album.get("name"),
        "artist": artist,
        "numberOfTracks": album.get("numberOfTracks"),
        "duration": album.get("duration"),
    }


def _request(config: Config, path: str, **params: str) -> dict | None:
    """Make a request, trying each available hifi API endpoint until one succeeds.

    Returns the parsed response body, or None if all endpoints fail.

    Raises:
        ConnectionError: If no endpoints are configured.
    """
    apis = config.get_apis()
    if not apis:
        raise ConnectionError("No hifi API endpoints available")

    shuffled = list(apis)
    random.shuffle(shuffled)
    query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())

    for api in shuffled:
        url = f"{api}/{path}?{query}" if query else f"{api}/{path}"
        logger.info("Requesting: %s", url)

        try:
            resp = requests.get(url, timeout=10)
        except requests.RequestException as e:
            logger.warning("Request failed for %s: %s", api, e)
            continue

        if not resp.ok:
            logger.warning("Request returned %s from %s", resp.status_code, api)
            continue

        body = resp.json()
        return body.get("data", body)

    return None


def _search_page(config: Config, query: str, offset: int = 0) -> tuple[list[dict], int]:
    """Fetch a single page of search results.

    Returns:
        Tuple of (parsed track list, total number of items).
    """
    params: dict[str, str] = {"s": query}
    if offset:
        params["offset"] = str(offset)
    data = _request(config, "search", **params)
    if data is None:
        logger.warning("Track search returned no data for query %r", query)
        return [], 0

    items = data.get("items", [])
    total = data.get("totalNumberOfItems", len(items))
    logger.debug("Track search %r: %d/%d results", query, len(items), total)
    return [_parse_track(t) for t in items], total


def _search_albums_page(
    config: Config, query: str, offset: int = 0
) -> tuple[list[dict], int]:
    """Fetch a single page of album search results.

    Returns:
        Tuple of (parsed album list, total number of items).
    """
    params: dict[str, str] = {"al": query}
    if offset:
        params["offset"] = str(offset)
    data = _request(config, "search", **params)
    if data is None:
        logger.warning("Album search returned no data for query %r", query)
        return [], 0

    # Album search results are nested under an "albums" key
    albums_section = data.get("albums", data)
    items = albums_section.get("items", [])
    total = albums_section.get("totalNumberOfItems", len(items))
    logger.debug("Album search %r: %d/%d results", query, len(items), total)
    return [_parse_album(a) for a in items], total


def search_albums(config: Config, query: str) -> list[dict]:
    """Search for albums via the hifi API (first page only).

    Args:
        config: Config instance with API endpoints configured.
        query: Search query, e.g. "Artist Album Name".

    Returns:
        List of matching album dicts (may be empty).

    Raises:
        ConnectionError: If no endpoints are available or request fails.
    """
    albums, _ = _search_albums_page(config, query)
    return albums


def search_track(config: Config, query: str) -> list[dict]:
    """Search for tracks via the hifi API (first page only).

    Args:
        config: Config instance with API endpoints configured.
        query: Search query, e.g. "Artist Track Name".

    Returns:
        List of matching track dicts (may be empty).

    Raises:
        ConnectionError: If no endpoints are available or request fails.
    """
    tracks, _ = _search_page(config, query)
    return tracks


def match_track(config: Config, query: str, isrc: str) -> dict | None:
    """Search for a track and match by ISRC.

    The API ignores offset/limit params and always returns the first 25
    results, so pagination is not possible — we search once.

    Args:
        config: Config instance with API endpoints configured.
        query: Search query, e.g. "Artist Track Name".
        isrc: ISRC code to match against.

    Returns:
        Matched track dict, or None if no ISRC match found.
    """
    results, _total = _search_page(config, query)
    for track in results:
        if track.get("isrc") == isrc:
            logger.info("ISRC match found: %s (id=%s)", isrc, track["id"])
            return track

    logger.warning("No ISRC match for %s in %d results", isrc, len(results))
    return None


def iter_spotify_matches(
    config: Config, spotify_tracks: list[dict]
) -> Generator[tuple[dict, dict | None], None, None]:
    """Yield (spotify_track, matched_hifi_track | None) for each Spotify track.

    Allows callers to interleave matching with downloads. The matched track
    has its `album` field overridden with the Spotify album name when present.
    """
    for st in spotify_tracks:
        title = st.get("name", "Unknown")
        artists = ", ".join(a["name"] for a in st.get("artists", []))
        isrc = st.get("external_ids", {}).get("isrc")
        if not isrc:
            yield st, None
            continue
        track = match_track(config, f"{artists} {title}", isrc)
        if track:
            track["album"] = st.get("album", {}).get("name") or track.get("album")
            yield st, track
        else:
            yield st, None


def get_album_tracks(config: Config, album_id: int) -> tuple[str, list[dict]]:
    """Fetch all tracks from an album.

    Returns:
        Tuple of (album_title, list of parsed track dicts).

    Raises:
        ConnectionError: If no endpoints are available.
        ValueError: If the album is not found.
    """
    data = _request(config, "album/", id=str(album_id))
    if data is None:
        logger.error("Album not found: %s", album_id)
        raise ValueError(f"Album not found: {album_id}")

    album_title = data.get("title") or data.get("name") or "Unknown"
    raw_items = data.get("items", [])
    total = (
        data.get("numberOfTracks") or data.get("totalNumberOfItems") or len(raw_items)
    )

    logger.info("Album %s: %r (%d tracks)", album_id, album_title, total)

    # Paginate if needed (limit=500, matching monochrome frontend)
    offset = len(raw_items)
    while offset < total:
        logger.debug("Fetching album %s page at offset %d/%d", album_id, offset, total)
        page = _request(
            config, "album/", id=str(album_id), offset=str(offset), limit="500"
        )
        if page is None:
            break
        page_items = page.get("items", [])
        if not page_items:
            break
        raw_items.extend(page_items)
        offset += len(page_items)

    # Album items may be wrapped as {"item": <track>, "type": "track"}
    items = [
        i.get("item", i) if isinstance(i, dict) and "item" in i else i
        for i in raw_items
    ]
    return album_title, [_parse_track(t) for t in items]


def get_track_info(config: Config, track_id: int) -> dict | None:
    """Fetch full track info from the hifi API.

    Args:
        config: Config instance with API endpoints configured.
        track_id: Monochrome track ID.

    Returns:
        Track info dict, or None if not found.

    Raises:
        ConnectionError: If no endpoints are available.
    """
    data = _request(config, "info/", id=str(track_id))
    if data is None:
        return None
    return _parse_track(data)


def _parse_dash_manifest(manifest_str: str) -> list[str]:
    """Parse a DASH XML manifest into a list of segment URLs."""
    segments: list[str] = []

    base_url_match = re.search(r"<BaseURL>([^<]+)</BaseURL>", manifest_str)
    base_url = base_url_match.group(1) if base_url_match else ""

    def resolve_url(url: str) -> str:
        if re.match(r"^https?://", url, re.IGNORECASE):
            return url
        if base_url:
            return urljoin(base_url, url)
        return url

    init_match = re.search(r'initialization="([^"]+)"', manifest_str, re.IGNORECASE)
    media_match = re.search(r'media="([^"]+)"', manifest_str, re.IGNORECASE)
    start_match = re.search(r'startNumber="(\d+)"', manifest_str, re.IGNORECASE)

    if init_match and media_match:
        segments.append(resolve_url(init_match.group(1).strip()))
        media_template = media_match.group(1).strip()
        start_number = int(start_match.group(1)) if start_match else 1

        seg_num = start_number
        for m in re.finditer(
            r'<S[^>]*\sd="(\d+)"(?:[^>]*\sr="(-?\d+)")?[^>]*/?>',
            manifest_str,
            re.IGNORECASE,
        ):
            repeat = int(m.group(2)) if m.group(2) else 0
            count = max(1, repeat + 1)
            for _ in range(count):
                segments.append(
                    resolve_url(media_template.replace("$Number$", str(seg_num)))
                )
                seg_num += 1

        return segments

    # Fallback: SegmentURL approach
    for m in re.finditer(r'<SegmentURL\s+media="([^"]+)"', manifest_str, re.IGNORECASE):
        segments.append(resolve_url(m.group(1)))

    return segments


def _decode_manifest(raw: str) -> str:
    """Decode a manifest string, handling optional base64 encoding."""
    if "<" in raw or "{" in raw:
        return raw
    try:
        return base64.b64decode(raw).decode()
    except Exception:
        return raw


def _extract_stream_url(data: dict) -> str | list[str] | None:
    """Extract a stream URL from a track response. Returns None if not found."""
    # Try direct URL fields
    for key in ("originalTrackUrl", "streamUrl", "url"):
        url = data.get(key)
        if url:
            return url

    stream_obj = data.get("stream")
    if isinstance(stream_obj, dict):
        url = stream_obj.get("url")
        if url:
            return url

    # Try manifest
    manifest_raw = data.get("manifest")
    if manifest_raw:
        manifest_str = _decode_manifest(manifest_raw)

        # JSON manifest
        if "{" in manifest_str:
            try:
                parsed = json.loads(manifest_str)
                urls = parsed.get("urls", [])
                if urls:
                    return urls[0]
            except json.JSONDecodeError:
                pass

        # DASH XML manifest
        if "<" in manifest_str and "SegmentTemplate" in manifest_str:
            segments = _parse_dash_manifest(manifest_str)
            if segments:
                return segments

    return None


def get_stream_url(config: Config, track_id: int) -> str | list[str]:
    """Fetch the stream URL(s) for a track.

    Returns:
        A single URL string for direct downloads, or a list of segment URLs
        for DASH manifests.

    Raises:
        ConnectionError: If no endpoints are available.
        ValueError: If no usable stream URL can be extracted.
    """
    data = _request(config, "track/", id=str(track_id), quality=config.audio_quality)
    if data is None:
        raise ValueError(f"Failed to fetch stream data for track {track_id}")

    result = _extract_stream_url(data)
    if result is not None:
        return result

    raise ValueError(f"No usable stream URL for track {track_id}")


def iter_stream_urls(
    config: Config,
    track_id: int,
) -> Generator[str | list[str], None, None]:
    """Yield stream URLs from each API endpoint in shuffled order.

    Each iteration fetches from a different endpoint, so the caller can
    retry with the next one on download failure (e.g. 403 on DASH segments).
    """
    apis = config.get_apis()
    if not apis:
        raise ConnectionError("No hifi API endpoints available")

    shuffled = list(apis)
    random.shuffle(shuffled)
    query = f"id={track_id}&quality={config.audio_quality}"

    for api in shuffled:
        url = f"{api}/track/?{query}"
        logger.info("Requesting stream from: %s", url)
        try:
            resp = requests.get(url, timeout=10)
        except requests.RequestException as e:
            logger.warning("Stream request failed for %s: %s", api, e)
            continue
        if not resp.ok:
            logger.warning("Stream request returned %s from %s", resp.status_code, api)
            continue
        body = resp.json()
        data = body.get("data", body)
        result = _extract_stream_url(data)
        if result is not None:
            yield result
