"""grunt users * — керування користувачами."""

from __future__ import annotations

import click

from grunt_cli.helpers import console, venv_delegate


@click.group()
def users() -> None:
    """Керування користувачами."""


@users.command("list")
@click.option("--site", default=None, help="Назва сайту")
def users_list(site: str | None) -> None:
    """Показати список всіх користувачів."""
    rc = venv_delegate("users", "list", site=site)
    if rc == -1:
        console.print("[red]✗[/red] Backend CLI не знайдено. Запустіть у папці проекту.")
    raise SystemExit(0 if rc in (0, -1) else rc)


@users.command("create")
@click.option("--email", prompt="Email")
@click.option("--password", prompt="Пароль", hide_input=True, confirmation_prompt=True)
@click.option("--full-name", prompt="Повне ім'я")
@click.option("--site", default=None, help="Назва сайту")
def users_create(email: str, password: str, full_name: str, site: str | None) -> None:
    """Створити нового користувача напряму в БД."""
    rc = venv_delegate("users", "create", "--email", email, "--password", password, "--full-name", full_name, site=site)
    if rc == -1:
        console.print("[red]✗[/red] Backend CLI не знайдено. Запустіть у папці проекту.")
    raise SystemExit(0 if rc in (0, -1) else rc)


@users.command("set-password")
@click.argument("email")
@click.option("--site", default=None, help="Назва сайту")
def users_set_password(email: str, site: str | None) -> None:
    """Змінити пароль користувача."""
    password = click.prompt("Новий пароль", hide_input=True, confirmation_prompt=True)
    rc = venv_delegate("users", "set-password", email, "--password", password, site=site)
    if rc == -1:
        console.print("[red]✗[/red] Backend CLI не знайдено. Запустіть у папці проекту.")
    raise SystemExit(0 if rc in (0, -1) else rc)
