import importlib.metadata
import logging
from pathlib import Path
from typing import Optional

import typer

from spidal.commands.config import config_app
from spidal.commands.get import get
from spidal.commands.logs import logs
from spidal.commands.where import where_app
from spidal.core.config import Config, setup_logging

logger = logging.getLogger(__name__)

app = typer.Typer()
app.add_typer(config_app, name="config", help="Manage configuration.")
app.add_typer(where_app, name="where", help="Open file locations.")
app.command("get")(get)
app.command("logs")(logs)


def _version_callback(value: bool) -> None:
    if value:
        version = importlib.metadata.version("spidal")
        typer.echo(version)
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    spotify_token: Optional[str] = typer.Option(None),
    hifi_api: Optional[str] = typer.Option(None),
    hifi_api_file: Optional[str] = typer.Option(None),
    download_dir: Optional[Path] = typer.Option(None),
    version: Optional[bool] = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """FLAC downloader."""
    setup_logging()
    config = Config.load(
        spotify_token=spotify_token,
        hifi_api=hifi_api,
        hifi_api_file=hifi_api_file,
        download_dir=str(download_dir) if download_dir else None,
    )
    ctx.obj = config
    if ctx.invoked_subcommand is None:
        logger.info("Launching TUI")
        from spidal.tui import SpidalApp

        SpidalApp(config).run()
        logger.info("TUI exited")


@app.command("search")
def search(
    ctx: typer.Context,
    query: str = typer.Argument(None, help="Search query"),
) -> None:
    """Search for tracks interactively."""
    logger.info("Launching search TUI (query=%r)", query)
    from spidal.commands.search import SearchApp

    SearchApp(ctx.obj, query).run()


if __name__ == "__main__":
    app()
