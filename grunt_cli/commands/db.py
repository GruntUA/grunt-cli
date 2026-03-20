"""grunt db * — управління базою даних."""

from __future__ import annotations

import subprocess
import sys

import click

from grunt_cli.helpers import console, get_site_dir


@click.group()
def db() -> None:
    """Команди для управління базою даних."""


def _backend_dir():
    return get_site_dir() / "grunt" / "backend"


@db.command("migrate")
def db_migrate() -> None:
    """Застосовує всі міграції (alembic upgrade head)."""
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(_backend_dir()),
    )
    if result.returncode == 0:
        console.print("[green]✓[/green] Міграції застосовані")
    sys.exit(result.returncode)


@db.command("rollback")
@click.argument("steps", default=1)
def db_rollback(steps: int) -> None:
    """Відкочує N міграцій назад."""
    result = subprocess.run(
        ["alembic", "downgrade", f"-{steps}"],
        cwd=str(_backend_dir()),
    )
    sys.exit(result.returncode)


@db.command("history")
def db_history() -> None:
    """Показує історію міграцій."""
    subprocess.run(
        ["alembic", "history", "--verbose"],
        cwd=str(_backend_dir()),
    )


@db.command("reset")
@click.option("--yes", is_flag=True, help="Пропустити підтвердження")
def db_reset(yes: bool) -> None:
    """Скидає всі дані і перестворює таблиці. Тільки при DEBUG=true."""
    if not yes and not click.confirm(
        "⚠️  Всі дані будуть видалені. Продовжити?"
    ):
        console.print("[dim]Скасовано[/dim]")
        return

    backend_dir = _backend_dir()

    # Використовуємо Python subprocess для скидання БД
    reset_script = (
        "from grunt.config import settings; "
        "assert settings.debug, 'db reset дозволено тільки при DEBUG=true'; "
        "import asyncio; "
        "from grunt.core.db.base import Base; "
        "from grunt.core.db.session import engine; "
        "async def _r(): "
        "    async with engine.begin() as c: "
        "        await c.run_sync(Base.metadata.drop_all); "
        "        await c.run_sync(Base.metadata.create_all); "
        "asyncio.run(_r()); "
        "print('OK')"
    )

    result = subprocess.run(
        [sys.executable, "-c", reset_script],
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        if "DEBUG=true" in result.stderr or "AssertionError" in result.stderr:
            console.print("[red]✗[/red] db reset дозволено тільки при DEBUG=true")
        else:
            console.print(f"[red]✗[/red] Помилка:\n{result.stderr}")
        sys.exit(1)

    console.print("[green]✓[/green] БД скинута і перестворена")

    # Синхронізуємо alembic_version
    subprocess.run(["alembic", "stamp", "head"], cwd=str(backend_dir))
    console.print("[green]✓[/green] Alembic синхронізовано")
