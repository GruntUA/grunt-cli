"""Grunt CLI — головна точка входу."""

from __future__ import annotations

import click

from grunt_cli import __version__


@click.group()
@click.version_option(version=__version__, prog_name="Ґрунт CLI")
def cli() -> None:
    """⚡ Ґрунт CLI — встановлення та управління Grunt-проєктами."""


from grunt_cli.commands.install import install  # noqa: E402
from grunt_cli.commands.init import init  # noqa: E402
from grunt_cli.commands.serve import serve  # noqa: E402
from grunt_cli.commands.db import db  # noqa: E402
from grunt_cli.commands.doctype import doctype  # noqa: E402
from grunt_cli.commands.auth import auth  # noqa: E402
from grunt_cli.commands.app import app  # noqa: E402
from grunt_cli.commands.update import update  # noqa: E402
from grunt_cli.commands.sites import sites  # noqa: E402
from grunt_cli.commands.test import test  # noqa: E402
from grunt_cli.commands.master import master  # noqa: E402

cli.add_command(install)
cli.add_command(init)
cli.add_command(serve)
cli.add_command(db)
cli.add_command(doctype)
cli.add_command(auth)
cli.add_command(app)
cli.add_command(update)
cli.add_command(sites)
cli.add_command(test)
cli.add_command(master)
