"""grunt auth * — авторизація для CLI команд."""

from __future__ import annotations

import click
import httpx

from grunt_cli.helpers import (
    DEFAULT_API,
    auth_headers,
    console,
    save_token,
    token_file,
)


@click.group()
def auth() -> None:
    """Авторизація для CLI команд."""


@auth.command("login")
@click.option("--api", default=DEFAULT_API, show_default=True)
def auth_login(api: str) -> None:
    """Авторизується і зберігає токен у ~/.grunt_token."""
    email = click.prompt("Email")
    password = click.prompt("Пароль", hide_input=True)

    try:
        resp = httpx.post(
            f"{api}/api/v1/auth/token",
            data={"username": email, "password": password},
            timeout=5.0,
        )
        if resp.status_code == 401:
            console.print("[red]✗[/red] Невірний email або пароль")
            return
        resp.raise_for_status()
        token = resp.json()["access_token"]
        save_token(token)
        console.print(f"[green]✓[/green] Авторизовано як {email}")
        console.print("[dim]Токен збережено в ~/.grunt_token[/dim]")
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout):
        console.print(f"[red]✗[/red] Сервер {api} недоступний. Запусти [cyan]grunt serve[/cyan]")


@auth.command("logout")
def auth_logout() -> None:
    """Видаляє збережений токен."""
    tf = token_file()
    if tf.exists():
        tf.unlink()
        console.print("[green]✓[/green] Вийшли з системи")
    else:
        console.print("[dim]Токен не знайдено[/dim]")


@auth.command("whoami")
@click.option("--api", default=DEFAULT_API, show_default=True)
def auth_whoami(api: str) -> None:
    """Показує поточного авторизованого користувача."""
    try:
        resp = httpx.get(
            f"{api}/api/v1/auth/me",
            headers=auth_headers(),
            timeout=5.0,
        )
        resp.raise_for_status()
        body = resp.json()
        user = body.get("data", body)
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout):
        console.print("[red]✗[/red] Сервер недоступний. Запусти [cyan]grunt serve[/cyan]")
        return

    console.print(f"[bold]{user['full_name']}[/bold]  [dim]{user['email']}[/dim]")
    if user.get("is_superadmin"):
        console.print("[cyan]Superadmin[/cyan]")
    roles = user.get("roles") or []
    if roles:
        console.print(f"Ролі: {', '.join(roles)}")
