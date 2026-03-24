"""grunt serve — запуск dev серверів."""

from __future__ import annotations

import os
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
    site_dir = get_site_dir()
    if site_dir is None:
        console.print("[red]✗[/red] grunt.site не знайдено. Перейди у директорію Grunt-проекту.")
        raise SystemExit(1)

    bench_dir = get_bench_dir()
    if bench_dir is None:
        console.print("[red]✗[/red] Bench-структуру не знайдено (потрібні apps/ та sites/).")
        raise SystemExit(1)

    grunt_dir = bench_dir / "apps" / "grunt"

    if not grunt_dir.exists():
        console.print(
            "[red]✗[/red] Grunt framework не знайдено в [cyan]{0}[/cyan]. "
            "Запусти [cyan]grunt install grunt[/cyan]".format(grunt_dir)
        )
        raise SystemExit(1)

    procs: list[subprocess.Popen[bytes]] = []

    def shutdown(sig: object = None, frame: object = None) -> None:
        console.print("\n[dim]Зупиняю сервери...[/dim]")
        for p in procs:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    backend_dir = grunt_dir / "backend"

    # Середовище для backend: .env з site_dir, PYTHONPATH на backend
    backend_env = {**os.environ}
    env_file = site_dir / ".env"
    if env_file.exists():
        backend_env["DOTENV_PATH"] = str(env_file)

    # Знаходимо Python: bench venv → site venv → системний
    bench_venv = bench_dir / ".venv" / "bin" / "python"
    site_venv = site_dir / ".venv" / "bin" / "python"
    if bench_venv.exists():
        python_exe = str(bench_venv)
    elif site_venv.exists():
        python_exe = str(site_venv)
    else:
        python_exe = sys.executable

    if not frontend_only and backend_dir.exists():
        backend_cmd = [
            python_exe,
            "-m",
            "uvicorn",
            "grunt.main:app",
            "--host",
            host,
            "--port",
            str(port),
        ]
        if not no_reload:
            backend_cmd.extend(["--reload", "--reload-dir", str(backend_dir)])

        console.print(f"[green]▶[/green] Backend:  http://{host}:{port}")
        console.print(f"  [dim]API docs: http://localhost:{port}/docs[/dim]")
        console.print(f"  [dim]Site:     {site_dir}[/dim]")
        # Запускаємо з cwd=site_dir щоб відносні шляхи (grunt.db) вказували на сайт
        procs.append(subprocess.Popen(
            backend_cmd,
            cwd=str(site_dir),
            env={**backend_env, "PYTHONPATH": str(backend_dir)},
        ))

    if not backend_only:
        pkg_json = grunt_dir / "package.json"
        if not pkg_json.exists():
            console.print("[yellow]⚠[/yellow]  package.json не знайдено, frontend пропущено")
        else:
            console.print("[green]▶[/green] Frontend: http://localhost:5173")
            procs.append(subprocess.Popen(["npm", "run", "dev"], cwd=str(grunt_dir)))

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
