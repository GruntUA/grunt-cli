"""grunt test — запуск тестів."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

from grunt_cli.helpers import console


@click.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def test(args: tuple[str, ...]) -> None:
    """Запускає тести grunt-cli через pytest.

    \b
    Приклади:
      grunt test                    всі тести
      grunt test -v                 verbose
      grunt test tests/test_helpers.py   конкретний файл
      grunt test -k "test_resolve"  фільтр по назві
    """
    cli_dir = Path(__file__).resolve().parent.parent.parent
    tests_dir = cli_dir / "tests"

    if not tests_dir.is_dir():
        console.print("[red]✗[/red] Директорію tests/ не знайдено")
        raise SystemExit(1)

    cmd = [sys.executable, "-m", "pytest", *args]
    result = subprocess.run(cmd, cwd=str(cli_dir))
    raise SystemExit(result.returncode)
