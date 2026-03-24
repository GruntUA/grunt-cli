"""Спільні утиліти для CLI команд."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

console = Console()

GRUNT_REPO_URL = "https://github.com/GruntUA/Grunt.git"
DEFAULT_API = "http://localhost:8000"

_LOCAL_HOSTS = {"localhost", "127.0.0.1"}


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
