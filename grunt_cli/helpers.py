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

def ensure_venv(target_dir: Path, install_targets: list[Path] | None = None) -> Path | None:
    """Створює .venv у target_dir та встановлює пакети через uv (або pip).

    Returns: шлях до .venv або None при невдачі.
    """
    venv_dir = target_dir / ".venv"
    uv_bin = shutil.which("uv")

    console.print("[dim]Встановлюю Python-залежності...[/dim]")

    if uv_bin:
        if not venv_dir.exists():
            subprocess.run([uv_bin, "venv", str(venv_dir)], capture_output=True, text=True)

        python_bin = str(venv_dir / "bin" / "python")
        for target in install_targets or []:
            result = subprocess.run(
                [uv_bin, "pip", "install", "-e", str(target), "--python", python_bin],
                cwd=str(target),
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                console.print("[yellow]⚠[/yellow]  Не вдалося встановити залежності автоматично")
                console.print(f"  [dim]{result.stderr.strip()}[/dim]" if result.stderr else "")
                return venv_dir
    else:
        for target in install_targets or []:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-e", "."],
                cwd=str(target),
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                console.print("[yellow]⚠[/yellow]  Не вдалося встановити залежності")
                console.print(f"  [dim]{result.stderr.strip()}[/dim]" if result.stderr else "")
                return venv_dir

    console.print("[green]✓[/green] Python-залежності встановлено")
    return venv_dir


def ensure_node(target_dir: Path) -> str | None:
    """Повертає шлях до npm, встановлюючи Node.js локально якщо потрібно.

    Порядок:
    1. npm вже є в PATH
    2. Локальна копія в target_dir/.node
    3. Завантажуємо Node.js LTS в target_dir/.node
    """
    npm_bin = shutil.which("npm")
    if npm_bin:
        return npm_bin

    local_node_dir = target_dir / ".node"
    local_npm = local_node_dir / "bin" / "npm"
    if local_npm.exists():
        return str(local_npm)

    machine = platform.machine()
    arch_map = {"x86_64": "x64", "aarch64": "arm64", "armv7l": "armv7l"}
    arch = arch_map.get(machine)
    if not arch:
        console.print(f"[yellow]⚠[/yellow]  Невідома архітектура: {machine} — пропускаю Node.js")
        return None

    slug = f"node-v{NODE_LTS_VERSION}-linux-{arch}"
    url = f"https://nodejs.org/dist/v{NODE_LTS_VERSION}/{slug}.tar.xz"

    console.print(f"[dim]Завантажую Node.js v{NODE_LTS_VERSION} ({arch})...[/dim]")
    tmp_path = target_dir / f"{slug}.tar.xz"
    try:
        urllib.request.urlretrieve(url, tmp_path)

        with tarfile.open(tmp_path, "r:xz") as tar:
            tar.extractall(path=target_dir)

        extracted = target_dir / slug
        if local_node_dir.exists():
            shutil.rmtree(local_node_dir)
        extracted.rename(local_node_dir)
        tmp_path.unlink(missing_ok=True)

        console.print(f"[green]✓[/green] Node.js v{NODE_LTS_VERSION} встановлено локально в .node/")
        return str(local_npm)
    except Exception as exc:
        console.print(f"[yellow]⚠[/yellow]  Не вдалося завантажити Node.js: {exc}")
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        return None


def install_npm_deps(grunt_dir: Path, node_base_dir: Path) -> bool:
    """Встановлює Node.js залежності у grunt_dir. Повертає True при успіху."""
    if not (grunt_dir / "package.json").exists():
        return True

    npm_bin = ensure_node(node_base_dir)
    if not npm_bin:
        console.print("[yellow]⚠[/yellow]  Не вдалося встановити Node.js автоматично")
        console.print("  [dim]Встанови вручну: https://nodejs.org/[/dim]")
        return False

    console.print("[dim]Встановлюю Node.js залежності...[/dim]")
    env = os.environ.copy()
    local_node_bin = str(node_base_dir / ".node" / "bin")
    env["PATH"] = local_node_bin + os.pathsep + env.get("PATH", "")

    result = subprocess.run(
        [npm_bin, "install"],
        cwd=str(grunt_dir),
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode == 0:
        console.print("[green]✓[/green] Node.js залежності встановлено")
        return True

    console.print("[yellow]⚠[/yellow]  npm install не вдався")
    console.print(f"  [dim]{result.stderr.strip()[:200]}[/dim]" if result.stderr else "")
    return False


def clone_grunt(target_dir: Path, repo: str = GRUNT_REPO_URL, branch: str = "master") -> Path:
    """Клонує Grunt framework в target_dir/grunt. Повертає шлях до grunt."""
    console.print(f"[dim]Клоную Grunt framework з {repo}...[/dim]")
    result = subprocess.run(
        ["git", "clone", "--branch", branch, "--depth", "1", repo, "grunt"],
        cwd=str(target_dir),
    )
    if result.returncode != 0:
        console.print("[red]✗[/red] Не вдалося клонувати репозиторій")
        raise SystemExit(1)
    console.print("[green]✓[/green] Grunt framework клоновано")
    return target_dir / "grunt"


def run_alembic(site_dir: Path, grunt_dir: Path, venv_dir: Path) -> bool:
    """Запускає alembic upgrade head для сайту. Повертає True при успіху."""
    backend_dir = grunt_dir / "backend"
    alembic_ini = backend_dir / "alembic.ini"
    if not alembic_ini.exists():
        return True

    venv_bin = venv_dir / "bin"
    alembic_bin = venv_bin / "alembic"
    if not alembic_bin.exists():
        alembic_bin = Path(shutil.which("alembic") or "alembic")

    env_file = site_dir / ".env"
    result = subprocess.run(
        [str(alembic_bin), "-c", str(alembic_ini), "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=str(site_dir),
        env={
            **os.environ,
            "DOTENV_PATH": str(env_file),
            "PYTHONPATH": str(backend_dir),
            "VIRTUAL_ENV": str(venv_dir),
            "PATH": str(venv_bin) + os.pathsep + os.environ.get("PATH", ""),
        },
    )
    if result.returncode == 0:
        console.print("[green]✓[/green] Таблиці БД створені")
        return True

    error_msg = result.stderr.strip() or result.stdout.strip()
    console.print(f"[red]✗[/red] Помилка міграцій:\n  {error_msg}")
    return False
