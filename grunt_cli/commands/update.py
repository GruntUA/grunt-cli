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

    # ── Фінал ───────────────────────────────────────────────────────
    if updated_something:
        console.print("[bold green]✅ Оновлення завершено[/bold green]")
    else:
        console.print("[yellow]Нічого не оновлено[/yellow]")
