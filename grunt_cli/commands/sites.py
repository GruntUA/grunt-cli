"""grunt sites — управління сайтами."""

from __future__ import annotations

import json
import secrets
import shutil

import click

from grunt_cli.helpers import console, get_bench_dir, get_site_dir, run_mise


@click.group()
def sites() -> None:
    """Управління сайтами (list, new, use, drop)."""


# ---------------------------------------------------------------------------
# grunt sites list
# ---------------------------------------------------------------------------

@sites.command("list")
def sites_list() -> None:
    """Показує список сайтів."""
    bench = get_bench_dir()

    if bench is not None:
        _list_bench_sites(bench)
        return

    site_dir = get_site_dir()
    if site_dir is not None:
        console.print(f"  [bold cyan]{site_dir.name}[/bold cyan]  (flat)")
        console.print(f"    Шлях: {site_dir}")
        _print_site_info(site_dir)
        return

    console.print("[dim]Сайтів не знайдено.[/dim]")
    console.print("  [cyan]grunt install <name>[/cyan]    створити flat-сайт")
    console.print("  [cyan]grunt init <name>[/cyan]       створити bench")


# ---------------------------------------------------------------------------
# grunt sites new <name>
# ---------------------------------------------------------------------------

@sites.command("new")
@click.argument("name")
@click.option("--db-url", default=None, help="DATABASE_URL (за замовчуванням SQLite)")
@click.option("--no-migrate", is_flag=True, help="Пропустити міграції БД")
def sites_new(name: str, db_url: str | None, no_migrate: bool) -> None:
    """Створює новий сайт у bench/sites/."""
    bench_dir = get_bench_dir()
    if bench_dir is None:
        console.print(
            "[red]✗[/red] Bench-структуру не знайдено. "
            "Спочатку створи bench: [cyan]grunt init <name>[/cyan]"
        )
        raise SystemExit(1)

    sites_dir = bench_dir / "sites"
    site_dir = sites_dir / name

    if site_dir.exists():
        console.print(f"[red]✗[/red] Сайт '{name}' вже існує: {site_dir}")
        raise SystemExit(1)

    site_dir.mkdir(parents=True)

    # grunt.site
    site_config = {
        "framework_path": "../../apps/grunt",
        "apps_path": "../../apps",
        "installed_apps": ["grunt"],
    }
    (site_dir / "grunt.site").write_text(json.dumps(site_config, ensure_ascii=False, indent=2))

    # .env
    secret_key = secrets.token_hex(32)
    database_url = db_url or "sqlite+aiosqlite:///./grunt.db"
    env_content = (
        "DEBUG=true\n"
        f"DATABASE_URL={database_url}\n"
        f"SECRET_KEY={secret_key}\n"
    )
    (site_dir / ".env").write_text(env_content)
    console.print(f"[green]✓[/green] Сайт '{name}' створено")

    # Міграції
    if not no_migrate:
        grunt_dir = bench_dir / "apps" / "grunt"
        console.print("[dim]Застосовую міграції...[/dim]")
        run_mise(
            grunt_dir, 
            "db:migrate", 
            env={"DOTENV_PATH": str(site_dir / ".env")}
        )

    # Встановлюємо як активний
    (sites_dir / "currentsite.txt").write_text(name)
    console.print(f"[green]✓[/green] Активний сайт: {name}")

    console.print()
    console.print(f"[bold green]✅ Сайт '{name}' готовий[/bold green]")
    console.print()
    console.print("Наступні кроки:")
    console.print("  [cyan]grunt serve[/cyan]           запустити сервери")
    console.print("  [cyan]grunt init[/cyan]            створити адміністратора")


# ---------------------------------------------------------------------------
# grunt sites use <name>
# ---------------------------------------------------------------------------

@sites.command("use")
@click.argument("site_name")
def sites_use(site_name: str) -> None:
    """Встановлює активний сайт (записує в currentsite.txt)."""
    bench_dir = get_bench_dir()
    if bench_dir is None:
        console.print("[red]✗[/red] Bench-структуру не знайдено.")
        raise SystemExit(1)

    site_dir = bench_dir / "sites" / site_name
    if not (site_dir / "grunt.site").exists():
        console.print(f"[red]✗[/red] Сайт '{site_name}' не знайдено в {bench_dir / 'sites'}")
        raise SystemExit(1)

    (bench_dir / "sites" / "currentsite.txt").write_text(site_name)
    console.print(f"[green]✓[/green] Активний сайт: [bold]{site_name}[/bold]")


# ---------------------------------------------------------------------------
# grunt sites drop <name>
# ---------------------------------------------------------------------------

@sites.command("drop")
@click.argument("name")
@click.option("--force", is_flag=True, help="Пропустити підтвердження")
def sites_drop(name: str, force: bool) -> None:
    """Видаляє сайт з bench/sites/ (включно з базою даних)."""
    bench_dir = get_bench_dir()
    if bench_dir is None:
        console.print("[red]✗[/red] Bench-структуру не знайдено.")
        raise SystemExit(1)

    site_dir = bench_dir / "sites" / name

    if not site_dir.exists() or not (site_dir / "grunt.site").exists():
        console.print(f"[red]✗[/red] Сайт '{name}' не знайдено")
        raise SystemExit(1)

    if not force and not click.confirm(
        f"⚠️  Сайт '{name}' та його база даних будуть видалені назавжди. Продовжити?"
    ):
        console.print("[dim]Скасовано[/dim]")
        return

    shutil.rmtree(site_dir)
    console.print(f"[green]✓[/green] Сайт '{name}' видалено")

    current_file = bench_dir / "sites" / "currentsite.txt"
    if current_file.exists() and current_file.read_text().strip() == name:
        current_file.write_text("")
        console.print("[dim]Активний сайт скинуто[/dim]")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _list_bench_sites(bench) -> None:
    sites_dir = bench / "sites"
    if not sites_dir.is_dir():
        console.print("[yellow]Директорія sites/ не знайдена[/yellow]")
        return

    current_file = sites_dir / "currentsite.txt"
    active = current_file.read_text().strip() if current_file.exists() else ""

    found = False
    for site_path in sorted(sites_dir.iterdir()):
        if not site_path.is_dir() or not (site_path / "grunt.site").exists():
            continue

        found = True
        is_active = site_path.name == active
        marker = "[bold green]★[/bold green] " if is_active else "  "
        console.print(f"{marker}[bold cyan]{site_path.name}[/bold cyan]")
        console.print(f"    Шлях: {site_path}")
        _print_site_info(site_path)
        console.print()

    if not found:
        console.print("[dim]Сайтів не знайдено. Створи: [cyan]grunt sites new <name>[/cyan][/dim]")


def _print_site_info(site_path) -> None:
    try:
        info = json.loads((site_path / "grunt.site").read_text())
    except (json.JSONDecodeError, OSError):
        info = {}

    apps = info.get("installed_apps", [])
    if apps:
        console.print(f"    Додатки: {', '.join(apps)}")

    db_file = site_path / "grunt.db"
    console.print(f"    БД: {'✓' if db_file.exists() else '✗'}")

    if (site_path / ".env").exists():
        console.print("    .env: ✓")
