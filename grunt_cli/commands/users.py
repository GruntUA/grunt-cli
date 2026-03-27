"""grunt users * — керування користувачами."""

from __future__ import annotations

import click
import httpx
from rich.table import Table

from grunt_cli.helpers import DEFAULT_API, auth_headers, console


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
@click.option("--api", default=DEFAULT_API, show_default=True)
def users_create(api: str) -> None:
    """Створити нового користувача."""
    email = click.prompt("Email")
    password = click.prompt("Пароль", hide_input=True, confirmation_prompt=True)
    full_name = click.prompt("Повне ім'я")

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
        console.print(f"[red]✗[/red] Сервер {api} недоступний.")


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
