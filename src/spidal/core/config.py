from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, fields
from logging.handlers import RotatingFileHandler
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

STATE_DIR = (
    Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "spidal"
)
LOG_DIR = STATE_DIR / "logs"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "spidal"
CONFIG_FILE = CONFIG_DIR / "config.json"

DOWNLOAD_DIR = Path.home() / "Music" / "spidal"
SPOTIFY_API_URL = "https://api.spotify.com/v1"

DEFAULTS: dict[str, str | None] = {
    "spotify-token": None,
    "hifi-api": None,
    "hifi-api-file": None,
    "download-dir": str(DOWNLOAD_DIR),
    "download-delay": "0",
    "disable-tagging": "false",
}

ENV_PREFIX = "SPIDAL_"


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


def _load_apis_from_source(source: str) -> list[str]:
    """Load API list from a URL or local JSON file."""
    if source.startswith(("http://", "https://")):
        logger.info("Fetching API list from URL: %s", source)
        data = requests.get(source).json()
    else:
        logger.info("Loading API list from file: %s", source)
        data = json.loads(Path(source).read_text())

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
    hifi_api_file: str | None = None
    download_dir: str | None = None
    download_delay: str | None = None
    disable_tagging: str | None = None
    _apis_cache: list[str] | None = field(default=None, init=False, repr=False)
    _sources: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    @classmethod
    def valid_keys(cls) -> set[str]:
        return {f.name.replace("_", "-") for f in fields(cls) if f.init}

    @classmethod
    def load(cls, **overrides: str | None) -> Config:
        """Load config by merging defaults, env vars, config file, and explicit overrides.

        Priority: overrides (CLI args) > config file > env vars > defaults.
        """
        saved = load_config_file()

        values: dict[str, str | None] = {}
        sources: dict[str, str] = {}
        for f in fields(cls):
            if not f.init:
                continue
            dashed = f.name.replace("_", "-")
            default = DEFAULTS.get(dashed)
            env_val = os.environ.get(f"{ENV_PREFIX}{f.name.upper()}")
            override = overrides.get(f.name)
            saved_val = saved.get(dashed)

            if override is not None:
                values[f.name] = override
                source = "cli"
            elif saved_val is not None:
                values[f.name] = saved_val
                source = "file"
            elif env_val is not None:
                values[f.name] = env_val
                source = "env"
            else:
                values[f.name] = default
                source = "default"
            sources[f.name] = source
            logger.info("Config %s=%s (source: %s)", dashed, values[f.name], source)

        config = cls(**values)
        config._sources = sources
        if config.hifi_api and config.hifi_api_file:
            raise ValueError("Cannot set both hifi-api and hifi-api-file")

        logger.info("Config loaded: %s", config)
        return config

    def get_apis(self) -> list[str]:
        if self._apis_cache is not None:
            return self._apis_cache

        _INSTANCES_URL = "https://raw.githubusercontent.com/monochrome-music/monochrome/main/public/instances.json"
        if self.hifi_api:
            self._apis_cache = [self.hifi_api]
        else:
            self._apis_cache = _load_apis_from_source(self.hifi_api_file or _INSTANCES_URL)

        return self._apis_cache

    def get_spotify_token(self) -> str | None:
        return self.spotify_token

    def get_hifi_api(self) -> str | None:
        return self.hifi_api

    def get_hifi_api_file(self) -> str | None:
        return self.hifi_api_file

    def get_download_dir(self) -> str | None:
        return self.download_dir

    def get_download_delay(self) -> str | None:
        return self.download_delay

    def get_disable_tagging(self) -> str | None:
        return self.disable_tagging

    def items(self) -> list[tuple[str, str | None, str]]:
        result = []
        for f in fields(self):
            if not f.init:
                continue
            dashed = f.name.replace("_", "-")
            value = getattr(self, f.name)
            source = self._sources.get(f.name, "unknown")
            result.append((dashed, value, source))
        return result

    def get_source(self, key: str) -> str:
        field_name = key.replace("-", "_")
        return self._sources.get(field_name, "unknown")

    def _set(self, name: str, value: str) -> None:
        setattr(self, name, value)
        self._sources[name] = "file"
        dashed = name.replace("_", "-")
        logger.info("Saving %s to config file", dashed)
        saved = load_config_file()
        saved[dashed] = value
        save_config_file(saved)

    def set_spotify_token(self, token: str) -> None:
        self._set("spotify_token", token)

    def set_hifi_api(self, api: str) -> None:
        if self.hifi_api_file:
            raise ValueError("Cannot set both hifi-api and hifi-api-file")
        self._set("hifi_api", api)
        self._apis_cache = None

    def set_hifi_api_file(self, path: str) -> None:
        if self.hifi_api:
            raise ValueError("Cannot set both hifi-api and hifi-api-file")
        self._set("hifi_api_file", path)
        self._apis_cache = None

    def set_download_dir(self, directory: str) -> None:
        self._set("download_dir", directory)

    def set_download_delay(self, delay: str) -> None:
        self._set("download_delay", delay)

    def set_disable_tagging(self, value: str) -> None:
        self._set("disable_tagging", value)
