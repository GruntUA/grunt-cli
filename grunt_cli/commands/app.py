"""grunt app * — управління додатками."""

from __future__ import annotations

import click

from grunt_cli.helpers import FrameworkGroup, console, get_apps_dir, git_clone


@click.group(cls=FrameworkGroup)
def app() -> None:
    """Команди для управління Grunt-додатками.

    \b
    Тут лише `get` (git clone у apps/ — працює і без venv фреймворку).
    Решту команд (install, uninstall, list, create, remove, deps, export…)
    виконує CLI фреймворку:
      grunt app install NAME    встановити додаток на сайт
      grunt app create NAME     новий додаток (шаблон фреймворку)
    """


@app.command("get")
@click.argument("repo_url")
@click.option("--branch", default=None, help="Гілка для клонування")
def app_get(repo_url: str, branch: str | None) -> None:
    """Завантажити додаток з git-репозиторію."""
    apps_dir = get_apps_dir()
    apps_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"[dim]Клоную {repo_url}...[/dim]")
    if not git_clone(repo_url, apps_dir, branch=branch):
        console.print("[red]✗[/red] Не вдалося клонувати репозиторій")
        raise SystemExit(1)

    # Визначаємо назву завантаженого додатку (остання частина URL без .git)
    app_name = repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
    console.print(
        f"[green]✓[/green] Додаток [bold]{app_name}[/bold] завантажено до {apps_dir / app_name}"
    )
    console.print(
        f"  Тепер встанови його: [cyan]grunt app install {app_name} --site localhost[/cyan]"
    )
