"""grunt init — ініціалізація bench або сайту."""

from __future__ import annotations

import re
import secrets
from pathlib import Path

import click
import httpx

from grunt_cli.helpers import (
    GRUNT_REPO_URL,
    clone_grunt,
    console,
    get_bench_dir,
    get_current_site,
    get_site_dir,
    run_mise,
)


@click.command()
@click.argument("name", required=False, default=None)
@click.option("--repo", default=GRUNT_REPO_URL, show_default=True, help="URL репозиторію Grunt")
@click.option("--branch", default="master", show_default=True, help="Гілка для клонування")
def init(name: str | None, repo: str, branch: str) -> None:
    """Ініціалізує bench або поточний сайт.

    \b
    З аргументом — створює нову bench-структуру:
      grunt init my-bench

    \b
    Без аргументу — ініціалізує поточний сайт (міграції БД, створення адміна):
      cd my-bench && grunt init
    """
    if name is not None:
        _init_bench(name, repo, branch)
    else:
        _init_site()


# ---------------------------------------------------------------------------
# grunt init <name> — створення bench
# ---------------------------------------------------------------------------

def _init_bench(name: str, repo: str, branch: str) -> None:
    bench_dir = Path(name).resolve()

    if bench_dir.exists() and any(bench_dir.iterdir()):
        console.print(f"[red]✗[/red] Директорія '{name}' вже існує і не порожня")
        raise SystemExit(1)

    bench_dir.mkdir(parents=True, exist_ok=True)

    apps_dir = bench_dir / "apps"
    sites_dir = bench_dir / "sites"
    apps_dir.mkdir(exist_ok=True)
    sites_dir.mkdir(exist_ok=True)

    # Клонуємо Grunt
    grunt_dir = clone_grunt(apps_dir, repo, branch)

    # Встановлюємо все через mise
    run_mise(bench_dir, "install")

    console.print()
    console.print(f"[bold green]✅ Bench створено у {bench_dir}[/bold green]")
    console.print()
    console.print("Наступні кроки:")
    console.print(f"  [cyan]cd {name}[/cyan]")
    console.print("  [cyan]grunt sites new dev.local[/cyan]    створити перший сайт")
    console.print("  [cyan]grunt serve[/cyan]                  запустити сервери")


# ---------------------------------------------------------------------------
# grunt init (без аргументу) — ініціалізація поточного сайту
# ---------------------------------------------------------------------------

def _init_site() -> None:
    bench_dir = get_bench_dir()

    if bench_dir is None:
        console.print(
            "[red]✗[/red] Bench не знайдено. "
            "Спочатку створи проект: [cyan]grunt install <name>[/cyan]"
        )
        raise SystemExit(1)

    site_dir = get_current_site()
    if site_dir is None:
        console.print(
            "[red]✗[/red] Немає активного сайту. "
            "Запусти [cyan]grunt sites use <site>[/cyan] або [cyan]grunt sites new <name>[/cyan]"
        )
        raise SystemExit(1)

    grunt_dir = bench_dir / "apps" / "grunt"
    console.print(f"[dim]Сайт: {site_dir.name}[/dim]")

    # 1. SECRET_KEY
    env_file = site_dir / ".env"
    if env_file.exists():
        env_content = env_file.read_text()
        if "change-me" in env_content or "SECRET_KEY=" not in env_content:
            secret = secrets.token_hex(32)
            if "SECRET_KEY=" in env_content:
                env_content = re.sub(r"SECRET_KEY=.*", f"SECRET_KEY={secret}", env_content)
            else:
                env_content += f"\nSECRET_KEY={secret}\n"
            env_file.write_text(env_content)
            console.print("[green]✓[/green] SECRET_KEY згенеровано")

    # 2. Alembic
    backend_dir = grunt_dir / "backend"
    if backend_dir.exists():
        console.print("[dim]Застосовую міграції...[/dim]")
        run_mise(
            grunt_dir, 
            "db:migrate", 
            env={"DOTENV_PATH": str(site_dir / ".env")}
        )

    # 3. Адміністратор
    console.print()
    if click.confirm("Створити адміністратора?", default=True):
        email = click.prompt("  Email", default="admin@grunt.local")
        password = click.prompt("  Пароль", hide_input=True, confirmation_prompt=True)
        full_name = click.prompt("  Повне ім'я", default="Адміністратор")

        try:
            resp = httpx.post(
                "http://localhost:8000/api/v1/auth/register",
                json={"email": email, "password": password, "full_name": full_name},
                timeout=5.0,
            )
            if resp.status_code in (200, 201):
                console.print(f"[green]✓[/green] Адміністратор {email} створений")
            elif resp.status_code == 409:
                console.print(f"[yellow]~[/yellow] Користувач {email} вже існує")
            else:
                console.print(f"[red]✗[/red] Помилка: {resp.text}")
        except Exception:  # noqa: BLE001
            console.print("[yellow]⚠[/yellow]  Сервер недоступний.")
            console.print("   Спочатку запусти [cyan]grunt serve[/cyan], потім зареєструй адміна:")
            console.print("   [dim]POST http://localhost:8000/api/v1/auth/register[/dim]")

    # 4. Фінал
    console.print()
    console.print("[bold green]✅ Ґрунт ініціалізовано![/bold green]")
    console.print()
    console.print("Наступні кроки:")
    console.print("  [cyan]grunt serve[/cyan]          запустити сервер")
    console.print("  [cyan]grunt auth login[/cyan]     авторизуватись для CLI команд")
