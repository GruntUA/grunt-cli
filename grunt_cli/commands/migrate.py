"""grunt migrate — синхронізувати схему БД та метадані DocType з JSON-файлів."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import click

from grunt_cli.helpers import console, get_bench_dir, get_venv_grunt


def _resolve_framework_dir() -> Path | None:
    """Директорія apps/grunt (де живуть alembic.ini і .venv)."""
    bench_dir = get_bench_dir()
    if bench_dir is not None:
        return bench_dir / "apps" / "grunt"
    if (Path.cwd() / "alembic.ini").exists():
        return Path.cwd()
    return None


@click.command("migrate")
@click.option("--site", "site_name", default=None, help="Цільовий сайт (без параметра: всі сайти)")
@click.option("--dry-run", is_flag=True, help="Показати SQL без виконання (для DocType таблиць)")
def migrate(site_name: str | None, dry_run: bool) -> None:
    """Синхронізувати схему БД та метадані DocType з JSON-файлів.

    Виконує два кроки:
      1. Alembic-міграції для core/системних таблиць (структурні зміни, які
         не можна вивести автоматично з DocType JSON — напр. зміна PK).
         Це єдине місце, звідки вони запускаються.
      2. `grunt migrate` у venv проекту — синхронізація DocType-таблиць
         і fixtures. Реалізація цієї частини живе тільки в самому
         фреймворку (apps/grunt) — тут лише делегування, без власної копії.
    """
    framework_dir = _resolve_framework_dir()
    if framework_dir is None:
        console.print("[red]✗[/red] apps/grunt не знайдено. Запустіть у папці bench-проекту.")
        raise SystemExit(1)

    if site_name:
        console.print(f"[dim]Сайт: {site_name}[/dim]\n")
    else:
        console.print("[dim]Сайти: всі[/dim]\n")

    # ── 1. Alembic міграції (core/системні таблиці) ────────────────────
    console.print("[bold cyan][1/2] Alembic міграції[/bold cyan]")

    alembic_ini = framework_dir / "alembic.ini"
    if not alembic_ini.exists():
        console.print("[red]✗[/red] Не знайдено alembic.ini у framework директорії")
        raise SystemExit(1)

    alembic_bin = str(framework_dir / ".venv" / "bin" / "alembic")
    if not Path(alembic_bin).exists():
        alembic_bin = shutil.which("alembic") or "alembic"

    result = subprocess.run(
        [alembic_bin, "-c", str(alembic_ini), "upgrade", "head"],
        cwd=str(framework_dir),
    )
    if result.returncode != 0:
        console.print("[red]✗[/red] Alembic міграція завершилась з помилкою")
        sys.exit(result.returncode)

    console.print("[green]✓[/green] Alembic міграції застосовано\n")

    # ── 2. DocType/fixtures — делеговано до venv проекту ───────────────
    console.print("[bold cyan][2/2] Синхронізація DocType метаданих[/bold cyan]")

    grunt_bin = get_venv_grunt()
    if not grunt_bin:
        console.print("[red]✗[/red] Backend venv не знайдено (apps/grunt/.venv).")
        raise SystemExit(1)

    cmd = [grunt_bin, "migrate"]
    if site_name:
        cmd.extend(["--site", site_name])
    if dry_run:
        cmd.append("--dry-run")

    result = subprocess.run(cmd, cwd=str(framework_dir))
    sys.exit(result.returncode)
