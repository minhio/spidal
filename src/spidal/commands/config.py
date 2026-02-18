import logging
import os
from dataclasses import fields as dc_fields

import typer

from spidal.commands import open_directory
from spidal.config import Config

logger = logging.getLogger(__name__)

config_app = typer.Typer()


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
    from spidal.config import DEFAULTS, ENV_PREFIX, load_config_file

    dashed_key = key.replace("_", "-")
    valid_keys = {f.name.replace("_", "-") for f in dc_fields(Config) if f.init}
    if dashed_key not in valid_keys:
        typer.echo(f"Unknown key: {key}", err=True)
        typer.echo(f"Valid keys: {', '.join(sorted(valid_keys))}", err=True)
        raise typer.Exit(1)

    config: Config = ctx.obj
    field_name = dashed_key.replace("-", "_")
    value = getattr(config, field_name)
    env_val = os.environ.get(f"{ENV_PREFIX}{field_name.upper()}")
    saved = load_config_file()
    saved_val = saved.get(dashed_key)

    if saved_val is not None and value == saved_val:
        source = "file"
    elif env_val is not None and value == env_val:
        source = "env"
    elif value == DEFAULTS.get(dashed_key):
        source = "default"
    else:
        source = "cli"

    display = value if value is not None else "(not set)"
    typer.echo(f"{dashed_key}: {display}  [{source}]")


@config_app.command("set")
def config_set(
    key: str = typer.Argument(help="Config key to set."),
    value: str = typer.Argument(help="Value to set."),
) -> None:
    """Set a configuration value."""
    from spidal.config import load_config_file, save_config_file

    dashed_key = key.replace("_", "-")
    valid_keys = {f.name.replace("_", "-") for f in dc_fields(Config) if f.init}
    if dashed_key not in valid_keys:
        typer.echo(f"Unknown key: {key}", err=True)
        typer.echo(f"Valid keys: {', '.join(sorted(valid_keys))}", err=True)
        raise typer.Exit(1)

    saved = load_config_file()
    saved[dashed_key] = value
    save_config_file(saved)
    logger.info("Config set: %s = %r", dashed_key, value)
    typer.echo(f"{dashed_key}: {value}")


@config_app.command("list")
def config_list(ctx: typer.Context) -> None:
    """Display current configuration values."""
    from spidal.config import CONFIG_FILE, DEFAULTS, ENV_PREFIX, load_config_file

    config: Config = ctx.obj
    saved = load_config_file()

    typer.echo(f"Config file: {CONFIG_FILE}\n")
    for f in dc_fields(Config):
        if not f.init:
            continue
        value = getattr(config, f.name)
        env_val = os.environ.get(f"{ENV_PREFIX}{f.name.upper()}")
        dashed = f.name.replace("_", "-")
        saved_val = saved.get(dashed)
        if saved_val is not None and value == saved_val:
            source = "file"
        elif env_val is not None and value == env_val:
            source = "env"
        elif value == DEFAULTS.get(dashed):
            source = "default"
        else:
            source = "cli"
        display = value if value is not None else "(not set)"
        typer.echo(f"{dashed}: {display}  [{source}]")
