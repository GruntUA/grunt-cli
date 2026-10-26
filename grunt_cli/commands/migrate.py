"""grunt migrate — синхронізувати схему БД та метадані DocType з JSON-файлів."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

from grunt_cli.helpers import console, get_bench_dir, get_venv_grunt


def _resolve_framework_dir() -> Path | None:
    """Директорія apps/grunt (де живе .venv)."""
    bench_dir = get_bench_dir()
    if bench_dir is not None:
        return bench_dir / "apps" / "grunt"
    if (Path.cwd() / "alembic.ini").exists():
        return Path.cwd()
    return None


@click.command("migrate")
@click.option("--site", "site_name", default=None, help="Цільовий сайт (без параметра: всі сайти)")
@click.option("--dry-run", is_flag=True, help="Показати SQL без виконання (для DocType таблиць)")
@click.option("--no-alembic", is_flag=True, help="Пропустити Alembic-міграції")
def migrate(site_name: str | None, dry_run: bool, no_alembic: bool) -> None:
    """Синхронізувати схему БД та метадані DocType з JSON-файлів.

    Делегує `grunt migrate` у venv проекту: для кожного сайту — Alembic
    (stamp для нового сайту, upgrade для існуючого), DocType-таблиці і
    fixtures. Реалізація живе тільки у фреймворку (apps/grunt) — тут
    власного Alembic-кроку немає: він запускав би міграції вдруге і лише
    для активного сайту, ігноруючи --site.
    """
    framework_dir = _resolve_framework_dir()
    if framework_dir is None:
        console.print("[red]✗[/red] apps/grunt не знайдено. Запустіть у папці bench-проекту.")
        raise SystemExit(1)

    grunt_bin = get_venv_grunt()
    if not grunt_bin:
        console.print("[red]✗[/red] Backend venv не знайдено (apps/grunt/.venv).")
        raise SystemExit(1)

    cmd = [*grunt_bin, "migrate"]
    if site_name:
        cmd.extend(["--site", site_name])
    if dry_run:
        cmd.append("--dry-run")
    if no_alembic:
        cmd.append("--no-alembic")

    result = subprocess.run(cmd, cwd=str(framework_dir))
    sys.exit(result.returncode)
