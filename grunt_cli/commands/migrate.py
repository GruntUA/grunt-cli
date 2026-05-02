"""grunt migrate — синхронізувати схему БД та метадані DocType з JSON-файлів."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click

from grunt_cli.helpers import console, get_bench_dir, get_current_site, get_site_dir


def _bench_sites(bench_dir: Path) -> list[Path]:
    """Повертає всі валідні сайти bench (тільки директорії з grunt.site)."""
    sites_dir = bench_dir / "sites"
    if not sites_dir.exists():
        return []

    return sorted(
        [
            site
            for site in sites_dir.iterdir()
            if site.is_dir() and not site.name.startswith(".") and (site / "grunt.site").exists()
        ],
        key=lambda p: p.name,
    )


def _resolve_context(site_name: str | None) -> tuple[Path, Path, dict]:
    """Повертає (framework_dir, site_dir, env)."""
    bench_dir = get_bench_dir()

    if bench_dir is not None:
        if site_name:
            site_dir = bench_dir / "sites" / site_name
            if not (site_dir / "grunt.site").exists():
                console.print(f"[red]✗[/red] Сайт '{site_name}' не знайдено")
                raise SystemExit(1)
        else:
            # Без --site мігруємо всі сайти. Для env беремо активний сайт,
            # а якщо його немає — перший валідний сайт у bench.
            site_dir = get_current_site()
            if site_dir is None or site_dir.parent != (bench_dir / "sites"):
                all_sites = _bench_sites(bench_dir)
                site_dir = all_sites[0] if all_sites else None
            if site_dir is None:
                console.print(
                    "[red]✗[/red] Не знайдено жодного сайту у bench (sites/*/grunt.site)"
                )
                raise SystemExit(1)
        framework_dir = bench_dir / "apps" / "grunt"
        venv_dir = framework_dir / ".venv"
    else:
        site_dir = get_site_dir()
        if site_dir is None:
            console.print("[red]✗[/red] grunt.site не знайдено. Увійдіть у директорію проекту.")
            raise SystemExit(1)
        framework_dir = Path.cwd()
        venv_dir = framework_dir / ".venv"

    venv_bin = venv_dir / "bin"
    env = {
        **os.environ,
        "DOTENV_PATH": str(site_dir / ".env"),
        "PYTHONPATH": str(framework_dir / "backend"),
        "VIRTUAL_ENV": str(venv_dir),
        "PATH": str(venv_bin) + os.pathsep + os.environ.get("PATH", ""),
    }
    return framework_dir, site_dir, env


@click.command("migrate")
@click.option("--site", "site_name", default=None, help="Цільовий сайт (без параметра: всі сайти)")
def migrate(site_name: str | None) -> None:
    """Синхронізувати схему БД та метадані DocType з JSON-файлів.

    \b
    Виконує два кроки:
      1. Оновлює метадані DocType у БД (порівнює JSON-файли з записами в grunt_core_meta_doctype)
         і додає нові колонки в таблиці (ALTER TABLE ADD COLUMN).
      2. Застосовує alembic-міграції (upgrade head).

    \b
    Запускай після будь-яких змін у *.json файлах DocType або після git pull.
    """
    framework_dir, site_dir, env = _resolve_context(site_name)
    venv_python = str(framework_dir / ".venv" / "bin" / "python")
    if not Path(venv_python).exists():
        venv_python = sys.executable

    if site_name:
        console.print(f"[dim]Сайт: {site_dir.name}[/dim]\n")
    elif get_bench_dir() is not None:
        sites_count = len(_bench_sites(get_bench_dir()))
        console.print(f"[dim]Сайти: всі ({sites_count})[/dim]\n")
    else:
        console.print(f"[dim]Сайт: {site_dir.name}[/dim]\n")

    # ── 1. Sync DocType metadata ──────────────────────────────────────
    console.print("[bold cyan][1/2] Синхронізація DocType метаданих[/bold cyan]")

    sync_script = f"""
import asyncio
import logging

logging.disable(logging.CRITICAL)

import structlog

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))

from sqlalchemy import or_

from grunt.core.db.base import Base
from grunt.core.metadata.compiler import compile_doctype_to_table
from grunt.core.site.manager import current_site, site_manager
from grunt.core.metadata.registry import doctype_registry
from grunt.core.startup import load_core_doctypes, seed_app_workspaces, sync_all_doctypes

TARGET_SITE = {site_name!r}


async def _sync() -> None:
    sites = [TARGET_SITE] if TARGET_SITE else site_manager.get_sites()
    failures: list[str] = []

    for site in sites:
        token = current_site.set(site)
        try:
            eng = site_manager.get_engine(site)
            maker = site_manager.get_session_maker(site)
            async with eng.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with maker() as session:
                # Persist latest bundled core metadata into DB before app sync.
                await load_core_doctypes(session, sync_db=True)
                # Import/update app DocTypes from JSON files into grunt_meta_doctype.
                await seed_app_workspaces(session, site)
                # Ensure physical tables match the refreshed metadata.
                await sync_all_doctypes(session, eng)

                # Backfill required fields with defaults for legacy rows created
                # before fields became required (prevents 422 on first save).
                backfilled = 0
                for dt in await doctype_registry.list_all():
                    if dt.is_virtual:
                        continue

                    table = compile_doctype_to_table(dt)
                    for field in dt.fields:
                        if not getattr(field, "required", False):
                            continue

                        default = getattr(field, "default", None)
                        if default in (None, ""):
                            continue

                        col = table.c.get(field.fieldname)
                        if col is None:
                            continue

                        result = await session.execute(
                            table.update()
                            .where(or_(col.is_(None), col == ""))
                            .values({{field.fieldname: default}})
                        )
                        backfilled += int(getattr(result, "rowcount", 0) or 0)

                await session.commit()

            print(f"✓ {{site}} (backfilled={{backfilled}})")
        except Exception as exc:  # noqa: BLE001
            print(f"✗ {{site}}: {{exc}}")
            failures.append(site)
        finally:
            current_site.reset(token)

    if failures:
        raise SystemExit(1)


asyncio.run(_sync())
"""

    result = subprocess.run(
        [venv_python, "-c", sync_script],
        cwd=str(framework_dir),
        capture_output=True,
        text=True,
        env=env,
    )

    for line in result.stdout.splitlines():
        if line.strip():
            console.print(f"  {line.strip()}")

    if result.returncode != 0:
        console.print("[red]✗[/red] Помилка синхронізації DocType")
        for line in result.stderr.splitlines():
            if any(w in line for w in ("Error", "error", "Exception", "Traceback")):
                console.print(f"  [dim red]{line.strip()}[/dim red]")
        sys.exit(1)

    console.print("[green]✓[/green] DocType метадані синхронізовано\n")

    # ── 2. Alembic migrations ─────────────────────────────────────────
    console.print("[bold cyan][2/2] Alembic міграції[/bold cyan]")

    backend_dir = framework_dir / "backend"
    alembic_ini = backend_dir / "alembic.ini"
    alembic_bin = str(framework_dir / ".venv" / "bin" / "alembic")
    if not Path(alembic_bin).exists():
        import shutil  # noqa: PLC0415
        alembic_bin = shutil.which("alembic") or "alembic"

    result = subprocess.run(
        [alembic_bin, "-c", str(alembic_ini), "upgrade", "head"],
        cwd=str(framework_dir),
        env=env,
    )

    if result.returncode != 0:
        console.print("[red]✗[/red] Alembic міграція завершилась з помилкою")
        sys.exit(result.returncode)

    console.print("[green]✓[/green] Alembic міграції застосовано\n")

    # ── 3. Signal running server to reload metadata cache ─────────────
    # SiteContextMiddleware checks for this file on the next request
    # and calls doctype_registry.clear_cache() automatically.
    bench_dir = get_bench_dir()
    if bench_dir is not None:
        sites_dir = bench_dir / "sites"
    else:
        sites_dir = framework_dir.parent / "sites"

    if site_name:
        _signal_sites = [site_name]
    else:
        _signal_sites = [
            d.name
            for d in sites_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".") and (d / "grunt.site").exists()
        ] if sites_dir.exists() else []

    _signaled: list[str] = []
    for _s in _signal_sites:
        _reload_file = sites_dir / _s / ".reload_meta"
        try:
            _reload_file.touch()
            _signaled.append(_s)
        except Exception:
            pass

    if _signaled:
        console.print(
            f"[dim]🔄 Сервер отримає сигнал оновлення кешу при наступному запиті "
            f"({', '.join(_signaled)})[/dim]"
        )

    console.print("[bold green]✅ Міграція завершена[/bold green]")
