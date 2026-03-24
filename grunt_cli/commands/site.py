"""grunt site — управління сайтами."""

from __future__ import annotations

import json
from pathlib import Path

import click

from grunt_cli.helpers import console, get_bench_dir


@click.group()
def site() -> None:
    """Управління сайтами."""


@site.command("list")
def site_list() -> None:
    """Показує список сайтів у bench."""
    bench = get_bench_dir()
    if bench is None:
        console.print("[red]✗[/red] Bench-структуру не знайдено.")
        raise SystemExit(1)

    sites_dir = bench / "sites"
    if not sites_dir.is_dir():
        console.print("[yellow]Директорія sites/ не знайдена[/yellow]")
        return

    found = False
    for site_path in sorted(sites_dir.iterdir()):
        marker = site_path / "grunt.site"
        if not site_path.is_dir() or not marker.exists():
            continue

        found = True
        # Читаємо grunt.site для інформації
        try:
            info = json.loads(marker.read_text())
        except (json.JSONDecodeError, OSError):
            info = {}

        apps = info.get("installed_apps", [])
        db_file = site_path / "grunt.db"
        has_db = db_file.exists()
        env_file = site_path / ".env"
        has_env = env_file.exists()

        console.print(f"  [bold cyan]{site_path.name}[/bold cyan]")
        console.print(f"    Шлях:     {site_path}")
        if apps:
            console.print(f"    Додатки:  {', '.join(apps)}")
        console.print(f"    БД:       {'✓' if has_db else '✗'}")
        if has_env:
            console.print(f"    .env:     ✓")
        console.print()

    if not found:
        console.print("[dim]Сайтів не знайдено. Створіть: [cyan]grunt init <назва>[/cyan][/dim]")
