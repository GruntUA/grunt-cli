"""grunt master — повна інтерактивна установка й запуск сервера."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

import click

from grunt_cli.helpers import (
    GRUNT_REPO_URL,
    clone_grunt,
    console,
    run_mise,
    save_token,
)

_DB_CHOICES = {
    "sqlite": {
        "label": "SQLite (локальний файл, без сервера)",
        "default_url": "sqlite+aiosqlite:///./grunt.db",
    },
    "postgres": {
        "label": "PostgreSQL",
        "default_url": "postgresql+asyncpg://postgres:postgres@localhost:5432/grunt",
    },
    "mysql": {
        "label": "MySQL / MariaDB",
        "default_url": "mysql+aiomysql://root:root@localhost:3306/grunt",
    },
}


def _prompt_database() -> str:
    """Інтерактивний вибір СУБД і побудова DATABASE_URL."""
    console.print("База даних:")
    for i, (key, info) in enumerate(_DB_CHOICES.items(), 1):
        console.print(f"  [cyan]{i}[/cyan]) {info['label']}")

    choice = click.prompt(
        "Оберіть СУБД",
        type=click.IntRange(1, len(_DB_CHOICES)),
        default=1,
    )
    db_key = list(_DB_CHOICES)[choice - 1]
    db_info = _DB_CHOICES[db_key]

    if db_key == "sqlite":
        db_file = click.prompt("  Файл БД", default="grunt.db")
        return f"sqlite+aiosqlite:///./{db_file}"

    # Для серверних СУБД — збираємо параметри
    host = click.prompt("  Хост", default="localhost")
    port_map = {"postgres": 5432, "mysql": 3306}
    db_port = click.prompt("  Порт", default=port_map[db_key], type=int)
    user = click.prompt("  Користувач", default="root" if db_key == "mysql" else "postgres")
    password = click.prompt("  Пароль", default="", hide_input=True)
    db_name = click.prompt("  Назва БД", default="grunt")

    driver_map = {"postgres": "postgresql+asyncpg", "mysql": "mysql+aiomysql"}
    driver = driver_map[db_key]

    if password:
        return f"{driver}://{user}:{password}@{host}:{db_port}/{db_name}"
    return f"{driver}://{user}@{host}:{db_port}/{db_name}"


@click.command()
@click.option("--repo", default=GRUNT_REPO_URL, show_default=True, help="URL репозиторію Grunt")
@click.option("--branch", default="master", show_default=True, help="Гілка для клонування")
def master(repo: str, branch: str) -> None:
    """Інтерактивна установка Grunt з нуля до працюючого сервера.

    \b
    Виконує все необхідне на новому оточенні:
      1. Створює bench-проєкт (мультитенантна структура)
      2. Створює перший сайт
      3. Генерує SECRET_KEY
      4. Застосовує міграції БД
      5. Створює адміністратора
      6. Запускає dev сервер
    """
    console.print()
    console.print("[bold]⚡ Ґрунт — інтерактивна установка[/bold]")
    console.print()

    # ── 1. Назва проєкту ──────────────────────────────────────────────
    project_name = click.prompt("Назва проєкту", default="grunt-bench")
    project_dir = Path(project_name).resolve()

    if project_dir.exists() and any(project_dir.iterdir()):
        console.print(f"[red]✗[/red] Директорія '{project_name}' вже існує і не порожня")
        raise SystemExit(1)

    # ── 2. Назва першого сайту ────────────────────────────────────────
    site_name = click.prompt("Назва першого сайту", default="dev.local")

    # ── 3. База даних ─────────────────────────────────────────────────
    db_url = _prompt_database()

    # ── 4. Порт сервера ───────────────────────────────────────────────
    port = click.prompt("Порт backend", default=8000, type=int)

    console.print()
    console.print("[dim]─── Створюю проєкт ───[/dim]")

    # ── 5. Створення bench-структури ──────────────────────────────────
    project_dir.mkdir(parents=True, exist_ok=True)
    apps_dir = project_dir / "apps"
    apps_dir.mkdir(exist_ok=True)
    sites_dir = project_dir / "sites"
    sites_dir.mkdir(exist_ok=True)

    # Перший сайт
    site_dir = sites_dir / site_name
    site_dir.mkdir(parents=True, exist_ok=True)

    site_config = {
        "framework_path": "apps/grunt",
        "apps_path": "apps",
        "installed_apps": ["grunt"],
    }
    (site_dir / "grunt.site").write_text(json.dumps(site_config, ensure_ascii=False, indent=2))
    (sites_dir / "currentsite.txt").write_text(site_name)

    # ── 6. .env ───────────────────────────────────────────────────────
    secret = secrets.token_hex(32)
    env_content = f"DEBUG=true\nDATABASE_URL={db_url}\nSECRET_KEY={secret}\n"
    (site_dir / ".env").write_text(env_content)
    console.print("[green]✓[/green] SECRET_KEY згенеровано")

    # ── 7. Клонування фреймворку ──────────────────────────────────────
    grunt_dir = clone_grunt(apps_dir, repo, branch)

    # 8. Встановлення всього через mise
    run_mise(project_dir, "install")

    # 10. Міграції
    if (grunt_dir / "backend").exists():
        console.print("[dim]Застосовую міграції...[/dim]")
        run_mise(site_dir, "db:migrate")

    # ── 11. Адміністратор ─────────────────────────────────────────────
    console.print()
    if click.confirm("Створити адміністратора?", default=True):
        email = click.prompt("  Email", default="admin@example.com")
        password = click.prompt("  Пароль", hide_input=True, confirmation_prompt=True)
        full_name = click.prompt("  Повне ім'я", default="Адміністратор")

        # Створюємо адміна напряму через backend CLI (без сервера)
        from grunt_cli.helpers import venv_delegate  # noqa: PLC0415
        rc = venv_delegate(
            "users", "create",
            "--email", email,
            "--password", password,
            "--full-name", full_name,
            site=site_name,
        )
        if rc == 0:
            console.print(f"[green]✓[/green] Адміністратор {email} створений")
        elif rc != -1:
            console.print(f"[yellow]⚠[/yellow] Не вдалося створити адміна автоматично.")
            console.print("Після запуску: [cyan]grunt users create[/cyan]")
        else:
            console.print("[yellow]⚠[/yellow] Backend CLI не знайдено. Після запуску: [cyan]grunt users create[/cyan]")

    # ── 12. Фінал ─────────────────────────────────────────────────────
    console.print()
    console.print(f"[bold green]✅ Ґрунт встановлено та налаштовано у {project_dir}[/bold green]")
    console.print()

    if click.confirm("Запустити dev сервер зараз?", default=True):
        console.print()
        import os

        from grunt_cli.commands.serve import serve as serve_cmd
        os.chdir(str(project_dir))
        ctx = click.Context(serve_cmd, info_name="serve")
        ctx.invoke(serve_cmd, host="0.0.0.0", port=port, no_reload=False, backend_only=False, frontend_only=False)
    else:
        console.print("Для запуску:")
        console.print(f"  [cyan]cd {project_name}[/cyan]")
        console.print(f"  [cyan]grunt serve --port {port}[/cyan]")
