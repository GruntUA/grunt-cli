"""grunt serve — запуск dev серверів."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from os import killpg
from pathlib import Path

import click

from grunt_cli.helpers import console, get_bench_dir, get_site_dir, run_mise_popen


def _kill_port(port: int) -> None:
    """Kill any process occupying the given port."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=5,
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


def _group_alive(pgid: int) -> bool:
    try:
        killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


# Command-line markers of the dev processes `grunt serve` spawns (via mise) in apps/grunt.
_DEV_PROCESS_MARKERS = ("grunt.tasks.worker:broker", "grunt.main:app")


def _find_stale_processes(grunt_dir: Path) -> set[int]:
    """Process groups of leftover backend/worker processes from a previous `grunt serve`.

    Children run in their own sessions, so if `grunt serve` died without cleanup
    (SIGKILL, lost terminal) they keep running. uvicorn is caught by the port check,
    but the TaskIQ worker holds no port and would pile up — match by cwd + cmdline.
    """
    target = grunt_dir.resolve()
    own_pgid = os.getpgrp()
    pgids: set[int] = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            if not any(m in cmdline for m in _DEV_PROCESS_MARKERS):
                continue
            if Path(os.readlink(entry / "cwd")).resolve() != target:
                continue
            pgid = os.getpgid(int(entry.name))
        except OSError:
            continue
        if pgid != own_pgid:
            pgids.add(pgid)
    return pgids


def _kill_stale_processes(grunt_dir: Path) -> None:
    """Terminate leftovers of a previous `grunt serve` for this bench (Linux only)."""
    if not Path("/proc").is_dir():
        return
    pgids = _find_stale_processes(grunt_dir)
    if not pgids:
        return
    console.print(
        f"  [dim]Зупиняю залишки попереднього запуску (PGID: {', '.join(map(str, sorted(pgids)))})[/dim]"
    )
    for pgid in pgids:
        try:
            killpg(pgid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and any(_group_alive(g) for g in pgids):
        time.sleep(0.2)
    for pgid in pgids:
        try:
            killpg(pgid, signal.SIGKILL)
        except OSError:
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
    bench_dir: Path,
    host: str,
    port: int,
    no_reload: bool,
    backend_only: bool,
    frontend_only: bool,
) -> None:
    """Запуск серверів у bench-режимі (мультисайтовість)."""
    grunt_dir = bench_dir / "apps" / "grunt"
    venv_dir = bench_dir / ".venv"

    if not grunt_dir.exists():
        console.print(f"[red]✗[/red] Grunt framework не знайдено: {grunt_dir}")
        raise SystemExit(1)

    # Підраховуємо сайти
    sites_dir = bench_dir / "sites"
    sites = (
        [d.name for d in sites_dir.iterdir() if d.is_dir() and (d / "grunt.site").exists()]
        if sites_dir.is_dir()
        else []
    )

    python_exe = (
        str(venv_dir / "bin" / "python")
        if (venv_dir / "bin" / "python").exists()
        else sys.executable
    )

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
        # Each child is a session leader (start_new_session), so pgid == pid and
        # stays valid after mise itself exits. Wait for the whole group, not just
        # mise — otherwise uv/taskiq outliving it get orphaned.
        pgids = [p.pid for p in procs]
        for pgid in pgids:
            try:
                killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and any(_group_alive(g) for g in pgids):
            for p in procs:
                p.poll()  # reap mise so it does not keep the group "alive" as a zombie
            time.sleep(0.2)
        for pgid in pgids:
            try:
                killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    # Closed terminal / dropped SSH: children live in their own sessions and
    # would not get the hangup themselves.
    signal.signal(signal.SIGHUP, shutdown)

    # Free ports / kill leftovers from a previous run
    if not frontend_only:
        _kill_stale_processes(grunt_dir)
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
            reload_flag = (
                "--reload "
                + " ".join(f"--reload-dir {d}" for d in reload_dirs)
                + " --reload-include '*.json'"
            )
        else:
            reload_flag = ""

        backend_env.update(
            {
                "HOST": host,
                "PORT": str(port),
                "RELOAD": reload_flag,
            }
        )

        console.print(
            f"[green]▶[/green] Backend:  http://{host}:{port}  [dim](bench, {len(sites)} сайтів)[/dim]"
        )
        console.print(f"  [dim]API docs: http://localhost:{port}/docs[/dim]")
        for s in sites:
            marker = " ←" if active_site_dir and active_site_dir.name == s else ""
            console.print(f"  [dim]Site:     {s}{marker}[/dim]")

        procs.append(
            run_mise_popen(
                grunt_dir, "backend", env=backend_env, config_file=grunt_dir / "mise.toml"
            )
        )

        # Tasks go to Redis when the site has REDIS_URL — someone has to take them.
        if _redis_configured(backend_env):
            console.print("[green]▶[/green] Worker:   TaskIQ [dim](Redis)[/dim]")
            procs.append(
                run_mise_popen(
                    grunt_dir, "worker", env=backend_env, config_file=grunt_dir / "mise.toml"
                )
            )
        else:
            console.print(
                "  [dim]Worker:   не потрібен (REDIS_URL не задано — задачі в процесі)[/dim]"
            )

    if not backend_only:
        _start_frontend(procs, grunt_dir, bench_dir)

    _wait_for_procs(procs, shutdown)


def _redis_configured(env: dict[str, str]) -> bool:
    """True when the backend will use a Redis broker (REDIS_URL in env or the site .env)."""
    if env.get("REDIS_URL"):
        return True
    dotenv = env.get("DOTENV_PATH")
    if not dotenv or not Path(dotenv).exists():
        return False
    for line in Path(dotenv).read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "REDIS_URL" and value.strip().strip("'\""):
            return True
    return False


def _start_frontend(procs: list, grunt_dir: Path, node_base_dir: Path) -> None:
    """Запускає Vite frontend."""
    if not (grunt_dir / "package.json").exists():
        console.print("[yellow]⚠[/yellow]  package.json не знайдено, frontend пропущено")
        return

    console.print("[green]▶[/green] Frontend: http://localhost:5173")
    procs.append(
        run_mise_popen(grunt_dir, "frontend", env=os.environ, config_file=grunt_dir / "mise.toml")
    )


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
