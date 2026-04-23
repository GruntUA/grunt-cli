"""grunt init — ініціалізація bench або сайту."""

from __future__ import annotations

import re
import secrets
import subprocess
from pathlib import Path

import click

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

def _create_user_direct(grunt_dir: Path, site_dir: Path, email: str, password: str, full_name: str) -> None:
    """Створює користувача напрямо в БД через backend grunt CLI (без запущеного сервера)."""
    import os  # noqa: PLC0415

    venv_grunt = grunt_dir / ".venv" / "bin" / "grunt"
    if not venv_grunt.exists():
        console.print("[red]✗[/red] Backend CLI не знайдено. Запусти [cyan]mise run deps[/cyan]")
        return

    env_path = site_dir / ".env"
    result = subprocess.run(
        [str(venv_grunt), "users", "create",
         "--email", email, "--password", password, "--full-name", full_name],
        cwd=str(grunt_dir),
        env={**os.environ, "DOTENV_PATH": str(env_path)},
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        console.print(f"[green]✓[/green] Адміністратор {email} створений")
    else:
        output = (result.stdout + result.stderr).strip()
        if "вже існує" in output or "already exists" in output:
            console.print(f"[yellow]~[/yellow] Користувач {email} вже існує")
        else:
            console.print(f"[red]✗[/red] Помилка створення користувача:")
            if output:
                console.print(f"[dim]{output}[/dim]")
            console.print(f"   Запусти вручну: [cyan]grunt users create[/cyan]")


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

    # 2. Setup (Sync dependencies + Bootstrap + Migrate)
    backend_dir = grunt_dir / "backend"
    if backend_dir.exists():
        console.print("[dim]Налаштування середовища та бази даних...[/dim]")
        ok = run_mise(
            grunt_dir,
            "setup",
            env={"DOTENV_PATH": str(site_dir / ".env")}
        )
        if not ok:
            console.print("[red]✗[/red] Ініціалізація сайту не завершилась")
            raise SystemExit(1)

    # 3. Адміністратор — створюємо напряму в БД через backend CLI
    console.print()
    if click.confirm("Створити адміністратора?", default=True):
        email = click.prompt("  Email", default="admin@example.com")
        password = click.prompt("  Пароль", hide_input=True, confirmation_prompt=True)
        full_name = click.prompt("  Повне ім'я", default="Адміністратор")
        _create_user_direct(grunt_dir, site_dir, email, password, full_name)

    # 4. Фінал
    console.print()
    console.print("[bold green]✅ Ґрунт ініціалізовано![/bold green]")
    console.print()
    console.print("Наступні кроки:")
    console.print("  [cyan]grunt serve[/cyan]          запустити сервер")
    console.print("  [cyan]grunt auth login[/cyan]     авторизуватись для CLI команд")
