"""grunt db * — управління базою даних."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import click

from grunt_cli.helpers import console, get_bench_dir, get_current_site, get_site_dir


def _resolve_db_context(site_name: str | None) -> tuple[Path, Path, dict]:
    """Повертає (backend_dir, site_dir, env) для alembic."""
    bench_dir = get_bench_dir()

    if bench_dir is not None:
        if site_name:
            site_dir = bench_dir / "sites" / site_name
            if not (site_dir / "grunt.site").exists():
                console.print(f"[red]✗[/red] Сайт '{site_name}' не знайдено")
                raise SystemExit(1)
        else:
            site_dir = get_current_site()
            if site_dir is None:
                console.print(
                    "[red]✗[/red] Немає активного сайту. "
                    "Вкажи [cyan]--site <name>[/cyan] або запусти [cyan]grunt use <site>[/cyan]"
                )
                raise SystemExit(1)

        backend_dir = bench_dir / "apps" / "grunt" / "backend"
        venv_dir = bench_dir / ".venv"
    else:
        site_dir = get_site_dir()
        if site_dir is None:
            console.print("[red]✗[/red] grunt.site не знайдено. Перейди у директорію Grunt-проекту.")
            raise SystemExit(1)
        backend_dir = site_dir / "apps" / "grunt" / "backend"
        venv_dir = site_dir / ".venv"

    venv_bin = venv_dir / "bin"
    env = {
        **os.environ,
        "DOTENV_PATH": str(site_dir / ".env"),
        "PYTHONPATH": str(backend_dir),
        "VIRTUAL_ENV": str(venv_dir),
        "PATH": str(venv_bin) + os.pathsep + os.environ.get("PATH", ""),
    }

    return backend_dir, site_dir, env


def _get_alembic_cmd(backend_dir: Path, env: dict) -> list[str]:
    """Повертає базову команду alembic з -c alembic.ini."""
    venv_bin = env["VIRTUAL_ENV"] + "/bin"
    alembic_bin = venv_bin + "/alembic"
    if not Path(alembic_bin).exists():
        alembic_bin = shutil.which("alembic") or "alembic"
    alembic_ini = str(backend_dir / "alembic.ini")
    return [alembic_bin, "-c", alembic_ini]


@click.group()
@click.option("--site", "site_name", default=None, help="Цільовий сайт (bench-режим)")
@click.pass_context
def db(ctx: click.Context, site_name: str | None) -> None:
    """Команди для управління базою даних."""
    ctx.ensure_object(dict)
    ctx.obj["site"] = site_name


@db.command("migrate")
@click.option("--dry-run", is_flag=True, help="Показати план міграцій без застосування")
@click.pass_context
def db_migrate(ctx: click.Context, dry_run: bool) -> None:
    """Застосовує всі міграції (alembic upgrade head)."""
    backend_dir, site_dir, env = _resolve_db_context(ctx.obj["site"])
    cmd = _get_alembic_cmd(backend_dir, env) + ["upgrade", "head"]

    if dry_run:
        cmd.extend(["--sql"])
        console.print(f"[dim]Сайт: {site_dir.name} (сухе запущення)[/dim]\n")
        result = subprocess.run(cmd, cwd=str(site_dir), env=env)
        console.print(f"\n[yellow]![/yellow] Це лише показ. Для застосування запусти без [cyan]--dry-run[/cyan]")
        sys.exit(result.returncode)

    console.print(f"[dim]Сайт: {site_dir.name}[/dim]")
    result = subprocess.run(cmd, cwd=str(site_dir), env=env)
    if result.returncode == 0:
        console.print("[green]✓[/green] Міграції застосовані")
    sys.exit(result.returncode)


@db.command("rollback")
@click.argument("steps", default=1)
@click.pass_context
def db_rollback(ctx: click.Context, steps: int) -> None:
    """Відкочує N міграцій назад."""
    backend_dir, site_dir, env = _resolve_db_context(ctx.obj["site"])
    cmd = _get_alembic_cmd(backend_dir, env) + ["downgrade", f"-{steps}"]

    console.print(f"[dim]Сайт: {site_dir.name}[/dim]")
    result = subprocess.run(cmd, cwd=str(site_dir), env=env)
    sys.exit(result.returncode)


@db.command("history")
@click.pass_context
def db_history(ctx: click.Context) -> None:
    """Показує історію міграцій."""
    backend_dir, site_dir, env = _resolve_db_context(ctx.obj["site"])
    cmd = _get_alembic_cmd(backend_dir, env) + ["history", "--verbose"]
    subprocess.run(cmd, cwd=str(site_dir), env=env)


@db.command("reset")
@click.option("--yes", is_flag=True, help="Пропустити підтвердження")
@click.pass_context
def db_reset(ctx: click.Context, yes: bool) -> None:
    """Скидає всі дані і перестворює таблиці. Тільки при DEBUG=true."""
    backend_dir, site_dir, env = _resolve_db_context(ctx.obj["site"])

    console.print(f"[dim]Сайт: {site_dir.name}[/dim]")

    if not yes and not click.confirm("⚠️  Всі дані будуть видалені. Продовжити?"):
        console.print("[dim]Скасовано[/dim]")
        return

    venv_python = env["VIRTUAL_ENV"] + "/bin/python"
    if not Path(venv_python).exists():
        venv_python = sys.executable

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
        [venv_python, "-c", reset_script],
        cwd=str(site_dir),
        capture_output=True,
        text=True,
        env=env,
    )

    if result.returncode != 0:
        if "DEBUG=true" in result.stderr or "AssertionError" in result.stderr:
            console.print("[red]✗[/red] db reset дозволено тільки при DEBUG=true")
        else:
            console.print(f"[red]✗[/red] Помилка:\n{result.stderr}")
        sys.exit(1)

    console.print("[green]✓[/green] БД скинута і перестворена")

    cmd = _get_alembic_cmd(backend_dir, env) + ["stamp", "head"]
    subprocess.run(cmd, cwd=str(site_dir), env=env)
    console.print("[green]✓[/green] Alembic синхронізовано")
