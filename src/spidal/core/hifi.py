from __future__ import annotations

import base64
import json
import logging
import random
import re
import xml.etree.ElementTree as ET
from collections.abc import Generator
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

_QUALITY_FALLBACK = ("HI_RES_LOSSLESS", "LOSSLESS")


def _parse_track(track: dict) -> dict:
    artists_list = track.get("artists") or []
    artist = (track.get("artist") or {}).get("name") or (
        artists_list[0].get("name", "Unknown") if artists_list else "Unknown"
    )
    return {
        "id": track["id"],
        "title": track.get("title"),
        "artist": artist,
        "album": (track.get("album") or {}).get("title"),
        "track_number": track.get("trackNumber"),
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
        "title": album.get("title"),
        "artist": artist,
        "numberOfTracks": album.get("numberOfTracks"),
        "duration": album.get("duration"),
    }


def _request(apis: list[str], path: str, **params: str) -> dict | None:
    """Make a request, trying each available hifi API endpoint until one succeeds.

    Returns the parsed response body, or None if all endpoints fail.

    Raises:
        ConnectionError: If no endpoints are configured.
    """
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


def search_tracks(apis: list[str], query: str) -> tuple[list[dict], int]:
    """Fetch a single page of search results.

    Returns:
        Tuple of (parsed track list, total number of items).
    """
    data = _request(apis, "search/", s=query)
    if data is None:
        logger.warning("Track search returned no data for query %r", query)
        return [], 0

    items = data.get("items", [])
    total = data.get("totalNumberOfItems", len(items))
    logger.debug("Track search %r: %d/%d results", query, len(items), total)
    return [_parse_track(t) for t in items], total


def search_albums(apis: list[str], query: str) -> tuple[list[dict], int]:
    """Fetch a single page of album search results.

    Returns:
        Tuple of (parsed album list, total number of items).
    """
    data = _request(apis, "search/", al=query)
    if data is None:
        logger.warning("Album search returned no data for query %r", query)
        return [], 0

    # Album search results are nested under an "albums" key
    albums_section = data.get("albums", data)
    items = albums_section.get("items", [])
    total = albums_section.get("totalNumberOfItems", len(items))
    logger.debug("Album search %r: %d/%d results", query, len(items), total)
    return [_parse_album(a) for a in items], total


def match_track(apis: list[str], query: str, isrc: str) -> dict | None:
    """Search for a track and match by ISRC.

    The API ignores offset/limit params and always returns the first 25
    results, so pagination is not possible — we search once.

    Args:
        apis: List of hifi API base URLs.
        query: Search query, e.g. "Artist Track Name".
        isrc: ISRC code to match against.

    Returns:
        Matched track dict, or None if no ISRC match found.
    """
    results, _ = search_tracks(apis, query)
    for track in results:
        if track.get("isrc") == isrc:
            logger.info("ISRC match found: %s (id=%s)", isrc, track["id"])
            return track

    logger.warning("No ISRC match for %s in %d results", isrc, len(results))
    return None


def get_album_tracks(apis: list[str], album_id: int) -> tuple[str, list[dict]]:
    """Fetch all tracks from an album.

    Returns:
        Tuple of (album_title, list of parsed track dicts).

    Raises:
        ConnectionError: If no endpoints are available.
        ValueError: If the album is not found.
    """
    data = _request(apis, "album/", id=str(album_id))
    if data is None:
        logger.error("Album not found: %s", album_id)
        raise ValueError(f"Album not found: {album_id}")

    album_title = data.get("title") or "Unknown"
    raw_items = data.get("items", [])
    total = data.get("numberOfTracks") or len(raw_items)

    logger.info("Album %s: %r (%d tracks)", album_id, album_title, total)

    # Paginate if needed (limit=500, matching monochrome frontend)
    offset = len(raw_items)
    while offset < total:
        logger.debug("Fetching album %s page at offset %d/%d", album_id, offset, total)
        page = _request(
            apis, "album/", id=str(album_id), offset=str(offset), limit="500"
        )
        if page is None:
            break
        page_items = page.get("items", [])
        if not page_items:
            break
        # Safeguard: if the API ignores offset and returns page 1 again, stop.
        if raw_items and page_items[0].get("id") == raw_items[0].get("id"):
            logger.warning("Album %s pagination loop detected at offset %d, stopping", album_id, offset)
            break
        raw_items.extend(page_items)
        offset += len(page_items)

    # Album items may be wrapped as {"item": <track>, "type": "track"}
    items = [
        i.get("item", i) if isinstance(i, dict) and "item" in i else i
        for i in raw_items
    ]
    return album_title, [_parse_track(t) for t in items]


def get_track_info(apis: list[str], track_id: int) -> dict | None:
    """Fetch full track info from the hifi API.

    Args:
        apis: List of hifi API base URLs.
        track_id: Monochrome track ID.

    Returns:
        Track info dict, or None if not found.

    Raises:
        ConnectionError: If no endpoints are available.
    """
    data = _request(apis, "info/", id=str(track_id))
    if data is None:
        return None
    return _parse_track(data)


def _dash_base_url(*els: ET.Element) -> str:
    """Return the deepest BaseURL found among elements, searching innermost first."""
    for el in els:
        bu = el.find("BaseURL")
        if bu is not None and bu.text:
            return bu.text.strip()
    return ""


def _dash_join(base: str, part: str) -> str:
    if not base or part.startswith("http"):
        return part
    return (base if base.endswith("/") else base + "/") + part


def _dash_apply_template(template: str, rep_id: str, number: int, time: int) -> str:
    def _fmt(val: int) -> re.Pattern:
        return lambda m: str(val).zfill(int(m.group(1))) if m.group(1) else str(val)

    out = template.replace("$RepresentationID$", rep_id)
    out = re.sub(r"\$Number(?:%0(\d+)d)?\$", _fmt(number), out)
    out = re.sub(r"\$Time(?:%0(\d+)d)?\$", _fmt(time), out)
    return out


def _parse_dash_manifest(manifest_str: str) -> list[str]:
    """Parse a DASH XML manifest into a list of segment URLs.

    Selects the highest-bandwidth audio Representation, resolves BaseURL at
    all nesting levels (MPD → Period → AdaptationSet → Representation), and
    supports $RepresentationID$, $Number$, $Number%0Nd$, and $Time$ template
    variables.
    """
    ns_clean = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', "", manifest_str)
    root = ET.fromstring(ns_clean)

    period = root.find("Period")
    if period is None:
        logger.warning("DASH manifest missing Period element")
        return []

    adaptation_sets = period.findall("AdaptationSet")
    if not adaptation_sets:
        logger.warning("DASH manifest missing AdaptationSet elements")
        return []

    def _bw(el: ET.Element) -> int:
        return max((int(r.get("bandwidth", "0")) for r in el.findall("Representation")), default=0)

    audio_sets = [a for a in adaptation_sets if (a.get("mimeType") or "").startswith("audio")]
    adaptation_set = max(audio_sets or adaptation_sets, key=_bw)

    representations = adaptation_set.findall("Representation")
    if not representations:
        logger.warning("DASH AdaptationSet has no Representation elements")
        return []

    rep = max(representations, key=lambda r: int(r.get("bandwidth", "0")))
    rep_id = rep.get("id", "")
    base_url = _dash_base_url(rep, adaptation_set, period, root)

    seg_template = rep.find("SegmentTemplate")
    if seg_template is None:
        seg_template = adaptation_set.find("SegmentTemplate")
    if seg_template is None:
        return [
            _dash_join(base_url, media)
            for seg_url in rep.findall(".//SegmentURL") or adaptation_set.findall(".//SegmentURL")
            if (media := seg_url.get("media", ""))
        ]

    initialization = seg_template.get("initialization", "")
    media = seg_template.get("media", "")
    start_number = int(seg_template.get("startNumber", "1"))

    segments: list[str] = []
    if initialization:
        segments.append(_dash_join(base_url, _dash_apply_template(initialization, rep_id, 0, 0)))

    seg_num = start_number
    current_time = 0
    timeline = seg_template.find("SegmentTimeline")
    if timeline is not None:
        for s in timeline.findall("S"):
            if (t := s.get("t")) is not None:
                current_time = int(t)
            d = int(s.get("d", "0"))
            for _ in range(int(s.get("r", "0")) + 1):
                segments.append(_dash_join(base_url, _dash_apply_template(media, rep_id, seg_num, current_time)))
                seg_num += 1
                current_time += d

    return segments


def _extract_stream_url(data: dict) -> str | list[str] | None:
    """Extract a stream URL from a track response. Returns None if not found."""
    manifest_raw = data.get("manifest")
    if not manifest_raw:
        logger.warning("No manifest in track response")
        return None

    try:
        manifest_str = base64.b64decode(manifest_raw).decode()
    except Exception as e:
        logger.warning("Failed to decode manifest: %s", e)
        return None

    # JSON manifest → direct URL
    if "{" in manifest_str:
        try:
            parsed = json.loads(manifest_str)
            urls = parsed.get("urls", [])
            if urls:
                logger.info("JSON manifest: direct URL")
                return urls[0]
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse JSON manifest: %s", e)

    # DASH XML manifest → segment list
    if "<" in manifest_str and "SegmentTemplate" in manifest_str:
        segments = _parse_dash_manifest(manifest_str)
        if segments:
            logger.info("DASH manifest: %d segments", len(segments))
            return segments

    logger.warning("Unrecognised manifest format")
    return None


def iter_stream_urls(
    apis: list[str],
    track_id: int,
) -> Generator[str | list[str], None, None]:
    """Yield stream URLs, trying HI_RES_LOSSLESS across all endpoints first,
    then LOSSLESS across all endpoints.

    Each yielded value comes from a different (endpoint, quality) combination,
    so the caller can retry with the next one on download failure.
    """
    if not apis:
        raise ConnectionError("No hifi API endpoints available")

    shuffled = list(apis)
    random.shuffle(shuffled)

    for quality in _QUALITY_FALLBACK:
        for api in shuffled:
            url = f"{api}/track/?id={track_id}&quality={quality}"
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
