import logging
import platform
import subprocess
import webbrowser
from pathlib import Path

from spidal.core.config import Config

logger = logging.getLogger(__name__)


def _prompt_token(config: Config) -> None:
    logger.info("Prompting user for Spotify token")
    webbrowser.open("https://developer.spotify.com")
    token = input("Paste your Spotify API token: ").strip()
    config.set_spotify_token(token)
    logger.info("Spotify token updated")


def ensure_token(config: Config) -> None:
    if not config.spotify_token:
        logger.info("No Spotify token configured, prompting user")
        _prompt_token(config)


def refresh_token(config: Config) -> None:
    logger.info("Refreshing Spotify token")
    _prompt_token(config)


def open_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    logger.info("Opening directory: %s", path)
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", str(path)])
    elif system == "Windows":
        subprocess.Popen(["explorer", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
