from __future__ import annotations

import logging

from spidal.core.hifi import match_track

logger = logging.getLogger(__name__)


def match_tracks_by_isrc(
    apis: list[str], spotify_tracks: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Match Spotify tracks to hifi tracks by ISRC.

    Returns:
        Tuple of (matched_hifi_tracks, unmatched_dicts).
        Matched tracks have both hifi_* and spotify_* fields populated.
        Unmatched dicts have only spotify_* fields (isrc may be None for
        tracks that had no ISRC).
    """
    matched: list[dict] = []
    unmatched: list[dict] = []
    for st in spotify_tracks:
        title = st.get("name", "Unknown")
        artists = ", ".join(a["name"] for a in st.get("artists", []))
        isrc = st.get("external_ids", {}).get("isrc")
        spotify_dict = {
            "isrc": isrc,
            "spotify_id": st.get("id"),
            "spotify_title": title,
            "spotify_artist": artists,
            "spotify_album": st.get("album", {}).get("name"),
            "spotify_track_number": st.get("track_number"),
            "spotify_duration": st.get("duration_ms"),
        }
        if not isrc:
            unmatched.append(spotify_dict)
            continue
        first_artist = st.get("artists", [{}])[0].get("name", "") if st.get("artists") else ""
        track = match_track(apis, f"{first_artist} {title}", isrc)
        if not track:
            words = title.split()
            short_title = " ".join(words[: max(1, len(words) // 2)])
            logger.debug("Retrying with shortened title: %r", short_title)
            track = match_track(apis, f"{first_artist} {short_title}", isrc)
        if track:
            matched.append({
                **track,
                "isrc": isrc,
                "spotify_id": st.get("id"),
                "spotify_title": title,
                "spotify_artist": artists,
                "spotify_album": st.get("album", {}).get("name"),
                "spotify_track_number": st.get("track_number"),
                "spotify_duration": st.get("duration_ms"),
            })
        else:
            unmatched.append(spotify_dict)
    logger.info(
        "Matched %d/%d Spotify tracks (%d unmatched)",
        len(matched), len(spotify_tracks), len(unmatched),
    )
    return matched, unmatched
