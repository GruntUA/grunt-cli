"""grunt app * — управління додатками."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import click
from rich import box
from rich.table import Table

from grunt_cli.helpers import (
    console,
    get_apps_dir,
    get_bench_dir,
    get_current_site,
    venv_delegate,
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
@click.option("--site", default=None, help="Ім'я сайту (за замовчуванням: автовизначення)", metavar="SITE")
def app_install(name: str, site: str | None) -> None:
    """Встановити додаток: DocTypes, fixtures, workspace, after_install.

    \b
    Приклади:
      grunt app install int_map
      grunt app install int_map --site my-site
    """
    import os  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    from grunt_cli.helpers import get_bench_dir  # noqa: PLC0415

    bench = get_bench_dir()
    if bench is None:
        console.print("[red]✗[/red] Bench не знайдено. Запустіть у папці проєкту.")
        raise SystemExit(1)

    apps_dir = bench / "apps"
    app_dir = apps_dir / name
    if not app_dir.exists():
        console.print(f"[red]✗[/red] Додаток '{name}' не знайдено в {apps_dir}")
        console.print("  Спочатку завантаж додаток: [cyan]grunt app get <repo_url>[/cyan]")
        raise SystemExit(1)

    backend_dir = bench / "apps" / "grunt" / "backend"
    if not backend_dir.exists():
        console.print(f"[red]✗[/red] Grunt framework не знайдено: {backend_dir}")
        raise SystemExit(1)

    # Знаходимо Python у venv bench
    python_exe = str(bench / ".venv" / "bin" / "python")
    if not Path(python_exe).exists():
        # Fallback 1: .venv у самому додатку grunt (framework)
        python_exe = str(apps_dir / "grunt" / ".venv" / "bin" / "python")
    
    if not Path(python_exe).exists():
        python_exe = sys.executable

    # Знаходимо site dir для cwd
    from grunt_cli.commands.shell import _resolve_site_dir  # noqa: PLC0415
    cwd = _resolve_site_dir(bench, site)

    env = {**os.environ, "PYTHONPATH": str(backend_dir)}
    env_file = Path(cwd) / ".env"
    if env_file.exists():
        env["DOTENV_PATH"] = str(env_file)

    site_arg = f", site={site!r}" if site else ""
    startup = (
        f"import asyncio; "
        f"from grunt.cli.app import _do_install; "
        f"asyncio.run(_do_install({name!r}{site_arg}))"
    )

    result = subprocess.run([python_exe, "-c", startup], env=env, cwd=cwd)
    raise SystemExit(result.returncode)


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
        from grunt_cli.helpers import get_current_site
        resolved_site_dir_maybe = get_current_site()
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

    # Fallback: no local site found — cannot uninstall without site info
    console.print("[red]✗[/red] Сайт не знайдено. Вкажи [cyan]--site <name>[/cyan] або запустіть у папці проекту.")
    raise SystemExit(1)


@app.command("list")
@click.option("--site", default=None, help="Назва сайту")
def app_list(site: str | None) -> None:
    """Показати список встановлених додатків."""
    rc = venv_delegate("app", "list", site=site)
    if rc == -1:
        console.print("[red]✗[/red] Backend CLI не знайдено. Запустіть у папці проекту.")
    raise SystemExit(0 if rc in (0, -1) else rc)


@app.command("export")
@click.argument("name")
def app_export(name: str) -> None:
    """Експортувати DocTypes додатку у JSON-файли (читає з диску, сервер не потрібен)."""
    bench = get_bench_dir()
    if bench is None:
        console.print("[red]✗[/red] Bench не знайдено")
        raise SystemExit(1)

    apps_dir = bench / "apps"
    app_pkg = apps_dir / name
    if not app_pkg.exists():
        console.print(f"[red]✗[/red] Додаток '{name}' не знайдено в {apps_dir}")
        raise SystemExit(1)

    # Find all <Name>.json files in */doctypes/*/*/*.json pattern
    dt_files = list(app_pkg.rglob("doctypes/*/*.json"))
    if not dt_files:
        console.print(f"[yellow]![/yellow] DocType JSON не знайдено в {app_pkg}")
        return

    out_dir = app_pkg / "exported_doctypes"
    out_dir.mkdir(parents=True, exist_ok=True)

    exported = 0
    for dt_file in dt_files:
        dest = out_dir / dt_file.name
        dest.write_bytes(dt_file.read_bytes())
        exported += 1

    console.print(f"[green]✓[/green] Експортовано {exported} DocType(s) у {out_dir}")
