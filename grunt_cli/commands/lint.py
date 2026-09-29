"""grunt lint — перевірка коду (ruff + vue-tsc)."""

from __future__ import annotations

import subprocess
import sys

import click

from grunt_cli.helpers import console, get_venv_grunt


@click.command("lint")
@click.option("--fix", is_flag=True, help="Автоматично виправити (ruff --fix + ruff format)")
@click.option("--py", "only_py", is_flag=True, help="Тільки Python")
@click.option("--js", "only_js", is_flag=True, help="Тільки TypeScript/Vue")
@click.option("--path", default=None, help="Корінь проєкту або bench (авто-пошук за замовчуванням)")
@click.option(
    "--app",
    "apps",
    multiple=True,
    metavar="APP",
    help="Додаток для перевірки (можна повторити). Активує bench-режим.",
)
def lint(fix: bool, only_py: bool, only_js: bool, path: str | None, apps: tuple[str, ...]) -> None:
    """Перевірити код: ruff (Python) + vue-tsc (TS/Vue).

    Тонка обгортка над `grunt lint` у venv проекту (apps/grunt/.venv) —
    реалізація живе тільки там, тут лише делегування.
    """
    grunt_bin = get_venv_grunt()
    if not grunt_bin:
        console.print(
            "[red]✗[/red] Backend venv не знайдено (apps/grunt/.venv). "
            "Запустіть команду у папці bench-проекту."
        )
        raise SystemExit(1)

    cmd = [grunt_bin, "lint"]
    if fix:
        cmd.append("--fix")
    if only_py:
        cmd.append("--py")
    if only_js:
        cmd.append("--js")
    if path:
        cmd.extend(["--path", path])
    for app in apps:
        cmd.extend(["--app", app])

    result = subprocess.run(cmd)
    sys.exit(result.returncode)
