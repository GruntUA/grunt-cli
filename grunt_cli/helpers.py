"""Спільні утиліти для CLI команд."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

from rich.console import Console

console = Console()

GRUNT_REPO_URL = "https://github.com/GruntUA/Grunt.git"
DEFAULT_API = "http://localhost:8000"
NODE_LTS_VERSION = "22.14.0"

_LOCAL_HOSTS = {"localhost", "127.0.0.1"}


# ---------------------------------------------------------------------------
# Site / Bench discovery
# ---------------------------------------------------------------------------

def get_site_dir() -> Path | None:
    """Повертає директорію поточного Grunt-сайту або None якщо не знайдено.

    Шукає grunt.site у поточній директорії та батьківських.
    Якщо не знайдено — шукає в sites/*/ (bench-структура).
    """
    cwd = Path.cwd()
    # Прямий пошук: cwd та батьківські директорії
    for parent in [cwd, *cwd.parents]:
        if (parent / "grunt.site").exists():
            return parent
    # Bench-структура: sites/*/grunt.site
    for parent in [cwd, *cwd.parents]:
        sites_dir = parent / "sites"
        if sites_dir.is_dir():
            for site in sites_dir.iterdir():
                if site.is_dir() and (site / "grunt.site").exists():
                    return site
    return None


def get_bench_dir() -> Path | None:
    """Повертає кореневу директорію bench (де є apps/ і sites/).

    Bench-структура:
        my-bench/
        ├── apps/          ← додатки
        ├── sites/         ← сайти
        │   └── my-site/
        │       └── grunt.site
        └── .venv/
    """
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "apps").is_dir() and (parent / "sites").is_dir():
            return parent
    # Fallback: якщо site_dir знайдено, bench — його прабатько
    site_dir = get_site_dir()
    if site_dir is not None:
        bench = site_dir.parent.parent  # sites/my-site → sites → bench
        if (bench / "apps").is_dir():
            return bench
    return None


def get_apps_dir() -> Path:
    """Повертає директорію додатків: bench/apps/ або глобальний ~/.grunt/apps/."""
    bench = get_bench_dir()
    if bench is not None:
        return bench / "apps"
    global_dir = Path.home() / ".grunt" / "apps"
    global_dir.mkdir(parents=True, exist_ok=True)
    return global_dir


def get_current_site() -> Path | None:
    """Повертає директорію активного сайту.

    Bench-режим: читає sites/currentsite.txt.
    Flat-режим: повертає get_site_dir().
    """
    bench = get_bench_dir()
    if bench is not None:
        current_file = bench / "sites" / "currentsite.txt"
        if current_file.exists():
            name = current_file.read_text().strip()
            if name:
                site_path = bench / "sites" / name
                if (site_path / "grunt.site").exists():
                    return site_path
        return None
    return get_site_dir()


# ---------------------------------------------------------------------------
# API / Auth helpers
# ---------------------------------------------------------------------------

def resolve_site_api(site: str) -> str:
    """Перетворює ідентифікатор сайту на базовий API URL.

    Приклади:
        localhost          → http://localhost:8000
        localhost:9000     → http://localhost:9000
        dev.itmlt.win      → https://dev.itmlt.win
        http://myhost:8080 → http://myhost:8080
    """
    if "://" in site:
        return site.rstrip("/")

    host = site.split(":")[0]
    if host in _LOCAL_HOSTS:
        port = site.split(":")[1] if ":" in site else "8000"
        return f"http://localhost:{port}"

    return f"https://{site.rstrip('/')}"


def token_file() -> Path:
    return Path.home() / ".grunt_token"


def get_token() -> str | None:
    tf = token_file()
    return tf.read_text().strip() if tf.exists() else None


def save_token(token: str) -> None:
    token_file().write_text(token)


def auth_headers() -> dict[str, str]:
    token = get_token()
    if not token:
        console.print("[red]✗[/red] Не авторизовано. Запусти: [cyan]grunt auth login[/cyan]")
        raise SystemExit(1)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Dependency installation helpers
# ---------------------------------------------------------------------------

def run_mise(cwd: Path, *args: str) -> bool:
    """Виконує команду mise у вказаній директорії.
    Автоматично виконує 'mise trust' перед запуском.
    """
    mise_bin = shutil.which("mise")
    if not mise_bin:
        # Спроба знайти в стандартному місці
        mise_bin = str(Path.home() / ".local/bin/mise")
        if not Path(mise_bin).exists():
            console.print("[red]✗[/red] [bold]mise[/bold] не знайдено. Встановіть його для роботи.")
            return False

    # 1. Trust
    subprocess.run([str(mise_bin), "trust"], cwd=str(cwd), capture_output=True)

    # 2. Run
    # Якщо перший аргумент це задача (не містить двокрапки або відома як задача), 
    # mise потребує 'run', але ми можемо передавати 'run' явно або неявно.
    # Для надійності використовуємо 'run' для задач.
    cmd = [str(mise_bin)]
    if args and args[0] in {"install", "setup", "test", "lint", "fmt", "build"}:
         cmd.extend(["run"])
    
    cmd.extend(args)

    result = subprocess.run(cmd, cwd=str(cwd))
    return result.returncode == 0


def clone_grunt(target_dir: Path, repo: str = GRUNT_REPO_URL, branch: str = "master") -> Path:
    """Клонує Grunt framework в target_dir/grunt. Повертає шлях до grunt."""
    console.print(f"[dim]Клоную Grunt framework з {repo}...[/dim]")
    result = subprocess.run(
        ["git", "--version"], capture_output=True
    )
    if result.returncode != 0:
        console.print("[red]✗[/red] [bold]git[/bold] не знайдено. Встановіть його.")
        raise SystemExit(1)

    result = subprocess.run(
        ["git", "clone", "--branch", branch, "--depth", "1", repo, "grunt"],
        cwd=str(target_dir),
    )
    if result.returncode != 0:
        console.print("[red]✗[/red] Не вдалося клонувати репозиторій")
        raise SystemExit(1)
    console.print("[green]✓[/green] Grunt framework клоновано")
    return target_dir / "grunt"


    return result.returncode == 0
