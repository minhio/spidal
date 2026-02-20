import logging

import typer

from spidal.core.config import CONFIG_FILE, Config

logger = logging.getLogger(__name__)

config_app = typer.Typer()


def _validate_key(key: str) -> str:
    name = key.replace("-", "_")
    valid_keys = Config.valid_keys()
    if name not in valid_keys:
        typer.echo(f"Unknown key: {key}", err=True)
        typer.echo(f"Valid keys: {', '.join(sorted(valid_keys))}", err=True)
        raise typer.Exit(1)
    return name


@config_app.callback(invoke_without_command=True)
def config_callback(ctx: typer.Context) -> None:
    """Manage configuration."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@config_app.command("get")
def config_get(
    ctx: typer.Context,
    key: str = typer.Argument(help="Config key to get."),
) -> None:
    """Get a configuration value."""
    name = _validate_key(key)
    config: Config = ctx.obj
    value = getattr(config, name)
    source = config.get_source(name)
    display = value if value is not None else "(not set)"
    typer.echo(f"{name}: {display}  [{source}]")


@config_app.command("set")
def config_set(
    ctx: typer.Context,
    key: str = typer.Argument(help="Config key to set."),
    value: str = typer.Argument(help="Value to set."),
) -> None:
    """Set a configuration value."""
    name = _validate_key(key)
    config: Config = ctx.obj
    config.set(name, value)
    typer.echo(f"{name}: {value}")


@config_app.command("list")
def config_list(ctx: typer.Context) -> None:
    """Display current configuration values."""
    config: Config = ctx.obj

    typer.echo(f"Config file: {CONFIG_FILE}\n")
    for key, value, source in config.items():
        display = value if value is not None else "(not set)"
        typer.echo(f"{key}: {display}  [{source}]")
