"""grunt users * — керування користувачами."""

from __future__ import annotations

import os
import subprocess

import click
import httpx
from rich.table import Table

from grunt_cli.helpers import DEFAULT_API, auth_headers, console, get_bench_dir


def _get_venv_grunt() -> str | None:
    """Повертає шлях до backend grunt CLI у .venv, або None якщо не знайдено."""
    bench_dir = get_bench_dir()
    if bench_dir is None:
        return None
    venv_grunt = bench_dir / "apps" / "grunt" / ".venv" / "bin" / "grunt"
    return str(venv_grunt) if venv_grunt.exists() else None


def _get_dotenv_path() -> str | None:
    """Повертає шлях до .env активного сайту, або None."""
    from grunt_cli.helpers import get_current_site  # noqa: PLC0415
    site_dir = get_current_site()
    if site_dir is None:
        return None
    env_file = site_dir / ".env"
    return str(env_file) if env_file.exists() else None



@click.group()
def users() -> None:
    """Керування користувачами."""


@users.command("list")
@click.option("--api", default=DEFAULT_API, show_default=True)
def users_list(api: str) -> None:
    """Показати список всіх користувачів."""
    try:
        resp = httpx.get(
            f"{api}/api/v1/auth/users",
            headers=auth_headers(),
            timeout=5.0,
        )
        resp.raise_for_status()
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout):
        console.print(f"[red]✗[/red] Сервер {api} недоступний.")
        return

    body = resp.json()
    users_data = body if isinstance(body, list) else body.get("data", [])

    if not users_data:
        console.print("[dim]Користувачів немає.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Email")
    table.add_column("Ім'я")
    table.add_column("Ролі")
    table.add_column("Superadmin")

    for u in users_data:
        roles = ", ".join(u.get("roles") or []) or "—"
        superadmin = "[cyan]так[/cyan]" if u.get("is_superadmin") else ""
        table.add_row(u["email"], u["full_name"], roles, superadmin)

    console.print(table)


@users.command("create")
@click.option("--email", prompt="Email")
@click.option("--password", prompt="Пароль", hide_input=True, confirmation_prompt=True)
@click.option("--full-name", prompt="Повне ім'я")
@click.option("--api", default=DEFAULT_API, show_default=True)
def users_create(email: str, password: str, full_name: str, api: str) -> None:
    """Створити нового користувача (напряму в БД або через API якщо сервер запущений)."""

    # Спробуємо напряму через backend CLI (не потребує запущеного сервера)
    venv_grunt = _get_venv_grunt()
    dotenv = _get_dotenv_path()
    if venv_grunt:
        env = {**os.environ}
        if dotenv:
            env["DOTENV_PATH"] = dotenv
        grunt_dir = str(get_bench_dir() / "apps" / "grunt")  # type: ignore[operator]
        result = subprocess.run(
            [venv_grunt, "users", "create",
             "--email", email, "--password", password, "--full-name", full_name],
            cwd=grunt_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            console.print(f"[green]✓[/green] Створено: {email} ({full_name})")
        elif "вже існує" in output or "already exists" in output:
            console.print(f"[yellow]~[/yellow] Користувач {email} вже існує")
        else:
            console.print(f"[red]✗[/red] Помилка: {output}")
        return

    # Fallback: через HTTP API (якщо сервер запущений)
    try:
        resp = httpx.post(
            f"{api}/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": full_name},
            timeout=5.0,
        )
        if resp.status_code in (200, 201):
            u = resp.json()
            label = "superadmin" if u.get("is_superadmin") else "user"
            console.print(f"[green]✓[/green] Створено {label}: {u['email']} ({u['full_name']})")
        elif resp.status_code == 409:
            console.print(f"[yellow]~[/yellow] Користувач {email} вже існує")
        else:
            console.print(f"[red]✗[/red] Помилка: {resp.text}")
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout):
        console.print(f"[red]✗[/red] Backend CLI не знайдено і сервер {api} недоступний.")
        console.print("   Запусти [cyan]grunt serve[/cyan] та спробуй знову.")


@users.command("set-password")
@click.argument("email")
@click.option("--api", default=DEFAULT_API, show_default=True)
def users_set_password(email: str, api: str) -> None:
    """Змінити пароль користувача."""
    password = click.prompt("Новий пароль", hide_input=True, confirmation_prompt=True)

    try:
        resp = httpx.post(
            f"{api}/api/v1/auth/users/set-password",
            json={"email": email, "password": password},
            headers=auth_headers(),
            timeout=5.0,
        )
        if resp.status_code == 200:
            console.print(f"[green]✓[/green] Пароль змінено для {email}")
        elif resp.status_code == 404:
            console.print(f"[red]✗[/red] Користувача {email} не знайдено")
        else:
            console.print(f"[red]✗[/red] Помилка: {resp.text}")
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout):
        console.print(f"[red]✗[/red] Сервер {api} недоступний.")
