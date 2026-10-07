"""grunt update — оновлення CLI, фреймворку та додатків через git."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click

from grunt_cli.commands.restart import installed_units, restart_units
from grunt_cli.helpers import (
    ask_github_token,
    console,
    find_uv,
    get_bench_dir,
    get_current_site,
    get_site_dir,
    github_repo_path,
    run_mise,
    venv_delegate,
)


def _git_pull(path: Path, label: str) -> bool:
    """Виконує git fetch + rebase у вказаній директорії. Повертає True якщо успішно."""
    if not (path / ".git").exists():
        console.print(f"  [yellow]⚠[/yellow]  {label}: не є git-репозиторієм, пропускаю")
        return False

    # Перевіряємо поточну гілку
    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(path),
        capture_output=True,
        text=True,
    )
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "?"

    # Зберігаємо поточний коміт для порівняння
    old_hash = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(path),
        capture_output=True,
        text=True,
    ).stdout.strip()

    console.print(f"  [dim]Оновлюю {label} ({branch})...[/dim]")

    # Без інтерактивного запиту логіна від git — токен питаємо самі.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=str(path), capture_output=True, text=True
    ).stdout.strip()
    github_path = github_repo_path(remote)

    # fetch + rebase на @{upstream} замість git pull: pull бере ціль з
    # .git/FETCH_HEAD, а паралельний fetch (напр. autofetch у VS Code) дописує
    # туди дублікат — і pull падає з "Cannot rebase onto multiple branches".
    for attempt in range(2):
        result = subprocess.run(
            ["git", "fetch"],
            cwd=str(path),
            env=env,
            capture_output=True,
            text=True,
        )
        auth_error = result.returncode != 0 and any(
            marker in result.stderr.lower()
            for marker in ("could not read username", "authentication failed", "not found")
        )
        if not (auth_error and attempt == 0 and github_path and sys.stdin.isatty()):
            break
        if not ask_github_token(github_path):
            break

    if result.returncode == 0:
        result = subprocess.run(
            ["git", "rebase", "--autostash", "@{upstream}"],
            cwd=str(path),
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 and any(
            (path / ".git" / d).exists() for d in ("rebase-merge", "rebase-apply")
        ):
            # Конфлікт — повертаємо репозиторій у стан до оновлення.
            subprocess.run(
                ["git", "rebase", "--abort"], cwd=str(path), capture_output=True, text=True
            )

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout).strip()
        if auth_error:
            console.print(f"  [yellow]⚠[/yellow]  {label}: немає доступу до {remote}")
            console.print(
                "    [dim]Запустіть grunt update у терміналі — він запитає токен GitHub[/dim]"
            )
        else:
            console.print(f"  [red]✗[/red] {label}: помилка оновлення з git")
            if stderr:
                console.print(f"    [dim]{stderr}[/dim]")
        return False

    new_hash = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(path),
        capture_output=True,
        text=True,
    ).stdout.strip()

    if old_hash == new_hash:
        console.print(f"  [green]✓[/green] {label}: вже актуальний ({old_hash})")
    else:
        console.print(f"  [green]✓[/green] {label}: оновлено {old_hash} → {new_hash}")

        # Відображення статистики змін
        diff_result = subprocess.run(
            ["git", "diff", "--stat", f"{old_hash}..{new_hash}"],
            cwd=str(path),
            capture_output=True,
            text=True,
        )
        if diff_result.returncode == 0:
            stats = diff_result.stdout.strip()
            if stats:
                import re  # noqa: PLC0415

                for line in stats.splitlines():
                    line = line.strip()
                    if "changed" in line and ("insertion" in line or "deletion" in line):
                        # Підсвічуємо підсумок: (+) зеленим, (-) червоним
                        line = line.replace("(+)", "[green](+)[/green]")
                        line = line.replace("(-)", "[red](-)[/red]")
                        console.print(f"    [cyan]{line}[/cyan]")
                    else:
                        # Підсвічуємо гістограму: + зеленим, - червоним
                        if "|" in line:
                            path_part, stats_part = line.rsplit("|", 1)
                            stats_part = re.sub(r"(\++)", r"[green]\1[/green]", stats_part)
                            stats_part = re.sub(r"(-+)", r"[red]\1[/red]", stats_part)
                            line = f"{path_part}|{stats_part}"
                        console.print(f"    [dim]{line}[/dim]")

    return True


# npm без package-lock.json: не читає і не переписує його (він під git).
_NPM_NO_LOCK_ENV = {"npm_config_package_lock": "false"}
_NPM_DEP_KEYS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")


def _package_lock_stale(path: Path) -> bool:
    """package-lock.json не відповідає package.json.

    Буває, коли в апстрімі підняли версії в package.json, а lock не
    перегенерували: npm install тоді падає з ERESOLVE на точних peer-версіях.
    """
    import json  # noqa: PLC0415

    try:
        pkg = json.loads((path / "package.json").read_text())
        lock = json.loads((path / "package-lock.json").read_text())
    except (OSError, ValueError):
        return False
    root = lock.get("packages", {}).get("", {})
    return any(pkg.get(k, {}) != root.get(k, {}) for k in _NPM_DEP_KEYS)


def _warn_stale_lock(label: str) -> None:
    console.print(
        f"  [yellow]⚠[/yellow]  {label}: package-lock.json не синхронізований з package.json"
        " — npm встановлює пакети без нього"
    )


def _install_deps(path: Path, label: str) -> None:
    """Встановлює залежності через mise."""
    console.print(f"  [dim]Оновлюю рантайми для {label}...[/dim]")
    run_mise(path, "install")

    mise_toml = path / "mise.toml"
    if mise_toml.exists():
        import tomllib  # noqa: PLC0415

        with mise_toml.open("rb") as f:
            tasks = tomllib.load(f).get("tasks", {})
        if "deps" in tasks:
            console.print(f"  [dim]Встановлюю пакети для {label} (mise run deps)...[/dim]")
            # deps-задача сама викликає npm install — із застарілим lock вона б упала.
            env = None
            if _package_lock_stale(path):
                _warn_stale_lock(label)
                env = _NPM_NO_LOCK_ENV
            run_mise(path, "run", "deps", env=env)


def _update_runtimes() -> None:
    """Оновити системні рантайми (Python, Node.js тощо) через mise."""
    import shutil  # noqa: PLC0415

    # Спочатку шукаємо mise у поточному середовищі
    mise_bin = shutil.which("mise")
    if not mise_bin:
        console.print("  [yellow]⚠[/yellow]  mise не знайдено, пропускаю оновлення рантаймів")
        return

    bench = get_bench_dir()
    if bench:
        config_file = bench / "apps" / "grunt" / "mise.toml"
        if config_file.exists():
            console.print("  [dim]Оновлюю системні рантайми (Python, Node.js тощо)...[/dim]")
            result = subprocess.run([mise_bin, "install"], cwd=str(bench), check=False)
            if result.returncode == 0:
                console.print("  [green]✓[/green] Системні рантайми оновлені")
            else:
                console.print("  [yellow]⚠[/yellow]  Оновлення рантаймів завершилось з помилкою")
            return

    site = get_site_dir()
    if site and (site / "mise.toml").exists():
        console.print("  [dim]Оновлюю системні рантайми (Python, Node.js тощо)...[/dim]")
        result = subprocess.run([mise_bin, "install"], cwd=str(site), check=False)
        if result.returncode == 0:
            console.print("  [green]✓[/green] Системні рантайми оновлені")
        else:
            console.print("  [yellow]⚠[/yellow]  Оновлення рантаймів завершилось з помилкою")
    else:
        console.print("  [dim]mise.toml не знайдено[/dim]")


def _update_python_packages() -> None:
    """Оновити Python пакети (uv sync --upgrade або pip)."""
    import os  # noqa: PLC0415
    import shutil  # noqa: PLC0415

    # Перевіряємо наявність uv
    uv_bin = find_uv()
    if uv_bin:
        console.print("  [dim]Оновлюю Python пакети (uv sync --upgrade)...[/dim]")
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        app_dir = _find_apps_dir()
        cwd_dir = str(app_dir / "grunt") if app_dir else None
        if cwd_dir:
            env["PWD"] = cwd_dir
        # --inexact: keep packages outside the framework's lock — the apps
        # (editable) and their dependencies, installed by `grunt app deps`.
        result = subprocess.run(
            [uv_bin, "sync", "--upgrade", "--all-extras", "--inexact"],
            cwd=cwd_dir,
            check=False,
            env=env,
        )
        if result.returncode != 0:
            console.print("  [yellow]⚠[/yellow]  uv sync --upgrade завершився з помилкою")
            return
        apps = subprocess.run(
            [uv_bin, "run", "grunt", "app", "deps"],
            cwd=cwd_dir,
            check=False,
            env=env,
        )
        if apps.returncode != 0:
            console.print(
                "  [yellow]⚠[/yellow]  Залежності додатків не встановились (grunt app deps)"
            )
        else:
            console.print("  [green]✓[/green] Python пакети оновлені (фреймворк + додатки)")
        return

    # Fallback на pip
    pip_bin = shutil.which("pip") or shutil.which("pip3")
    if pip_bin:
        console.print("  [dim]uv не знайдено, оновлюю через pip...[/dim]")
        result = subprocess.run([pip_bin, "install", "--upgrade", "pip"], check=False)
        if result.returncode != 0:
            console.print("  [yellow]⚠[/yellow]  pip update завершився з помилкою")
        else:
            console.print("  [green]✓[/green] Python пакети оновлені")
    else:
        console.print("  [yellow]⚠[/yellow]  Ні uv, ні pip не знайдено")


def _run_npm_install(app_dir: Path) -> None:
    """Встановити npm пакети."""
    import shutil  # noqa: PLC0415

    mise = shutil.which("mise")
    if mise:
        npm_run = [mise, "exec", "--", "npm"]
    else:
        npm = shutil.which("npm")
        if not npm:
            console.print("  [yellow]⚠[/yellow]  npm не знайдено")
            return
        npm_run = [npm]

    console.print(f"  [dim]Встановлюю npm пакети ({app_dir.name})...[/dim]")
    no_lock = [*npm_run, "install", "--no-package-lock"]

    if _package_lock_stale(app_dir):
        # Із застарілим lock звичайний install гарантовано впаде з ERESOLVE —
        # одразу розв'язуємо за package.json. audit fix не запускаємо: він
        # знову поставив би версії з lock.
        _warn_stale_lock(app_dir.name)
    else:
        result = subprocess.run([*npm_run, "install"], cwd=str(app_dir), check=False)
        if result.returncode == 0:
            subprocess.run([*npm_run, "audit", "fix"], cwd=str(app_dir), check=False)
            console.print("  [green]✓[/green] npm пакети встановлені")
            return
        console.print("  [dim]Повторна спроба без package-lock.json...[/dim]")

    if subprocess.run(no_lock, cwd=str(app_dir), check=False).returncode == 0:
        console.print("  [green]✓[/green] npm пакети встановлені (без package-lock.json)")
        return

    # Чиста установка, але старий node_modules відкладаємо, а не видаляємо:
    # якщо й вона впаде, повертаємо його, щоб було з чим зібрати фронтенд.
    nm = app_dir / "node_modules"
    backup = app_dir / "node_modules.bak"
    if nm.exists():
        console.print("  [dim]Чиста установка node_modules, повторна спроба...[/dim]")
        shutil.rmtree(backup, ignore_errors=True)
        nm.rename(backup)
        if subprocess.run(no_lock, cwd=str(app_dir), check=False).returncode == 0:
            shutil.rmtree(backup, ignore_errors=True)
            console.print("  [green]✓[/green] npm пакети встановлені (чиста установка)")
            return
        shutil.rmtree(nm, ignore_errors=True)
        backup.rename(nm)
        console.print("  [dim]Повернуто попередній node_modules[/dim]")

    console.print("  [yellow]⚠[/yellow]  npm install завершився з помилкою")


def _run_migrations(site: str | None) -> bool:
    """Повна ``grunt migrate`` фреймворку: Alembic + DocType-таблиці + fixtures.

    Окремим процесом із venv проєкту — там уже новий код після git pull.
    """
    if get_current_site() is None:
        console.print("  [yellow]⚠[/yellow]  grunt.site не знайдено")
        return False
    code = venv_delegate("migrate", site=site)
    if code == -1:
        console.print("  [yellow]⚠[/yellow]  Backend venv не знайдено (apps/grunt/.venv)")
        return False
    if code != 0:
        console.print("  [yellow]⚠[/yellow]  Міграції завершилися з помилкою")
        return False
    console.print("  [green]✓[/green] Міграції завершені")
    return True


def _restart_production(migrated: bool) -> bool:
    """На проді (є systemd-сервіси проєкту): зібрати фронтенд і перезапустити.

    У розробці нічого не робить — ``grunt serve`` працює з ``--reload``.
    Повертає False, якщо перезапуск не вдався.
    """
    bench = get_bench_dir()
    units = installed_units(bench) if bench else []
    if not units:
        console.print(
            "  [dim]Розробка (сервіси не встановлено): grunt serve підхопить зміни сам;"
            " після оновлення пакетів перезапустіть його[/dim]"
        )
        return True
    if not migrated:
        console.print(
            "  [yellow]⚠[/yellow]  Міграція не вдалася — сервіси НЕ перезапущено. "
            "Виправте й виконайте [cyan]grunt migrate && grunt restart[/cyan]"
        )
        return False

    console.print("  [dim]Збираю фронтенд (mise run build)...[/dim]")
    if not run_mise(bench / "apps" / "grunt", "build"):
        console.print("  [yellow]⚠[/yellow]  Збірка фронтенду не вдалася — сервіси НЕ перезапущено")
        return False
    return restart_units(units)


def _find_bench_dir() -> Path | None:
    """Шукає кореневу директорію bench-проєкту."""
    return get_bench_dir()


def _find_apps_dir() -> Path | None:
    """Повертає директорію apps/."""
    bench = get_bench_dir()
    if bench:
        return bench / "apps"
    site = get_site_dir()
    if site and (site / "apps").is_dir():
        return site / "apps"
    return None


def _get_cli_dir() -> Path | None:
    """Повертає директорію grunt-cli (editable install)."""
    # Спочатку перевіряємо стандартне розташування
    default_dir = Path.home() / ".grunt-cli"
    if (default_dir / ".git").exists():
        return default_dir

    # Fallback: шукаємо через uv
    uv_bin = find_uv()
    if uv_bin:
        result = subprocess.run(
            [uv_bin, "pip", "show", "grunt-cli"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
    else:
        return None

    for line in result.stdout.splitlines():
        if line.startswith("Editable project location:"):
            path = Path(line.split(":", 1)[1].strip())
            if path.exists():
                return path
    return None


_COMPONENTS = ("cli", "framework", "apps", "deps")


@click.command()
@click.argument("component", required=False, type=click.Choice(_COMPONENTS))
@click.option("--cli", "update_cli", is_flag=True, default=False, help="Оновити тільки CLI")
@click.option(
    "--framework", "update_framework", is_flag=True, default=False, help="Оновити тільки фреймворк"
)
@click.option("--apps", "update_apps", is_flag=True, default=False, help="Оновити тільки додатки")
@click.option(
    "--deps",
    "update_deps",
    is_flag=True,
    default=False,
    help="Оновити системні залежності (Python, Node.js тощо)",
)
@click.option("--skip-packages", is_flag=True, default=False, help="Не оновлювати Python пакети")
@click.option("--skip-npm", is_flag=True, default=False, help="Не встановлювати npm пакети")
@click.option("--skip-migrate", is_flag=True, default=False, help="Не запускати міграції БД")
@click.option(
    "--no-deps", is_flag=True, default=False, help="Не встановлювати залежності після оновлення"
)
@click.option(
    "--no-restart",
    is_flag=True,
    default=False,
    help="Не збирати фронтенд і не перезапускати сервіси (прод)",
)
@click.option("--site", default=None, help="Назва сайту (для migrate)")
def update(
    component: str | None,
    update_cli: bool,
    update_framework: bool,
    update_apps: bool,
    update_deps: bool,
    skip_packages: bool,
    skip_npm: bool,
    skip_migrate: bool,
    no_deps: bool,
    no_restart: bool,
    site: str | None,
) -> None:
    """Оновити CLI, фреймворк, додатки, пакети та схему БД.

    \b
    Послідовність:
      1. git fetch + rebase для CLI, фреймворку та додатків
      2. mise install (системні залежності: Python, Node.js тощо)
      3. uv sync --upgrade --inexact + grunt app deps (Python пакети фреймворку й додатків)
      4. npm install
      5. grunt migrate (Alembic + DocType-таблиці + fixtures)
      6. прод (є systemd-сервіси): mise run build + перезапуск сервісів

    \b
    Без прапорців оновлює все.
    З прапорцями — тільки вказані компоненти.

    \b
    Приклади:
      grunt update                  оновити все
      grunt update cli              оновити тільки сам grunt-cli
      grunt update framework        тільки фреймворк (+ пакети, npm, міграції)
      grunt update --deps           оновити тільки системні залежності
      grunt update --apps           тільки додатки + пакети + міграції
      grunt update --skip-migrate   без міграцій БД
      grunt update --no-restart     без збірки фронтенду й перезапуску (прод)
      grunt update --no-deps        без перевстановлення залежностей
    """
    # `grunt update cli` == `grunt update --cli` тощо
    update_cli = update_cli or component == "cli"
    update_framework = update_framework or component == "framework"
    update_apps = update_apps or component == "apps"
    update_deps = update_deps or component == "deps"

    # Якщо жоден прапорець не вказано — оновлюємо все
    update_all = not (update_cli or update_framework or update_apps or update_deps)
    # Лише CLI — пакети, npm і міграції проєкту не чіпаємо (можна й поза проєктом).
    cli_only = update_cli and not (update_framework or update_apps or update_deps)

    console.print("[bold]⚡ Grunt Update[/bold]")
    console.print()

    updated_something = False

    # ── 1. CLI ──────────────────────────────────────────────────────
    if update_all or update_cli:
        console.print("[bold cyan]CLI[/bold cyan]")
        cli_dir = _get_cli_dir()
        if cli_dir is None:
            console.print("  [yellow]⚠[/yellow]  grunt-cli не встановлений як editable, пропускаю")
        else:
            _git_pull(cli_dir, "grunt-cli")
            if not no_deps:
                # editable-встановлення підхоплює код і так, а нові залежності
                # CLI ставить лише перевстановлення (mise-задача install).
                console.print("  [dim]Встановлюю grunt-cli (mise run install)...[/dim]")
                run_mise(cli_dir, "install")
                run_mise(cli_dir, "run", "install")
            updated_something = True
        console.print()

    # ── 2. Framework ────────────────────────────────────────────────
    if update_all or update_framework:
        console.print("[bold cyan]Фреймворк[/bold cyan]")
        apps_dir = _find_apps_dir()
        framework_dir = apps_dir / "grunt" if apps_dir else None

        if framework_dir is None or not framework_dir.exists():
            console.print("  [yellow]⚠[/yellow]  Grunt framework не знайдено")
        else:
            _git_pull(framework_dir, "grunt")
            if not no_deps:
                _install_deps(framework_dir, "grunt")
            updated_something = True
        console.print()

    # ── 3. Apps ─────────────────────────────────────────────────────
    if update_all or update_apps:
        console.print("[bold cyan]Додатки[/bold cyan]")
        apps_dir = _find_apps_dir()

        if apps_dir is None or not apps_dir.exists():
            console.print("  [dim]Директорію додатків не знайдено[/dim]")
        else:
            app_dirs = sorted(
                p
                for p in apps_dir.iterdir()
                if p.is_dir() and p.name != "grunt" and (p / ".git").exists()
            )

            if not app_dirs:
                console.print("  [dim]Немає додатків з git-репозиторієм для оновлення[/dim]")
            else:
                for app_dir in app_dirs:
                    _git_pull(app_dir, app_dir.name)
                    if not no_deps:
                        _install_deps(app_dir, app_dir.name)
                    updated_something = True
        console.print()

    # ── 4. Системні залежності (рантайми) ────────────────────────
    if update_all or update_deps:
        console.print("[bold cyan]Системні залежності[/bold cyan]")
        _update_runtimes()
        updated_something = True
        console.print()

    if cli_only:
        console.print("[bold green]✅ grunt-cli оновлено[/bold green]")
        return

    # ── 5. Python пакети ────────────────────────────────────────────
    if not skip_packages:
        console.print("[bold cyan]Python пакети[/bold cyan]")
        _update_python_packages()
        updated_something = True
        console.print()
    else:
        console.print("[dim]Python пакети пропущено (--skip-packages)[/dim]")
        console.print()

    # ── 6. npm пакети ──────────────────────────────────────────────
    if not skip_npm:
        console.print("[bold cyan]npm пакети[/bold cyan]")
        apps_dir = _find_apps_dir()
        if apps_dir and (apps_dir / "grunt").exists():
            _run_npm_install(apps_dir / "grunt")
            updated_something = True
        else:
            console.print("  [dim]Grunt app директорія не знайдена[/dim]")
        console.print()
    else:
        console.print("[dim]npm пакети пропущено (--skip-npm)[/dim]")
        console.print()

    # ── 7. Міграція БД ──────────────────────────────────────────────
    migrated = True
    if not skip_migrate:
        console.print("[bold cyan]Міграція БД[/bold cyan]")
        migrated = _run_migrations(site)
        updated_something = True
        console.print()
    else:
        console.print("[dim]Міграція БД пропущена (--skip-migrate)[/dim]")
        console.print()

    # ── 8. Перезапуск ───────────────────────────────────────────────
    restarted = True
    if updated_something and not no_restart:
        console.print("[bold cyan]Перезапуск[/bold cyan]")
        restarted = _restart_production(migrated)
        console.print()

    # ── Фінал ───────────────────────────────────────────────────────
    if not updated_something:
        console.print("[yellow]Нічого не оновлено[/yellow]")
    elif restarted:
        console.print("[bold green]✅ Оновлення завершено[/bold green]")
    else:
        console.print("[bold red]✗ Оновлення завершено з помилками[/bold red]")
        raise SystemExit(1)
