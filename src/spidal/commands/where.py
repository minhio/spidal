from pathlib import Path

import typer

from spidal.commands import open_directory
from spidal.config import Config

where_app = typer.Typer()


@where_app.callback(invoke_without_command=True)
def where_callback(ctx: typer.Context) -> None:
    """Open file locations."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@where_app.command("config")
def where_config() -> None:
    """Open the config directory."""
    from spidal.config import CONFIG_DIR

    open_directory(CONFIG_DIR)


@where_app.command("db")
def where_db() -> None:
    """Open the database location."""
    from spidal.persistence import DB_PATH

    open_directory(DB_PATH.parent)


@where_app.command("dl")
def where_dl(ctx: typer.Context) -> None:
    """Open the music download directory."""
    config: Config = ctx.obj
    open_directory(Path(config.download_dir))


@where_app.command("logs")
def where_logs() -> None:
    """Open the log directory."""
    from spidal.config import LOG_DIR

    open_directory(LOG_DIR)
