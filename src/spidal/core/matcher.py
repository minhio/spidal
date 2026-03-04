from __future__ import annotations

import logging

from spidal.core.hifi import match_track
from spidal.core.track import Track

logger = logging.getLogger(__name__)


def match_tracks_by_isrc(apis: list[str], spotify_tracks: list[Track]) -> list[Track]:
    """Match Spotify tracks to hifi tracks by ISRC.

    Returns:
        List of matched hifi Track objects.
    """
    matched: list[Track] = []
    for spotify_track in spotify_tracks:
        if not spotify_track.isrc:
            continue
        query = f"{spotify_track.artist} {spotify_track.title}"
        hifi_dict = match_track(apis, query, spotify_track.isrc)
        if not hifi_dict:
            words = (spotify_track.title or "").split()
            if len(words) > 1:
                short_title = " ".join(words[: len(words) // 2])
                logger.debug("Retrying with shortened title: %r", short_title)
                hifi_dict = match_track(apis, f"{spotify_track.artist} {short_title}", spotify_track.isrc)
        if hifi_dict:
            matched.append(hifi_dict)
    logger.info(
        "Matched %d/%d Spotify tracks",
        len(matched), len(spotify_tracks),
    )
    return matched
