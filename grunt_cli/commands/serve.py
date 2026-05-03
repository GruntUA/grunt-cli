"""grunt serve — запуск dev серверів."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from os import killpg, getpgid
from pathlib import Path

import click

from grunt_cli.helpers import console, get_bench_dir, get_site_dir, run_mise_popen


def _kill_port(port: int) -> None:
    """Kill any process occupying the given port."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split()
        if pids:
            console.print(f"  [dim]Звільняю порт {port} (PID: {', '.join(pids)})[/dim]")
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except (ProcessLookupError, ValueError):
                    pass
            time.sleep(0.5)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


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
    
    if bench_dir is None:
        console.print("[red]✗[/red] Bench не знайдено. Перейди у директорію Grunt-проекту.")
        raise SystemExit(1)

    _serve_bench(bench_dir, host, port, no_reload, backend_only, frontend_only)


def _serve_bench(
    bench_dir: Path, host: str, port: int, no_reload: bool, backend_only: bool, frontend_only: bool,
) -> None:
    """Запуск серверів у bench-режимі (мультисайтовість)."""
    grunt_dir = bench_dir / "apps" / "grunt"
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
    backend_env = {**os.environ, "PYTHONPATH": str(grunt_dir)}
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
            try:
                killpg(getpgid(p.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    killpg(getpgid(p.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Free ports from stale processes
    if not frontend_only:
        _kill_port(port)
    if not backend_only:
        _kill_port(5173)

    if not frontend_only:
        if not no_reload:
            reload_dirs = [str(grunt_dir / "grunt")]
            # Also watch all installed app packages (e.g. hrm/hrm, cms/cms, …)
            apps_dir = bench_dir / "apps"
            if apps_dir.is_dir():
                for app_dir in sorted(apps_dir.iterdir()):
                    if app_dir.name == "grunt" or not app_dir.is_dir():
                        continue
                    # Convention: package dir has same name as the app folder
                    pkg_dir = app_dir / app_dir.name
                    if pkg_dir.is_dir():
                        reload_dirs.append(str(pkg_dir))
            reload_flag = "--reload " + " ".join(f"--reload-dir {d}" for d in reload_dirs)
        else:
            reload_flag = ""

        backend_env.update({
            "HOST": host,
            "PORT": str(port),
            "RELOAD": reload_flag,
        })
        
        console.print(f"[green]▶[/green] Backend:  http://{host}:{port}  [dim](bench, {len(sites)} сайтів)[/dim]")
        console.print(f"  [dim]API docs: http://localhost:{port}/docs[/dim]")
        for s in sites:
            marker = " ←" if active_site_dir and active_site_dir.name == s else ""
            console.print(f"  [dim]Site:     {s}{marker}[/dim]")

        procs.append(run_mise_popen(
            grunt_dir,
            "backend",
            env=backend_env,
            config_file=grunt_dir / "mise.toml"
        ))

    if not backend_only:
        _start_frontend(procs, grunt_dir, bench_dir)

    _wait_for_procs(procs, shutdown)


def _start_frontend(procs: list, grunt_dir: Path, node_base_dir: Path) -> None:
    """Запускає Vite frontend."""
    if not (grunt_dir / "package.json").exists():
        console.print("[yellow]⚠[/yellow]  package.json не знайдено, frontend пропущено")
        return

    console.print("[green]▶[/green] Frontend: http://localhost:5173")
    procs.append(run_mise_popen(
        grunt_dir, 
        "frontend", 
        env=os.environ,
        config_file=grunt_dir / "mise.toml"
    ))


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
