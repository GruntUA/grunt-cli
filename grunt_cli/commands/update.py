"""grunt update — оновлення CLI, фреймворку та додатків через git."""

from __future__ import annotations

import subprocess
from pathlib import Path

import click

from grunt_cli.helpers import (
    console,
    find_uv,
    get_bench_dir,
    get_site_dir,
    get_current_site,
    run_mise,
)


def _git_pull(path: Path, label: str) -> bool:
    """Виконує git pull у вказаній директорії. Повертає True якщо успішно."""
    if not (path / ".git").exists():
        console.print(f"  [yellow]⚠[/yellow]  {label}: не є git-репозиторієм, пропускаю")
        return False

    # Перевіряємо поточну гілку
    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(path),
        capture_output=True,
        text=True,
    )
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "?"

    # Зберігаємо поточний коміт для порівняння
    old_hash = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(path),
        capture_output=True,
        text=True,
    ).stdout.strip()

    console.print(f"  [dim]Оновлюю {label} ({branch})...[/dim]")

    result = subprocess.run(
        ["git", "pull", "--rebase", "--autostash"],
        cwd=str(path),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "could not read Username" in stderr or "Authentication failed" in stderr:
            console.print(f"  [yellow]⚠[/yellow]  {label}: немає доступу до GitHub")
            console.print("    [dim]Налаштуйте SSH-ключ або git credentials:[/dim]")
            console.print("    [dim]  ssh-keygen -t ed25519 && ssh-add ~/.ssh/id_ed25519[/dim]")
            console.print("    [dim]  git remote set-url origin git@github.com:ORG/REPO.git[/dim]")
        else:
            console.print(f"  [red]✗[/red] {label}: помилка git pull")
            if stderr:
                console.print(f"    [dim]{stderr}[/dim]")
        return False

    new_hash = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(path),
        capture_output=True,
        text=True,
    ).stdout.strip()

    if old_hash == new_hash:
        console.print(f"  [green]✓[/green] {label}: вже актуальний ({old_hash})")
    else:
        console.print(f"  [green]✓[/green] {label}: оновлено {old_hash} → {new_hash}")

        # Відображення статистики змін
        diff_result = subprocess.run(
            ["git", "diff", "--stat", f"{old_hash}..{new_hash}"],
            cwd=str(path),
            capture_output=True,
            text=True,
        )
        if diff_result.returncode == 0:
            stats = diff_result.stdout.strip()
            if stats:
                import re  # noqa: PLC0415
                for line in stats.splitlines():
                    line = line.strip()
                    if "changed" in line and ("insertion" in line or "deletion" in line):
                        # Підсвічуємо підсумок: (+) зеленим, (-) червоним
                        line = line.replace("(+)", "[green](+)[/green]")
                        line = line.replace("(-)", "[red](-)[/red]")
                        console.print(f"    [cyan]{line}[/cyan]")
                    else:
                        # Підсвічуємо гістограму: + зеленим, - червоним
                        if "|" in line:
                            path_part, stats_part = line.rsplit("|", 1)
                            stats_part = re.sub(r"(\++)", r"[green]\1[/green]", stats_part)
                            stats_part = re.sub(r"(-+)", r"[red]\1[/red]", stats_part)
                            line = f"{path_part}|{stats_part}"
                        console.print(f"    [dim]{line}[/dim]")

    return True


def _install_deps(path: Path, label: str) -> None:
    """Встановлює залежності через mise."""
    console.print(f"  [dim]Оновлюю рантайми для {label}...[/dim]")
    run_mise(path, "install")

    mise_toml = path / "mise.toml"
    if mise_toml.exists():
        import tomllib  # noqa: PLC0415
        with mise_toml.open("rb") as f:
            tasks = tomllib.load(f).get("tasks", {})
        if "deps" in tasks:
            console.print(f"  [dim]Встановлюю пакети для {label} (mise run deps)...[/dim]")
            run_mise(path, "deps")


def _update_runtimes() -> None:
    """Оновити системні рантайми (Python, Node.js тощо) через mise."""
    import shutil  # noqa: PLC0415
    
    # Спочатку шукаємо mise у поточному середовищі
    mise_bin = shutil.which("mise")
    if not mise_bin:
        console.print("  [yellow]⚠[/yellow]  mise не знайдено, пропускаю оновлення рантаймів")
        return
    
    bench = get_bench_dir()
    if bench:
        config_file = bench / "apps" / "grunt" / "mise.toml"
        if config_file.exists():
            console.print("  [dim]Оновлюю системні рантайми (Python, Node.js тощо)...[/dim]")
            result = subprocess.run(
                [mise_bin, "install"],
                cwd=str(bench),
                check=False
            )
            if result.returncode == 0:
                console.print("  [green]✓[/green] Системні рантайми оновлені")
            else:
                console.print("  [yellow]⚠[/yellow]  Оновлення рантаймів завершилось з помилкою")
            return
    
    site = get_site_dir()
    if site and (site / "mise.toml").exists():
        console.print("  [dim]Оновлюю системні рантайми (Python, Node.js тощо)...[/dim]")
        result = subprocess.run(
            [mise_bin, "install"],
            cwd=str(site),
            check=False
        )
        if result.returncode == 0:
            console.print("  [green]✓[/green] Системні рантайми оновлені")
        else:
            console.print("  [yellow]⚠[/yellow]  Оновлення рантаймів завершилось з помилкою")
    else:
        console.print("  [dim]mise.toml не знайдено[/dim]")


def _update_python_packages() -> None:
    """Оновити Python пакети (uv sync --upgrade або pip)."""
    import shutil  # noqa: PLC0415
    import sys  # noqa: PLC0415
    import os  # noqa: PLC0415
    
    # Перевіряємо наявність uv
    uv_bin = find_uv()
    if uv_bin:
        console.print("  [dim]Оновлюю Python пакети (uv sync --upgrade)...[/dim]")
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        app_dir = _find_apps_dir()
        cwd_dir = str(app_dir / "grunt") if app_dir else None
        if cwd_dir:
            env["PWD"] = cwd_dir
        result = subprocess.run([uv_bin, "sync", "--upgrade"], cwd=cwd_dir, check=False, env=env)
        if result.returncode != 0:
            console.print("  [yellow]⚠[/yellow]  uv sync --upgrade завершився з помилкою")
        else:
            console.print("  [green]✓[/green] Python пакети оновлені")
        return
    
    # Fallback на pip
    pip_bin = shutil.which("pip") or shutil.which("pip3")
    if pip_bin:
        console.print("  [dim]uv не знайдено, оновлюю через pip...[/dim]")
        result = subprocess.run(
            [pip_bin, "install", "--upgrade", "pip"],
            check=False
        )
        if result.returncode != 0:
            console.print("  [yellow]⚠[/yellow]  pip update завершився з помилкою")
        else:
            console.print("  [green]✓[/green] Python пакети оновлені")
    else:
        console.print("  [yellow]⚠[/yellow]  Ні uv, ні pip не знайдено")


def _run_npm_install(app_dir: Path) -> None:
    """Встановити npm пакети."""
    import shutil  # noqa: PLC0415
    
    mise = shutil.which("mise")
    if mise:
        npm_run = [mise, "exec", "--", "npm"]
    else:
        npm = shutil.which("npm")
        if not npm:
            console.print("  [yellow]⚠[/yellow]  npm не знайдено")
            return
        npm_run = [npm]
    
    console.print(f"  [dim]Встановлюю npm пакети ({app_dir.name})...[/dim]")
    result = subprocess.run([*npm_run, "install"], cwd=str(app_dir), check=False)
    
    if result.returncode != 0:
        # Retry after cleaning node_modules
        nm = app_dir / "node_modules"
        if nm.exists():
            console.print("  [dim]Очищення node_modules, повторна спроба...[/dim]")
            import shutil as _shutil  # noqa: PLC0415
            _shutil.rmtree(nm)
            result = subprocess.run([*npm_run, "install"], cwd=str(app_dir), check=False)
    
    if result.returncode == 0:
        subprocess.run([*npm_run, "audit", "fix"], cwd=str(app_dir), check=False)
        console.print("  [green]✓[/green] npm пакети встановлені")
    else:
        console.print("  [yellow]⚠[/yellow]  npm install завершився з помилкою")


def _run_migrations(site: str | None) -> None:
    """Запустити міграції БД."""
    site_dir = get_current_site()
    if site_dir is None:
        console.print("  [yellow]⚠[/yellow]  grunt.site не знайдено")
        return
    
    console.print(f"  [dim]Запускаю міграції БД{f' для {site}' if site else ''}...[/dim]")
    
    # Визначаємо директорію для міграцій
    from grunt_cli.helpers import get_apps_dir  # noqa: PLC0415
    try:
        apps_dir = get_apps_dir()
    except SystemExit:
        console.print("  [yellow]⚠[/yellow]  Grunt backend не знайдено (bench не визначено)")
        return
    
    backend_dir = apps_dir / "grunt" / "backend"
    if not backend_dir.exists():
        console.print(f"  [yellow]⚠[/yellow]  Grunt backend не знайдено: {backend_dir}")
        return
    
    # Запускаємо міграції через mise
    if run_mise(apps_dir / "grunt", "db:migrate", env={"SITE_NAME": site or site_dir.name}):
        console.print("  [green]✓[/green] Міграції завершені")
    else:
        console.print("  [yellow]⚠[/yellow]  Міграції завершилися з помилкою")


def _find_bench_dir() -> Path | None:
    """Шукає кореневу директорію bench-проєкту."""
    return get_bench_dir()


def _find_apps_dir() -> Path | None:
    """Повертає директорію apps/."""
    bench = get_bench_dir()
    if bench:
        return bench / "apps"
    site = get_site_dir()
    if site and (site / "apps").is_dir():
        return site / "apps"
    return None


def _get_cli_dir() -> Path | None:
    """Повертає директорію grunt-cli (editable install)."""
    # Спочатку перевіряємо стандартне розташування
    default_dir = Path.home() / ".grunt-cli"
    if (default_dir / ".git").exists():
        return default_dir

    # Fallback: шукаємо через uv
    uv_bin = find_uv()
    if uv_bin:
        result = subprocess.run(
            [uv_bin, "pip", "show", "grunt-cli"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
    else:
        return None

    for line in result.stdout.splitlines():
        if line.startswith("Editable project location:"):
            path = Path(line.split(":", 1)[1].strip())
            if path.exists():
                return path
    return None


@click.command()
@click.option("--cli", "update_cli", is_flag=True, default=False, help="Оновити тільки CLI")
@click.option("--framework", "update_framework", is_flag=True, default=False,
              help="Оновити тільки фреймворк")
@click.option("--apps", "update_apps", is_flag=True, default=False,
              help="Оновити тільки додатки")
@click.option("--deps", "update_deps", is_flag=True, default=False,
              help="Оновити системні залежності (Python, Node.js тощо)")
@click.option("--skip-packages", is_flag=True, default=False,
              help="Не оновлювати Python пакети")
@click.option("--skip-npm", is_flag=True, default=False,
              help="Не встановлювати npm пакети")
@click.option("--skip-migrate", is_flag=True, default=False,
              help="Не запускати міграції БД")
@click.option("--no-deps", is_flag=True, default=False,
              help="Не встановлювати залежності після оновлення")
@click.option("--site", default=None, help="Назва сайту (для migrate)")
def update(update_cli: bool, update_framework: bool, update_apps: bool, 
           update_deps: bool, skip_packages: bool, skip_npm: bool, skip_migrate: bool, 
           no_deps: bool, site: str | None) -> None:
    """Оновити CLI, фреймворк, додатки, пакети та схему БД.

    \b
    Послідовність:
      1. git pull --rebase для CLI, фреймворку та додатків
      2. mise install (системні залежності: Python, Node.js тощо)
      3. uv sync --upgrade (Python пакети)
      4. npm install
      5. grunt migrate (міграція БД)

    \b
    Без прапорців оновлює все.
    З прапорцями — тільки вказані компоненти.

    \b
    Приклади:
      grunt update                  оновити все
      grunt update --deps           оновити тільки системні залежності
      grunt update --apps           тільки додатки + пакети + міграції
      grunt update --skip-migrate   без міграцій БД
      grunt update --no-deps        без перевстановлення залежностей
    """
    # Якщо жоден прапорець не вказано — оновлюємо все
    update_all = not (update_cli or update_framework or update_apps or update_deps)

    console.print("[bold]⚡ Grunt Update[/bold]")
    console.print()

    updated_something = False

    # ── 1. CLI ──────────────────────────────────────────────────────
    if update_all or update_cli:
        console.print("[bold cyan]CLI[/bold cyan]")
        cli_dir = _get_cli_dir()
        if cli_dir is None:
            console.print("  [yellow]⚠[/yellow]  grunt-cli не встановлений як editable, пропускаю")
        else:
            _git_pull(cli_dir, "grunt-cli")
            if not no_deps:
                _install_deps(cli_dir, "grunt-cli")
            updated_something = True
        console.print()

    # ── 2. Framework ────────────────────────────────────────────────
    if update_all or update_framework:
        console.print("[bold cyan]Фреймворк[/bold cyan]")
        apps_dir = _find_apps_dir()
        framework_dir = apps_dir / "grunt" if apps_dir else None

        if framework_dir is None or not framework_dir.exists():
            console.print("  [yellow]⚠[/yellow]  Grunt framework не знайдено")
        else:
            _git_pull(framework_dir, "grunt")
            if not no_deps:
                _install_deps(framework_dir, "grunt")
            updated_something = True
        console.print()

    # ── 3. Apps ─────────────────────────────────────────────────────
    if update_all or update_apps:
        console.print("[bold cyan]Додатки[/bold cyan]")
        apps_dir = _find_apps_dir()

        if apps_dir is None or not apps_dir.exists():
            console.print("  [dim]Директорію додатків не знайдено[/dim]")
        else:
            app_dirs = sorted(
                p for p in apps_dir.iterdir()
                if p.is_dir() and p.name != "grunt" and (p / ".git").exists()
            )

            if not app_dirs:
                console.print("  [dim]Немає додатків з git-репозиторієм для оновлення[/dim]")
            else:
                for app_dir in app_dirs:
                    _git_pull(app_dir, app_dir.name)
                    if not no_deps:
                        _install_deps(app_dir, app_dir.name)
                    updated_something = True
        console.print()

    # ── 4. Системні залежності (рантайми) ────────────────────────
    if update_all or update_deps:
        console.print("[bold cyan]Системні залежності[/bold cyan]")
        _update_runtimes()
        updated_something = True
        console.print()

    # ── 5. Python пакети ────────────────────────────────────────────
    if not skip_packages:
        console.print("[bold cyan]Python пакети[/bold cyan]")
        _update_python_packages()
        updated_something = True
        console.print()
    else:
        console.print("[dim]Python пакети пропущено (--skip-packages)[/dim]")
        console.print()

    # ── 6. npm пакети ──────────────────────────────────────────────
    if not skip_npm:
        console.print("[bold cyan]npm пакети[/bold cyan]")
        apps_dir = _find_apps_dir()
        if apps_dir and (apps_dir / "grunt").exists():
            _run_npm_install(apps_dir / "grunt")
            updated_something = True
        else:
            console.print("  [dim]Grunt app директорія не знайдена[/dim]")
        console.print()
    else:
        console.print("[dim]npm пакети пропущено (--skip-npm)[/dim]")
        console.print()

    # ── 7. Міграція БД ──────────────────────────────────────────────
    if not skip_migrate:
        console.print("[bold cyan]Міграція БД[/bold cyan]")
        _run_migrations(site)
        updated_something = True
        console.print()
    else:
        console.print("[dim]Міграція БД пропущена (--skip-migrate)[/dim]")
        console.print()

    # ── Фінал ───────────────────────────────────────────────────────
    if updated_something:
        console.print("[bold green]✅ Оновлення завершено[/bold green]")
    else:
        console.print("[yellow]Нічого не оновлено[/yellow]")
