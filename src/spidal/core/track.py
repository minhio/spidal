from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Track:
    isrc: str | None = None
    id: str | None = None
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    track_number: int | None = None
    duration: int | None = None
