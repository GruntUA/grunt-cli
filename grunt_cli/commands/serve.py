"""grunt serve — запуск dev серверів."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import click

from grunt_cli.helpers import console, get_bench_dir, get_site_dir


@click.command()
@click.option("--host", default="0.0.0.0", show_default=True, help="Bind host для backend")
@click.option("--port", default=8000, show_default=True, help="Порт backend")
@click.option("--no-reload", "no_reload", is_flag=True, help="Вимкнути auto-reload")
@click.option("--backend-only", "backend_only", is_flag=True, help="Тільки FastAPI")
@click.option("--frontend-only", "frontend_only", is_flag=True, help="Тільки Vite")
def serve(
    host: str,
    port: int,
    no_reload: bool,
    backend_only: bool,
    frontend_only: bool,
) -> None:
    """Запускає dev сервери (backend + frontend)."""
    bench_dir = get_bench_dir()
    site_dir = get_site_dir()

    if bench_dir is not None:
        _serve_bench(bench_dir, host, port, no_reload, backend_only, frontend_only)
    elif site_dir is not None:
        _serve_flat(site_dir, host, port, no_reload, backend_only, frontend_only)
    else:
        console.print("[red]✗[/red] grunt.site не знайдено. Перейди у директорію Grunt-проекту.")
        raise SystemExit(1)


def _serve_bench(
    bench_dir: Path, host: str, port: int, no_reload: bool, backend_only: bool, frontend_only: bool,
) -> None:
    """Запуск серверів у bench-режимі (мультисайтовість)."""
    grunt_dir = bench_dir / "apps" / "grunt"
    backend_dir = grunt_dir / "backend"
    venv_dir = bench_dir / ".venv"

    if not grunt_dir.exists():
        console.print(f"[red]✗[/red] Grunt framework не знайдено: {grunt_dir}")
        raise SystemExit(1)

    # Підраховуємо сайти
    sites_dir = bench_dir / "sites"
    sites = [d.name for d in sites_dir.iterdir()
             if d.is_dir() and (d / "grunt.site").exists()] if sites_dir.is_dir() else []

    python_exe = str(venv_dir / "bin" / "python") if (venv_dir / "bin" / "python").exists() else sys.executable

    # Визначаємо активний сайт для env
    backend_env = {**os.environ, "PYTHONPATH": str(backend_dir)}
    active_site_dir = None
    if sites:
        # Перевіряємо, чи cwd знаходиться в одному з сайтів
        try:
            cwd = Path.cwd()
            for s in sites:
                sd = sites_dir / s
                if cwd == sd or sd in cwd.parents:
                    active_site_dir = sd
                    break
        except OSError:
            pass
        # Якщо не визначили за cwd і є лише один сайт — беремо його
        if active_site_dir is None and len(sites) == 1:
            active_site_dir = sites_dir / sites[0]

    if active_site_dir is not None:
        env_file = active_site_dir / ".env"
        if env_file.exists():
            backend_env["DOTENV_PATH"] = str(env_file)

    procs: list[subprocess.Popen] = []

    def shutdown(sig=None, frame=None):
        console.print("\n[dim]Зупиняю сервери...[/dim]")
        for p in procs:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    if not frontend_only and backend_dir.exists():
        backend_cmd = [python_exe, "-m", "uvicorn", "grunt.main:app", "--host", host, "--port", str(port)]
        if not no_reload:
            backend_cmd.extend(["--reload", "--reload-dir", str(backend_dir)])

        console.print(f"[green]▶[/green] Backend:  http://{host}:{port}  [dim](bench, {len(sites)} сайтів)[/dim]")
        console.print(f"  [dim]API docs: http://localhost:{port}/docs[/dim]")
        for s in sites:
            marker = " ←" if active_site_dir and active_site_dir.name == s else ""
            console.print(f"  [dim]Site:     {s}{marker}[/dim]")

        # cwd = активний сайт (щоб відносні шляхи як ./grunt.db працювали)
        # або grunt_dir якщо сайт не визначено
        backend_cwd = str(active_site_dir) if active_site_dir else str(grunt_dir)
        procs.append(subprocess.Popen(
            backend_cmd,
            cwd=backend_cwd,
            env=backend_env,
        ))

    if not backend_only:
        _start_frontend(procs, grunt_dir, bench_dir)

    _wait_for_procs(procs, shutdown)


def _serve_flat(
    site_dir: Path, host: str, port: int, no_reload: bool, backend_only: bool, frontend_only: bool,
) -> None:
    """Запуск серверів у flat-режимі (один сайт)."""
    grunt_dir = site_dir / "apps" / "grunt"
    backend_dir = grunt_dir / "backend"

    if not grunt_dir.exists():
        console.print(f"[red]✗[/red] Grunt framework не знайдено: {grunt_dir}")
        raise SystemExit(1)

    # Python exe
    site_venv = site_dir / ".venv" / "bin" / "python"
    python_exe = str(site_venv) if site_venv.exists() else sys.executable

    # Env
    backend_env = {**os.environ}
    env_file = site_dir / ".env"
    if env_file.exists():
        backend_env["DOTENV_PATH"] = str(env_file)

    procs: list[subprocess.Popen] = []

    def shutdown(sig=None, frame=None):
        console.print("\n[dim]Зупиняю сервери...[/dim]")
        for p in procs:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    if not frontend_only and backend_dir.exists():
        backend_cmd = [python_exe, "-m", "uvicorn", "grunt.main:app", "--host", host, "--port", str(port)]
        if not no_reload:
            backend_cmd.extend(["--reload", "--reload-dir", str(backend_dir)])

        console.print(f"[green]▶[/green] Backend:  http://{host}:{port}")
        console.print(f"  [dim]API docs: http://localhost:{port}/docs[/dim]")
        console.print(f"  [dim]Site:     {site_dir}[/dim]")

        procs.append(subprocess.Popen(
            backend_cmd,
            cwd=str(site_dir),
            env={**backend_env, "PYTHONPATH": str(backend_dir)},
        ))

    if not backend_only:
        _start_frontend(procs, grunt_dir, site_dir)

    _wait_for_procs(procs, shutdown)


def _start_frontend(procs: list, grunt_dir: Path, node_base_dir: Path) -> None:
    """Запускає Vite frontend."""
    if not (grunt_dir / "package.json").exists():
        console.print("[yellow]⚠[/yellow]  package.json не знайдено, frontend пропущено")
        return

    local_npm = node_base_dir / ".node" / "bin" / "npm"
    npm_bin = str(local_npm) if local_npm.exists() else shutil.which("npm") or "npm"

    frontend_env = {**os.environ}
    local_node_bin = node_base_dir / ".node" / "bin"
    if local_node_bin.exists():
        frontend_env["PATH"] = str(local_node_bin) + os.pathsep + frontend_env.get("PATH", "")

    console.print("[green]▶[/green] Frontend: http://localhost:5173")
    procs.append(subprocess.Popen([npm_bin, "run", "dev"], cwd=str(grunt_dir), env=frontend_env))


def _wait_for_procs(procs: list, shutdown) -> None:
    """Чекає на завершення процесів."""
    if not procs:
        console.print("[red]Нічого не запущено[/red]")
        return

    console.print()
    console.print("[dim]Ctrl+C для зупинки[/dim]")

    try:
        while True:
            for p in procs:
                if p.poll() is not None:
                    console.print(f"[red]Процес завершився з кодом {p.returncode}[/red]")
                    shutdown()
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutdown()
