"""grunt install — встановлення Grunt framework (flat-структура)."""

from __future__ import annotations

import json
from pathlib import Path

import click

from grunt_cli.helpers import (
    GRUNT_REPO_URL,
    clone_grunt,
    console,
    run_mise,
)


@click.command()
@click.argument("project_name", default="grunt-site")
@click.option("--repo", default=GRUNT_REPO_URL, show_default=True, help="URL репозиторію Grunt")
@click.option("--branch", default="master", show_default=True, help="Гілка для клонування")
def install(project_name: str, repo: str, branch: str) -> None:
    """Встановлює Grunt framework у нову директорію (bench-структура).

    \b
      <project_name>/
        apps/
          grunt/          ← фреймворк
        sites/
          default/        ← перший сайт
            grunt.site    ← маркер-файл
            .env          ← конфігурація
    """
    bench_dir = Path(project_name).resolve()

    if bench_dir.exists() and any(bench_dir.iterdir()):
        console.print(f"[red]✗[/red] Директорія '{project_name}' вже існує і не порожня")
        raise SystemExit(1)

    bench_dir.mkdir(parents=True, exist_ok=True)

    # 1. Структура
    apps_dir = bench_dir / "apps"
    apps_dir.mkdir(exist_ok=True)
    sites_dir = bench_dir / "sites"
    sites_dir.mkdir(exist_ok=True)

    # Перший сайт
    site_dir = sites_dir / "default"
    site_dir.mkdir(parents=True, exist_ok=True)

    # 2. Клонуємо Grunt
    grunt_dir = clone_grunt(apps_dir, repo, branch)

    # 3. grunt.site (відносні шляхи до apps і grunt)
    site_config = {
        "framework_path": "../../apps/grunt",
        "apps_path": "../../apps",
        "installed_apps": ["grunt"],
    }
    (site_dir / "grunt.site").write_text(json.dumps(site_config, ensure_ascii=False, indent=2))
    (sites_dir / "currentsite.txt").write_text("default")

    # 4. .env
    env_content = (
        "DEBUG=true\n"
        "DATABASE_URL=sqlite+aiosqlite:///./grunt.db\n"
        "SECRET_KEY=change-me\n"
    )
    (site_dir / ".env").write_text(env_content)

    # 5. Встановлення всього через mise
    run_mise(bench_dir, "install")

    # Фінал
    console.print()
    console.print(f"[bold green]✅ Grunt встановлено у {bench_dir}[/bold green]")
    console.print()
    console.print("Наступні кроки:")
    console.print(f"  [cyan]cd {project_name}[/cyan]")
    console.print("  [cyan]grunt init[/cyan]            ініціалізувати БД і створити адміна")
    console.print("  [cyan]grunt serve[/cyan]           запустити dev сервер")
