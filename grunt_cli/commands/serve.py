"""grunt serve — запуск dev серверів."""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

import click

from grunt_cli.helpers import console, get_site_dir


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
    grunt_dir = site_dir / "grunt"

    if not grunt_dir.exists():
        console.print(
            "[red]✗[/red] Grunt framework не знайдено. "
            "Запусти [cyan]grunt install <назва>[/cyan]"
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

    if not frontend_only and backend_dir.exists():
        backend_cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "grunt.main:app",
            "--host",
            host,
            "--port",
            str(port),
        ]
        if not no_reload:
            backend_cmd.append("--reload")

        console.print(f"[green]▶[/green] Backend:  http://{host}:{port}")
        console.print(f"  [dim]API docs: http://localhost:{port}/docs[/dim]")
        procs.append(subprocess.Popen(backend_cmd, cwd=str(backend_dir)))

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
