"""grunt app * — управління додатками."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import click
import httpx
from rich import box
from rich.table import Table

from grunt_cli.helpers import DEFAULT_API, auth_headers, console, get_site_dir


@click.group()
def app() -> None:
    """Команди для управління Grunt-додатками."""


@app.command("create")
@click.argument("name")
@click.option("--title", default=None, help="Назва додатку")
def app_create(name: str, title: str | None) -> None:
    """Створити структуру нового Grunt-додатку."""
    site_dir = get_site_dir()
    apps_dir = site_dir / "apps"
    app_dir = apps_dir / name

    if app_dir.exists():
        console.print(f"[red]✗[/red] Додаток '{name}' вже існує")
        raise SystemExit(1)

    title = title or name.replace("_", " ").title()

    # Створюємо структуру
    (app_dir / "doctypes").mkdir(parents=True)
    (app_dir / "fixtures").mkdir(parents=True)

    app_json = {
        "name": name,
        "title": title,
        "version": "0.1.0",
        "modules": [],
    }
    (app_dir / "app.json").write_text(json.dumps(app_json, ensure_ascii=False, indent=2))
    (app_dir / "README.md").write_text(f"# {title}\n\nGrunt app: {name}\n")

    console.print(f"[green]✓[/green] Додаток [bold]{name}[/bold] створено у {app_dir}")
    console.print(f"  [dim]{app_dir}/app.json[/dim]")
    console.print(f"  [dim]{app_dir}/doctypes/[/dim]")


@app.command("get")
@click.argument("repo_url")
@click.option("--branch", default=None, help="Гілка для клонування")
def app_get(repo_url: str, branch: str | None) -> None:
    """Завантажити додаток з git-репозиторію."""
    site_dir = get_site_dir()
    apps_dir = site_dir / "apps"
    apps_dir.mkdir(exist_ok=True)

    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd.extend(["--branch", branch])
    cmd.append(repo_url)

    console.print(f"[dim]Клоную {repo_url}...[/dim]")
    result = subprocess.run(cmd, cwd=str(apps_dir))
    if result.returncode != 0:
        console.print("[red]✗[/red] Не вдалося клонувати репозиторій")
        raise SystemExit(1)

    console.print("[green]✓[/green] Додаток завантажено")
    console.print(f"  Тепер встанови його: [cyan]grunt app install <назва>[/cyan]")


@app.command("install")
@click.argument("name")
@click.option("--api", default=DEFAULT_API, show_default=True)
def app_install(name: str, api: str) -> None:
    """Встановити додаток із директорії apps/."""
    site_dir = get_site_dir()
    app_path = site_dir / "apps" / name / "app.json"

    if not app_path.exists():
        console.print(f"[red]✗[/red] Файл app.json не знайдено: {app_path}")
        console.print("  Спочатку завантаж додаток: [cyan]grunt app get <repo_url>[/cyan]")
        raise SystemExit(1)

    app_data = json.loads(app_path.read_text())

    try:
        resp = httpx.post(
            f"{api}/api/v1/apps/",
            headers=auth_headers(),
            json=app_data,
            timeout=10.0,
        )
        if resp.status_code == 409:
            console.print(f"[yellow]![/yellow] Додаток '{name}' вже встановлено")
            return
        resp.raise_for_status()
    except httpx.ConnectError:
        console.print(f"[red]✗[/red] Не можу підключитись до {api}")
        raise SystemExit(1)

    # Оновлюємо grunt.site
    site_file = site_dir / "grunt.site"
    if site_file.exists():
        site_config = json.loads(site_file.read_text())
        installed = site_config.get("installed_apps", [])
        if name not in installed:
            installed.append(name)
            site_config["installed_apps"] = installed
            site_file.write_text(json.dumps(site_config, ensure_ascii=False, indent=2))

    console.print(f"[green]✓[/green] Додаток [bold]{name}[/bold] встановлено")


@app.command("list")
@click.option("--api", default=DEFAULT_API, show_default=True)
def app_list(api: str) -> None:
    """Показати список встановлених додатків."""
    try:
        resp = httpx.get(
            f"{api}/api/v1/apps/",
            headers=auth_headers(),
            timeout=5.0,
        )
        resp.raise_for_status()
        apps = resp.json().get("data", [])
    except httpx.ConnectError:
        console.print(f"[red]✗[/red] Не можу підключитись до {api}")
        raise SystemExit(1)

    if not apps:
        console.print("[dim]Додатків не встановлено[/dim]")
        return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("Назва", style="cyan")
    table.add_column("Заголовок")
    table.add_column("Версія", style="dim")
    table.add_column("Встановлено", style="dim")

    for a in apps:
        table.add_row(
            a["name"],
            a["title"],
            a["version"],
            (a.get("installed_at") or "")[:10],
        )

    console.print(table)


@app.command("export")
@click.argument("name")
@click.option("--api", default=DEFAULT_API, show_default=True)
def app_export(name: str, api: str) -> None:
    """Експортувати DocTypes додатку у JSON-файли."""
    site_dir = get_site_dir()

    try:
        resp = httpx.get(
            f"{api}/api/v1/meta/doctypes",
            headers=auth_headers(),
            timeout=10.0,
        )
        resp.raise_for_status()
        doctypes = resp.json().get("data", [])
    except httpx.ConnectError:
        console.print(f"[red]✗[/red] Не можу підключитись до {api}")
        raise SystemExit(1)

    out_dir = site_dir / "apps" / name / "doctypes"
    out_dir.mkdir(parents=True, exist_ok=True)

    exported = 0
    for dt in doctypes:
        dt_file = out_dir / f"{dt['name']}.json"
        dt_file.write_text(json.dumps(dt, ensure_ascii=False, indent=2))
        exported += 1

    console.print(f"[green]✓[/green] Експортовано {exported} DocType(s) у {out_dir}")
