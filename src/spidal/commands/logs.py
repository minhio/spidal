from collections import deque

import typer


_LEVEL_STYLES = {
    "DEBUG": "dim",
    "INFO": "cyan",
    "WARNING": "yellow",
    "ERROR": "bold red",
    "CRITICAL": "bold white on red",
}


def _style_line(line: str) -> str:
    """Wrap a log line with Rich markup based on its level."""
    for level, style in _LEVEL_STYLES.items():
        if f" {level} " in line:
            # Highlight just the level token, dim the timestamp, rest normal
            parts = line.split(f" {level} ", 1)
            timestamp = f"[dim]{parts[0]}[/dim]"
            rest = parts[1].rstrip("\n")
            return f"{timestamp} [{style}]{level}[/{style}] {rest}"
    return line.rstrip("\n")


def logs(
    n: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
    plain: bool = typer.Option(False, "--plain", help="Plain text, no color"),
) -> None:
    """Display the last N lines of the log file."""
    from spidal.config import LOG_DIR

    log_file = LOG_DIR / "spidal.log"
    if not log_file.exists():
        typer.echo("No log file found.")
        raise typer.Exit()

    with open(log_file) as f:
        lines = deque(f, maxlen=n)

    if plain:
        for line in lines:
            typer.echo(line, nl=False)
        return

    from rich.console import Console
    from rich.text import Text

    console = Console()
    for line in lines:
        console.print(_style_line(line), highlight=False)
