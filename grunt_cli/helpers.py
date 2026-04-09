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
    """Повертає директорію поточного Grunt-сайту.
    Шукає grunt.site у поточній директорії та батьківських.
    """
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "grunt.site").exists():
            return parent
    return None


def get_bench_dir() -> Path | None:
    """Повертає кореневу директорію bench (де є і apps/, і sites/)."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "apps").is_dir() and (parent / "sites").is_dir():
            return parent
    # Якщо ми в папці сайту, bench — це прабатько
    site = get_site_dir()
    if site and site.parent.name == "sites":
        bench = site.parent.parent
        if (bench / "apps").is_dir():
            return bench
    return None


def get_apps_dir() -> Path:
    """Повертає директорію додатків поточного bench."""
    bench = get_bench_dir()
    if bench:
        return bench / "apps"
    raise SystemExit("[red]✗[/red] Bench не знайдено. Запустіть в папці проекту.")


def get_current_site() -> Path | None:
    """Повертає директорію активного сайту (з currentsite.txt або поточної папки)."""
    bench = get_bench_dir()
    if bench:
        current_file = bench / "sites" / "currentsite.txt"
        if current_file.exists():
            name = current_file.read_text().strip()
            if name:
                site_path = bench / "sites" / name
                if (site_path / "grunt.site").exists():
                    return site_path
    
    # Якщо нема в файлі — повертаємо поточну папку (якщо це сайт)
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

def get_mise_bin() -> str | None:
    """Знаходить шлях до mise."""
    mise_bin = shutil.which("mise")
    if not mise_bin:
        # Спроба знайти в стандартному місці
        candidates = [
            Path.home() / ".local/bin/mise",
            Path.home() / ".cargo/bin/mise",
            Path.home() / ".local/share/mise/bin/mise",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
    return mise_bin


def run_mise(cwd: Path, *args: str, env: dict[str, str] | None = None, config_file: Path | None = None) -> bool:
    """Виконує команду mise у вказаній директорії (блокує)."""
    mise_bin = get_mise_bin()
    if not mise_bin:
        console.print("[red]✗[/red] [bold]mise[/bold] не знайдено. Встановіть його для роботи.")
        return False

    # Trust
    trust_cmd = [str(mise_bin)]
    if config_file:
        trust_cmd.extend(["--config", str(config_file)])
    trust_cmd.append("trust")
    subprocess.run(trust_cmd, cwd=str(cwd), capture_output=True)

    cmd = [str(mise_bin)]
    if config_file:
        cmd.extend(["--config", str(config_file)])
    
    if args and args[0] in {"install", "setup", "test", "lint", "fmt", "build", "db:migrate", "serve", "dev"}:
         cmd.extend(["run"])
    cmd.extend(args)

    final_env = {**os.environ, **(env or {})}
    result = subprocess.run(cmd, cwd=str(cwd), env=final_env)
    return result.returncode == 0


def run_mise_popen(cwd: Path, *args: str, env: dict[str, str] | None = None, config_file: Path | None = None, **kwargs) -> subprocess.Popen:
    """Запускає команду mise у вказаній директорії (не блокує)."""
    mise_bin = get_mise_bin() or "mise"
    
    # Trust
    trust_cmd = [str(mise_bin)]
    if config_file:
        trust_cmd.extend(["--config", str(config_file)])
    trust_cmd.append("trust")
    subprocess.run(trust_cmd, cwd=str(cwd), capture_output=True)

    cmd = [str(mise_bin)]
    if config_file:
        cmd.extend(["--config", str(config_file)])

    if args and args[0] in {"install", "setup", "test", "lint", "fmt", "build", "db:migrate", "serve", "dev"}:
         cmd.extend(["run"])
    cmd.extend(args)

    final_env = {**os.environ, **(env or {})}
    return subprocess.Popen(cmd, cwd=str(cwd), env=final_env, **kwargs)


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


def find_uv() -> str | None:
    """Знаходить шлях до uv."""
    uv_bin = shutil.which("uv")
    if not uv_bin:
        # Спроба знайти в стандартному місці
        candidates = [
            Path.home() / ".local/bin/uv",
            Path.home() / ".cargo/bin/uv",
            Path.home() / ".local/share/mise/shims/uv",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
    return uv_bin
