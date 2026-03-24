"""grunt update — оновлення CLI, фреймворку та додатків через git."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

from grunt_cli.helpers import console


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
        ["git", "pull", "--rebase"],
        cwd=str(path),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        console.print(f"  [red]✗[/red] {label}: помилка git pull")
        if result.stderr.strip():
            console.print(f"    [dim]{result.stderr.strip()}[/dim]")
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

    return True


def _install_python_deps(path: Path, label: str) -> None:
    """Встановлює Python-залежності через pip install -e ."""
    if not (path / "pyproject.toml").exists() and not (path / "setup.py").exists():
        return

    console.print(f"  [dim]Встановлюю Python-залежності для {label}...[/dim]")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", "."],
        cwd=str(path),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        console.print(f"  [green]✓[/green] {label}: Python-залежності оновлено")
    else:
        console.print(f"  [yellow]⚠[/yellow]  {label}: не вдалося оновити Python-залежності")
        if result.stderr.strip():
            for line in result.stderr.strip().splitlines()[-3:]:
                console.print(f"    [dim]{line}[/dim]")


def _install_node_deps(path: Path, label: str) -> None:
    """Встановлює Node.js залежності через npm install."""
    if not (path / "package.json").exists():
        return

    console.print(f"  [dim]Встановлюю Node.js залежності для {label}...[/dim]")
    result = subprocess.run(
        ["npm", "install"],
        cwd=str(path),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        console.print(f"  [green]✓[/green] {label}: Node.js залежності оновлено")
    else:
        console.print(f"  [yellow]⚠[/yellow]  {label}: не вдалося оновити Node.js залежності")


def _find_bench_dir() -> Path | None:
    """Шукає кореневу директорію bench-проєкту (містить apps/ та sites/)."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "apps").is_dir() and (parent / "sites").is_dir():
            return parent
        # Якщо ми всередині apps/grunt або apps/*
        if parent.name == "apps" and parent.parent is not None:
            bench = parent.parent
            if (bench / "sites").is_dir():
                return bench
    return None


def _find_apps_dir() -> Path | None:
    """Повертає директорію apps/ для bench-структури."""
    bench = _find_bench_dir()
    if bench is not None:
        apps_dir = bench / "apps"
        if apps_dir.is_dir():
            return apps_dir
    return None


def _get_cli_dir() -> Path | None:
    """Повертає директорію grunt-cli (editable install)."""
    # Шукаємо через pip show
    result = subprocess.run(
        [sys.executable, "-m", "pip", "show", "grunt-cli"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
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
@click.option("--no-deps", is_flag=True, default=False,
              help="Не встановлювати залежності після оновлення")
def update(update_cli: bool, update_framework: bool, update_apps: bool, no_deps: bool) -> None:
    """Оновити CLI, фреймворк та додатки через git.

    \b
    Без прапорців оновлює все: CLI, фреймворк і додатки.
    З прапорцями — тільки вказані компоненти.

    \b
    Приклади:
      grunt update                  оновити все
      grunt update --cli            тільки CLI
      grunt update --framework      тільки фреймворк Grunt
      grunt update --apps           тільки додатки
      grunt update --no-deps        без перевстановлення залежностей
    """
    # Якщо жоден прапорець не вказано — оновлюємо все
    update_all = not (update_cli or update_framework or update_apps)

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
            pulled = _git_pull(cli_dir, "grunt-cli")
            if pulled and not no_deps:
                _install_python_deps(cli_dir, "grunt-cli")
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
            pulled = _git_pull(framework_dir, "grunt")
            if pulled and not no_deps:
                _install_python_deps(framework_dir, "grunt")
                _install_node_deps(framework_dir, "grunt")
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
                    pulled = _git_pull(app_dir, app_dir.name)
                    if pulled and not no_deps:
                        _install_python_deps(app_dir, app_dir.name)
                        _install_node_deps(app_dir, app_dir.name)
                    updated_something = True
        console.print()

    # ── Фінал ───────────────────────────────────────────────────────
    if updated_something:
        console.print("[bold green]✅ Оновлення завершено[/bold green]")
    else:
        console.print("[yellow]Нічого не оновлено[/yellow]")
