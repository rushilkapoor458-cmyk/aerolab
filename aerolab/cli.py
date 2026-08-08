"""Command-line interface for aerolab.

The CLI is the one place in the package where angles are expressed in
**degrees**, because that is what every wind-tunnel test matrix and every
published polar uses. Conversion to radians happens immediately on entry to
the solver layer; nothing below this module sees a degree.
"""

from __future__ import annotations

import typer

from aerolab import __version__

app = typer.Typer(
    name="aerolab",
    help="A 2D/3D subsonic aerodynamics toolkit.",
    add_completion=False,
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Entry point for the `aerolab` command group.

    This callback exists for a structural reason, not a functional one. Typer
    collapses an app holding exactly one command into a single-command CLI,
    which silently drops the subcommand name — `aerolab version` would fail
    until a second command happened to be added. Declaring a callback pins the
    app as a command group from the start, so subcommand names are stable no
    matter how many commands exist.
    """


@app.command()
def version() -> None:
    """Print the installed aerolab version and exit."""
    typer.echo(f"aerolab {__version__}")


if __name__ == "__main__":  # pragma: no cover - manual entry point
    app()
