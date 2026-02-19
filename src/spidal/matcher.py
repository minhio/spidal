from __future__ import annotations

import logging

from spidal.hifi import match_track

logger = logging.getLogger(__name__)


def match_spotify_tracks(
    apis: list[str], spotify_tracks: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Match Spotify tracks to hifi tracks by ISRC.

    Returns:
        Tuple of (matched_hifi_tracks, unmatched_spotify_tracks).
        Unmatched includes tracks with no ISRC and tracks with no hifi match.
    """
    matched: list[dict] = []
    unmatched: list[dict] = []
    for st in spotify_tracks:
        title = st.get("name", "Unknown")
        artists = ", ".join(a["name"] for a in st.get("artists", []))
        isrc = st.get("external_ids", {}).get("isrc")
        if not isrc:
            unmatched.append(st)
            continue
        track = match_track(apis, f"{artists} {title}", isrc)
        if track:
            track["album"] = st.get("album", {}).get("name") or track.get("album")
            matched.append(track)
        else:
            unmatched.append(st)
    logger.info(
        "Matched %d/%d Spotify tracks (%d unmatched)",
        len(matched), len(spotify_tracks), len(unmatched),
    )
    return matched, unmatched
