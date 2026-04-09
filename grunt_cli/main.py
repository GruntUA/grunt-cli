"""Grunt CLI — головна точка входу."""

from __future__ import annotations

import os
import sys

from importlib.metadata import entry_points

import click

from grunt_cli import __version__


@click.group()
@click.version_option(version=__version__, prog_name="Ґрунт CLI")
def cli() -> None:
    """⚡ Ґрунт CLI — встановлення та управління Grunt-проєктами."""
    try:
        os.getcwd()
    except FileNotFoundError:
        click.echo("Помилка: Поточна директорія не існує. Спробуйте виконати 'cd .'", err=True)
        sys.exit(1)


from grunt_cli.commands.app import app  # noqa: E402
from grunt_cli.commands.auth import auth  # noqa: E402
from grunt_cli.commands.db import db  # noqa: E402
from grunt_cli.commands.doctype import doctype  # noqa: E402
from grunt_cli.commands.fixtures import fixtures  # noqa: E402
from grunt_cli.commands.init import init  # noqa: E402
from grunt_cli.commands.install import install  # noqa: E402
from grunt_cli.commands.master import master  # noqa: E402
from grunt_cli.commands.serve import serve  # noqa: E402
from grunt_cli.commands.shell import shell  # noqa: E402
from grunt_cli.commands.sites import sites  # noqa: E402
from grunt_cli.commands.test import test  # noqa: E402
from grunt_cli.commands.update import update  # noqa: E402
from grunt_cli.commands.users import users  # noqa: E402

cli.add_command(install)
cli.add_command(init)
cli.add_command(serve)
cli.add_command(db)
cli.add_command(doctype)
cli.add_command(auth)
cli.add_command(users)
cli.add_command(app)
cli.add_command(update)
cli.add_command(sites)
cli.add_command(test)
cli.add_command(master)
cli.add_command(shell)
cli.add_command(fixtures)


def _load_plugins() -> None:
    """Discover and register CLI commands from installed Grunt apps.

    Apps declare their commands in pyproject.toml:

        [project.entry-points."grunt.commands"]
        myapp = "myapp.cli:cli"

    The registered group/command is added to the top-level ``cli`` group.
    """
    for ep in entry_points(group="grunt.commands"):
        try:
            cmd = ep.load()
            if isinstance(cmd, click.BaseCommand):
                cli.add_command(cmd, name=ep.name)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"[warn] grunt.commands plugin '{ep.name}' failed to load: {exc}", err=True)


_load_plugins()
