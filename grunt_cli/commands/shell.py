"""grunt shell — інтерактивний Python REPL з Grunt контекстом."""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

import click

from grunt_cli.helpers import console, get_bench_dir, get_site_dir


@click.command()
@click.option("--site", default=None, help="Ім'я сайту (за замовчуванням: перший знайдений)")
def shell(site: str | None) -> None:
    """Запустити інтерактивний Python REPL з Grunt контекстом.

    \b
    Доступні об'єкти:
      session           AsyncSession
      engine            AsyncEngine
      registry          DocType Registry
      run(coro)         виконати async coroutine
      get_doc(dt, id)   отримати документ
      get_list(dt, ...) список документів
      save_doc(dt, {})  створити або оновити
      delete_doc(dt, id)видалити

    \b
    Приклади:
      grunt shell
      grunt shell --site my-site
    """
    bench = get_bench_dir()

    if bench is not None:
        python_exe = _find_python(bench / ".venv")
        backend_dir = bench / "apps" / "grunt" / "backend"
        cwd = _resolve_site_dir(bench, site)
    else:
        site_dir = get_site_dir()
        if site_dir is None:
            console.print("[red]✗[/red] grunt.site не знайдено. Перейди у директорію Grunt-проєкту.")
            raise SystemExit(1)
        python_exe = _find_python(site_dir / ".venv")
        backend_dir = site_dir / "apps" / "grunt" / "backend"
        cwd = str(site_dir)

    if not backend_dir.exists():
        console.print(f"[red]✗[/red] Grunt framework не знайдено: {backend_dir}")
        raise SystemExit(1)

    env = {**os.environ, "PYTHONPATH": str(backend_dir)}

    # Load site .env if present
    env_file = Path(cwd) / ".env"
    if env_file.exists():
        env["DOTENV_PATH"] = str(env_file)

    site_arg = f"site={site!r}" if site else ""
    startup = f"from grunt.utils.shell import start_shell; start_shell({site_arg})"

    result = subprocess.run([python_exe, "-c", startup], env=env, cwd=cwd)
    raise SystemExit(result.returncode)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _find_python(venv_dir: Path) -> str:
    candidate = venv_dir / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def _resolve_site_dir(bench: Path, site: str | None) -> str:
    sites_dir = bench / "sites"
    if not sites_dir.is_dir():
        return str(bench)

    if site:
        candidate = sites_dir / site
        if candidate.is_dir() and (candidate / "grunt.site").exists():
            return str(candidate)
        console.print(f"[yellow]![/yellow] Сайт '{site}' не знайдено, використовую bench dir")
        return str(bench)

    # Auto-detect: single site or cwd match
    site_dirs = [d for d in sites_dir.iterdir() if d.is_dir() and (d / "grunt.site").exists()]
    if len(site_dirs) == 1:
        return str(site_dirs[0])

    # Try to match cwd
    try:
        cwd = Path.cwd()
        for sd in site_dirs:
            if cwd == sd or sd in cwd.parents:
                return str(sd)
    except OSError:
        pass

    return str(bench)
