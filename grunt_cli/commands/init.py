"""grunt init — ініціалізація Grunt-сайту."""

from __future__ import annotations

import re
import secrets
import subprocess
import sys
from pathlib import Path

import click
import httpx

from grunt_cli.helpers import console, get_site_dir


@click.command()
def init() -> None:
    """Ініціалізує Grunt-сайт: міграції БД, створення адміна."""
    site_dir = get_site_dir()
    grunt_dir = site_dir / "grunt"

    if not (site_dir / "grunt.site").exists():
        console.print(
            "[red]✗[/red] grunt.site не знайдено. "
            "Спочатку запусти [cyan]grunt install <назва>[/cyan]"
        )
        raise SystemExit(1)

    # 1. Генерація SECRET_KEY
    env_file = site_dir / ".env"
    if env_file.exists():
        env_content = env_file.read_text()
        if "change-me" in env_content or "SECRET_KEY=" not in env_content:
            secret = secrets.token_hex(32)
            if "SECRET_KEY=" in env_content:
                env_content = re.sub(r"SECRET_KEY=.*", f"SECRET_KEY={secret}", env_content)
            else:
                env_content += f"\nSECRET_KEY={secret}\n"
            env_file.write_text(env_content)
            console.print("[green]✓[/green] SECRET_KEY згенеровано")

    # 2. Alembic міграції
    backend_dir = grunt_dir / "backend"
    if backend_dir.exists():
        console.print("[dim]Застосовую міграції...[/dim]")
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            cwd=str(backend_dir),
            env={**__import__("os").environ, "DOTENV_PATH": str(env_file)},
        )
        if result.returncode == 0:
            console.print("[green]✓[/green] Таблиці БД створені")
        else:
            console.print(f"[red]✗[/red] Помилка міграцій:\n{result.stderr}")
            console.print("[dim]Запусти вручну: cd grunt/backend && alembic upgrade head[/dim]")

    # 3. Створення адміністратора
    console.print()
    if click.confirm("Створити адміністратора?", default=True):
        email = click.prompt("  Email", default="admin@grunt.local")
        password = click.prompt("  Пароль", hide_input=True, confirmation_prompt=True)
        full_name = click.prompt("  Повне ім'я", default="Адміністратор")

        try:
            resp = httpx.post(
                "http://localhost:8000/api/v1/auth/register",
                json={"email": email, "password": password, "full_name": full_name},
                timeout=5.0,
            )
            if resp.status_code == 200:
                console.print(f"[green]✓[/green] Адміністратор {email} створений")
            elif resp.status_code == 409:
                console.print(f"[yellow]~[/yellow] Користувач {email} вже існує")
            else:
                console.print(f"[red]✗[/red] Помилка: {resp.text}")
        except Exception:  # noqa: BLE001
            console.print("[yellow]⚠[/yellow]  Сервер недоступний.")
            console.print("   Спочатку запусти [cyan]grunt serve[/cyan], потім зареєструй адміна:")
            console.print("   [dim]POST http://localhost:8000/api/v1/auth/register[/dim]")

    # 4. Фінал
    console.print()
    console.print("[bold green]✅ Ґрунт ініціалізовано![/bold green]")
    console.print()
    console.print("Наступні кроки:")
    console.print("  [cyan]grunt serve[/cyan]          запустити сервер")
    console.print("  [cyan]grunt auth login[/cyan]     авторизуватись для CLI команд")
    console.print("  [cyan]grunt doctype list[/cyan]   переглянути DocTypes")
