"""grunt app * — управління додатками."""

from __future__ import annotations

import json
import subprocess

import click
import httpx
from rich import box
from rich.table import Table

from grunt_cli.helpers import (
    DEFAULT_API,
    auth_headers,
    console,
    get_apps_dir,
    get_site_dir,
    resolve_site_api,
)


def _load_app_meta(app_dir: Path) -> dict | None:
    """Завантажує метадані додатку з app.json або grunt_app.py."""

    app_json = app_dir / "app.json"
    if app_json.exists():
        return json.loads(app_json.read_text())

    grunt_app = app_dir / "grunt_app.py"
    if grunt_app.exists():
        ns: dict = {}
        exec(grunt_app.read_text(), ns)
        return {
            "name": ns.get("APP_NAME", app_dir.name),
            "title": ns.get("APP_TITLE", app_dir.name),
            "version": ns.get("APP_VERSION", "0.1.0"),
            "modules": ns.get("MODULES", []),
        }

    return None


@click.group()
def app() -> None:
    """Команди для управління Grunt-додатками."""


@app.command("create")
@click.argument("name")
@click.option("--no-git", is_flag=True, default=False, help="Не ініціалізувати git репозиторій")
@click.option("--dest", default=None, help="Директорія для створення (за замовчуванням: apps/)")
def app_create(name: str, no_git: bool, dest: str | None) -> None:
    """Інтерактивно створити новий Grunt-додаток з повною структурою.

    \b
    Приклади:
      grunt app create my_crm
      grunt app create my_crm --no-git
      grunt app create my_crm --dest /tmp/apps
    """
    from pathlib import Path  # noqa: PLC0415

    from grunt_cli.utils.boilerplate import make_boilerplate  # noqa: PLC0415

    dest_path = Path(dest) if dest else get_apps_dir()
    dest_path.mkdir(parents=True, exist_ok=True)
    make_boilerplate(dest_path, name, no_git=no_git)


@app.command("get")
@click.argument("repo_url")
@click.option("--branch", default=None, help="Гілка для клонування")
def app_get(repo_url: str, branch: str | None) -> None:
    """Завантажити додаток з git-репозиторію."""
    apps_dir = get_apps_dir()
    apps_dir.mkdir(parents=True, exist_ok=True)

    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd.extend(["--branch", branch])
    cmd.append(repo_url)

    console.print(f"[dim]Клоную {repo_url}...[/dim]")
    result = subprocess.run(cmd, cwd=str(apps_dir))
    if result.returncode != 0:
        console.print("[red]✗[/red] Не вдалося клонувати репозиторій")
        raise SystemExit(1)

    # Визначаємо назву завантаженого додатку (остання частина URL без .git)
    app_name = repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
    console.print(f"[green]✓[/green] Додаток [bold]{app_name}[/bold] завантажено до {apps_dir / app_name}")
    console.print(f"  Тепер встанови його: [cyan]grunt app install {app_name} --site localhost[/cyan]")


@app.command("install")
@click.argument("name")
@click.option("--site", default=None, help="Ім'я локального сайту або URL (напр. my-site, localhost, dev.example.com)", metavar="SITE")
def app_install(name: str, site: str | None) -> None:
    """Встановити додаток на сайт.

    \b
    Приклади:
      grunt app install cnap --site my-site     (локальний сайт)
      grunt app install cnap                    (автовизначення)
      grunt app install cnap --site localhost    (через API)
    """
    from grunt_cli.helpers import get_bench_dir

    apps_dir = get_apps_dir()
    app_dir = apps_dir / name

    if not app_dir.exists():
        console.print(f"[red]✗[/red] Додаток '{name}' не знайдено в {apps_dir}")
        console.print("  Спочатку завантаж додаток: [cyan]grunt app get <repo_url>[/cyan]")
        raise SystemExit(1)

    app_data = _load_app_meta(app_dir)
    if app_data is None:
        console.print(f"[red]✗[/red] Не знайдено app.json або grunt_app.py в {app_dir}")
        raise SystemExit(1)

    # Визначаємо site_dir: якщо --site — ім'я локального сайту, шукаємо в bench/sites/
    resolved_site_dir = None
    bench = get_bench_dir()

    if site is not None and bench is not None:
        local_site = bench / "sites" / site
        if local_site.is_dir() and (local_site / "grunt.site").exists():
            resolved_site_dir = local_site

    # Якщо --site не вказано або вказано але це не локальний сайт — шукаємо автоматично
    if resolved_site_dir is None and site is None:
        resolved_site_dir_maybe = get_site_dir()
        if resolved_site_dir_maybe is not None:
            resolved_site_dir = resolved_site_dir_maybe

    # Якщо знайшли локальний сайт — встановлюємо локально (без API)
    if resolved_site_dir is not None:
        site_file = resolved_site_dir / "grunt.site"
        site_config = json.loads(site_file.read_text())
        installed = site_config.get("installed_apps", [])
        if name in installed:
            console.print(f"[yellow]![/yellow] Додаток '{name}' вже встановлено на {resolved_site_dir.name}")
            return
        installed.append(name)
        site_config["installed_apps"] = installed
        site_file.write_text(json.dumps(site_config, ensure_ascii=False, indent=2))
        console.print(f"[green]✓[/green] Додаток [bold]{name}[/bold] встановлено на сайт [cyan]{resolved_site_dir.name}[/cyan]")
        console.print(f"  [dim]Додатки: {', '.join(installed)}[/dim]")
        return

    # Fallback: встановлення через API (remote site)
    if site is not None:
        base_api = resolve_site_api(site)
    else:
        base_api = DEFAULT_API

    try:
        resp = httpx.post(
            f"{base_api}/api/v1/apps/",
            headers=auth_headers(),
            json=app_data,
            timeout=10.0,
        )
        if resp.status_code == 409:
            console.print(f"[yellow]![/yellow] Додаток '{name}' вже встановлено")
            return
        resp.raise_for_status()
    except httpx.ConnectError:
        console.print(f"[red]✗[/red] Не можу підключитись до {base_api}")
        raise SystemExit(1)

    console.print(f"[green]✓[/green] Додаток [bold]{name}[/bold] встановлено на {base_api}")


@app.command("uninstall")
@click.argument("name")
@click.option("--site", default=None, help="Ім'я локального сайту або URL", metavar="SITE")
@click.option("--yes", "-y", is_flag=True, help="Без підтвердження")
def app_uninstall(name: str, site: str | None, yes: bool) -> None:
    """Видалити додаток з сайту.

    \b
    Приклади:
      grunt app uninstall cnap --site dev.local
      grunt app uninstall cnap                     (автовизначення)
      grunt app uninstall cnap --site localhost     (через API)
    """
    from grunt_cli.helpers import get_bench_dir

    if name == "grunt":
        console.print("[red]✗[/red] Не можна видалити системний додаток 'grunt'")
        raise SystemExit(1)

    # Визначаємо site_dir
    resolved_site_dir = None
    bench = get_bench_dir()

    if site is not None and bench is not None:
        local_site = bench / "sites" / site
        if local_site.is_dir() and (local_site / "grunt.site").exists():
            resolved_site_dir = local_site

    if resolved_site_dir is None and site is None:
        resolved_site_dir_maybe = get_site_dir()
        if resolved_site_dir_maybe is not None:
            resolved_site_dir = resolved_site_dir_maybe

    # Локальне видалення
    if resolved_site_dir is not None:
        site_file = resolved_site_dir / "grunt.site"
        site_config = json.loads(site_file.read_text())
        installed = site_config.get("installed_apps", [])
        if name not in installed:
            console.print(f"[yellow]![/yellow] Додаток '{name}' не встановлено на {resolved_site_dir.name}")
            return

        if not yes:
            click.confirm(
                f"Видалити додаток '{name}' з сайту {resolved_site_dir.name}?",
                abort=True,
            )

        installed.remove(name)
        site_config["installed_apps"] = installed
        site_file.write_text(json.dumps(site_config, ensure_ascii=False, indent=2))
        console.print(f"[green]✓[/green] Додаток [bold]{name}[/bold] видалено з сайту [cyan]{resolved_site_dir.name}[/cyan]")
        console.print(f"  [dim]Додатки: {', '.join(installed)}[/dim]")
        console.print(f"  [dim]Файли додатку залишено у apps/{name}/[/dim]")
        return

    # Fallback: видалення через API
    if site is not None:
        base_api = resolve_site_api(site)
    else:
        base_api = DEFAULT_API

    if not yes:
        click.confirm(f"Видалити додаток '{name}' з {base_api}?", abort=True)

    try:
        resp = httpx.delete(
            f"{base_api}/api/v1/apps/{name}",
            headers=auth_headers(),
            timeout=10.0,
        )
        if resp.status_code == 404:
            console.print(f"[yellow]![/yellow] Додаток '{name}' не знайдено")
            return
        resp.raise_for_status()
    except httpx.ConnectError:
        console.print(f"[red]✗[/red] Не можу підключитись до {base_api}")
        raise SystemExit(1)

    console.print(f"[green]✓[/green] Додаток [bold]{name}[/bold] видалено з {base_api}")


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

    out_dir = get_apps_dir() / name / "doctypes"
    out_dir.mkdir(parents=True, exist_ok=True)

    exported = 0
    for dt in doctypes:
        dt_file = out_dir / f"{dt['name']}.json"
        dt_file.write_text(json.dumps(dt, ensure_ascii=False, indent=2))
        exported += 1

    console.print(f"[green]✓[/green] Експортовано {exported} DocType(s) у {out_dir}")
