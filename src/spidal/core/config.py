from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, fields
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "spidal"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "spidal"
LOG_DIR = STATE_DIR / "logs"
CONFIG_FILE = CONFIG_DIR / "config.json"

SPOTIFY_API_URL = "https://api.spotify.com/v1"
HIFI_API_INSTANCES_URL = "https://raw.githubusercontent.com/monochrome-music/monochrome/main/public/instances.json"

_BOOL_FIELDS = {"disable_tagging", "disable_mp4_to_flac"}


def _parse_bool(v: str | bool | None) -> bool:
    if isinstance(v, bool):
        return v
    return bool(v) and v.lower() not in ("false", "0", "")


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            RotatingFileHandler(
                LOG_DIR / "spidal.log", maxBytes=1_000_000, backupCount=10
            ),
        ],
    )
    logging.getLogger("musicbrainzngs").setLevel(logging.WARNING)


def load_config_file() -> dict[str, str]:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except FileNotFoundError:
        logger.debug("Config file not found: %s", CONFIG_FILE)
        return {}
    except json.JSONDecodeError as e:
        logger.warning("Config file is malformed, ignoring: %s", e)
        return {}


def save_config_file(data: dict[str, str]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CONFIG_FILE.write_text(json.dumps(data, indent=2) + "\n")
        logger.info("Config saved: %s", CONFIG_FILE)
    except OSError as e:
        logger.error("Failed to save config file: %s", e)


def _load_apis_from_url(url: str) -> list[str]:
    """Load API list from a URL."""
    logger.info("Fetching API list from URL: %s", url)
    data = requests.get(url).json()

    if not isinstance(data, dict) or "api" not in data:
        raise ValueError("Expected JSON object with an 'api' key")
    apis = data["api"]
    if not isinstance(apis, list):
        raise ValueError("Expected 'api' to be a list")
    logger.info("Loaded APIs: %s", apis)
    return list(apis)


@dataclass
class Config:
    spotify_token: str | None = None
    hifi_api: str | None = None
    download_dir: str = str(Path.home() / "Music" / "spidal")
    download_delay: int = 0
    disable_tagging: bool = False
    disable_mp4_to_flac: bool = False
    _apis_cache: list[str] | None = field(default=None, init=False, repr=False)
    _sources: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    @classmethod
    def valid_keys(cls) -> set[str]:
        return {f.name for f in fields(cls) if f.init}

    @classmethod
    def load(cls, **overrides: str | None) -> Config:
        """Load config by merging defaults, config file, and explicit overrides.

        Priority: overrides (CLI args) > config file > defaults.
        """
        saved = load_config_file()

        values: dict[str, str | None] = {}
        sources: dict[str, str] = {}
        for f in fields(cls):
            if not f.init:
                continue
            override = overrides.get(f.name)
            saved_val = saved.get(f.name)

            if override is not None:
                values[f.name] = override
                source = "cli"
            elif saved_val is not None:
                values[f.name] = saved_val
                source = "file"
            else:
                source = "default"
            sources[f.name] = source
            logger.info("Config %s=%s (source: %s)", f.name, values.get(f.name, f.default), source)

        for name in _BOOL_FIELDS:
            if name in values:
                values[name] = _parse_bool(values[name])  # type: ignore[assignment]
        if "download_delay" in values and values["download_delay"] is not None:
            values["download_delay"] = int(values["download_delay"])  # type: ignore[assignment]

        config = cls(**values)
        config._sources = sources

        logger.info("Config loaded: %s", config)
        return config

    def get_apis(self) -> list[str]:
        if self._apis_cache is not None:
            return self._apis_cache

        if self.hifi_api:
            self._apis_cache = [self.hifi_api]
        else:
            self._apis_cache = _load_apis_from_url(HIFI_API_INSTANCES_URL)

        return self._apis_cache

    def items(self) -> list[tuple[str, str | None, str]]:
        result = []
        for f in fields(self):
            if not f.init:
                continue
            value = getattr(self, f.name)
            source = self._sources.get(f.name, "unknown")
            result.append((f.name, value, source))
        return result

    def get_source(self, key: str) -> str:
        name = key.replace("-", "_")
        return self._sources.get(name, "unknown")

    def set(self, key: str, value: str) -> None:
        name = key.replace("-", "_")
        if name not in self.valid_keys():
            raise ValueError(f"Unknown config key: {key}")
        setattr(self, name, _parse_bool(value) if name in _BOOL_FIELDS else value)
        self._sources[name] = "file"
        logger.info("Saving %s to config file", name)
        saved = load_config_file()
        saved[name] = value
        save_config_file(saved)
        if name == "hifi_api":
            self._apis_cache = None
