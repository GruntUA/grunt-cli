"""grunt install — встановлення Grunt framework."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import click

from grunt_cli.helpers import GRUNT_REPO_URL, console


@click.command()
@click.argument("project_name", default="grunt-site")
@click.option("--repo", default=GRUNT_REPO_URL, show_default=True, help="URL репозиторію Grunt")
@click.option("--branch", default="master", show_default=True, help="Гілка для клонування")
def install(project_name: str, repo: str, branch: str) -> None:
    """Встановлює Grunt framework у нову директорію.

    Створює структуру сайту:

    \b
      <project_name>/
        apps/
          grunt/          ← фреймворк (клонований репозиторій)
          ...             ← інші додатки
        grunt.site        ← маркер-файл сайту
        .env              ← конфігурація
    """
    site_dir = Path(project_name)

    if site_dir.exists() and any(site_dir.iterdir()):
        console.print(f"[red]✗[/red] Директорія '{project_name}' вже існує і не порожня")
        raise SystemExit(1)

    site_dir.mkdir(parents=True, exist_ok=True)

    # 1. Створюємо структуру сайту
    apps_dir = site_dir / "apps"
    apps_dir.mkdir(exist_ok=True)

    # 2. Клонуємо Grunt framework в apps/grunt
    console.print(f"[dim]Клоную Grunt framework з {repo}...[/dim]")
    result = subprocess.run(
        ["git", "clone", "--branch", branch, "--depth", "1", repo, "grunt"],
        cwd=str(apps_dir),
    )
    if result.returncode != 0:
        console.print("[red]✗[/red] Не вдалося клонувати репозиторій")
        raise SystemExit(1)
    console.print("[green]✓[/green] Grunt framework встановлено")

    site_config = {
        "framework_path": "apps/grunt",
        "apps_path": "apps",
        "installed_apps": ["grunt"],
    }
    (site_dir / "grunt.site").write_text(json.dumps(site_config, ensure_ascii=False, indent=2))

    # 3. .env
    env_content = (
        "DEBUG=true\n"
        "DATABASE_URL=sqlite+aiosqlite:///./grunt.db\n"
        "SECRET_KEY=change-me\n"
    )
    (site_dir / ".env").write_text(env_content)

    # 4. Встановлюємо Python-залежності
    grunt_dir = apps_dir / "grunt"
    console.print("[dim]Встановлюю Python-залежності...[/dim]")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", "."],
        cwd=str(grunt_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        console.print("[green]✓[/green] Python-залежності встановлено")
    else:
        console.print("[yellow]⚠[/yellow]  Не вдалося встановити залежності автоматично")
        console.print(f"  [dim]Запусти вручну: cd {grunt_dir} && pip install -e .[/dim]")

    # 5. Node залежності
    if (grunt_dir / "package.json").exists():
        console.print("[dim]Встановлюю Node.js залежності...[/dim]")
        result = subprocess.run(
            ["npm", "install"],
            cwd=str(grunt_dir),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            console.print("[green]✓[/green] Node.js залежності встановлено")
        else:
            console.print("[yellow]⚠[/yellow]  npm install не вдався")
            console.print(f"  [dim]Запусти вручну: cd {grunt_dir} && npm install[/dim]")

    # Фінал
    console.print()
    console.print(f"[bold green]✅ Grunt встановлено у {site_dir.resolve()}[/bold green]")
    console.print()
    console.print("Наступні кроки:")
    console.print(f"  [cyan]cd {project_name}[/cyan]")
    console.print("  [cyan]grunt init[/cyan]            ініціалізувати БД і створити адміна")
    console.print("  [cyan]grunt serve[/cyan]           запустити dev сервер")
