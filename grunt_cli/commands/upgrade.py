"""grunt upgrade — оновлення залежностей до найновіших версій з оновленням файлів версій."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import click

from grunt_cli import helpers
from grunt_cli.commands.restart import installed_units
from grunt_cli.commands.update import (
    _MANAGED_RCLONE,
    _cleanup_runtimes,
    _find_apps_dir,
    _get_cli_dir,
    _print_cleanup_summary,
    _project_uv,
    _restart_production,
    _run_migrations,
    _runtime_dir,
    _step,
)
from grunt_cli.helpers import (
    FRAMEWORK_CLI_MODULE,
    console,
    find_uv,
    get_bench_dir,
    get_mise_bin,
    run_captured,
    run_mise,
)

DEP_PATTERN = re.compile(
    r"""(?P<prefix>["'])(?P<pkg>[A-Za-z0-9_.\-]+)(?P<extras>\[[^\]]+\])?(?P<op>>=|==|~=)(?P<ver>[^"',\s]+)(?P<suffix>["'])"""
)


def _canon(name: str) -> str:
    """PEP 503 канонічна назва пакета."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _update_pyproject_deps(
    pyproject_path: Path, locked_versions: dict[str, str], dry_run: bool = False
) -> list[str]:
    """Оновити версії залежностей у pyproject.toml відповідно до locked_versions,
    зберігаючи коментарі, відступи та extras."""
    if not pyproject_path.exists():
        return []

    content = pyproject_path.read_text(encoding="utf-8")
    changes: list[str] = []

    def _replace(m: re.Match) -> str:
        prefix = m.group("prefix")
        pkg_raw = m.group("pkg")
        extras = m.group("extras") or ""
        op = m.group("op")
        old_ver = m.group("ver")
        suffix = m.group("suffix")

        new_ver = locked_versions.get(_canon(pkg_raw))
        if new_ver and new_ver != old_ver:
            changes.append(f"{pkg_raw}: {old_ver} → {new_ver}")
            return f"{prefix}{pkg_raw}{extras}{op}{new_ver}{suffix}"
        return m.group(0)

    new_content = DEP_PATTERN.sub(_replace, content)
    if changes and not dry_run:
        pyproject_path.write_text(new_content, encoding="utf-8")
    return changes


def _update_mise_toml(
    mise_path: Path,
    node_ver: str | None = None,
    python_ver: str | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Оновити версії node та python у mise.toml, зберігаючи форматування."""
    if not mise_path.exists():
        return []

    content = mise_path.read_text(encoding="utf-8")
    orig_content = content
    changes: list[str] = []

    if node_ver:

        def _replace_node(m: re.Match) -> str:
            old = m.group(2)
            if old != node_ver:
                changes.append(f"node: {old} → {node_ver}")
                return f"{m.group(1)}{node_ver}{m.group(3)}"
            return m.group(0)

        content = re.sub(r'(\bnode\s*=\s*["\'])([^"\']+)(["\'])', _replace_node, content)

    if python_ver:

        def _replace_python(m: re.Match) -> str:
            old = m.group(2)
            if old != python_ver:
                changes.append(f"python: {old} → {python_ver}")
                return f"{m.group(1)}{python_ver}{m.group(3)}"
            return m.group(0)

        content = re.sub(r'(\bpython\s*=\s*["\'])([^"\']+)(["\'])', _replace_python, content)

    if content != orig_content and not dry_run:
        mise_path.write_text(content, encoding="utf-8")
    return changes


def _update_package_json_engines(
    pkg_path: Path, node_major: str, dry_run: bool = False
) -> list[str]:
    """Оновити engines.node у package.json."""
    if not pkg_path.exists():
        return []
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    changes: list[str] = []
    engines = data.get("engines", {})
    if "node" in engines:
        curr = engines["node"]
        target = f">={node_major}.0.0"
        if curr != target:
            changes.append(f"engines.node: {curr} → {target}")
            engines["node"] = target
            if not dry_run:
                pkg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return changes


def _get_latest_node_version() -> tuple[str | None, str | None]:
    """Отримати найновішу версію Node.js через mise ls-remote node.

    Повертає (повна_версія, мажорна_версія), наприклад ('26.11.1', '26').
    """
    mise_bin = get_mise_bin()
    if not mise_bin:
        return None, None
    try:
        out = subprocess.run(
            [mise_bin, "ls-remote", "node"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        ).stdout
        versions = [v.strip() for v in out.splitlines() if re.match(r"^\d+\.\d+\.\d+$", v.strip())]
        if versions:
            latest = versions[-1]
            major = latest.split(".")[0]
            return latest, major
    except (OSError, subprocess.SubprocessError):
        pass
    return None, None


def _get_latest_python_version() -> tuple[str | None, str | None]:
    """Отримати найновішу версію CPython через uv python list.

    Повертає (повна_версія, мінорна_версія), наприклад ('3.15.0', '3.15').
    """
    uv_bin = _project_uv() or find_uv()
    if not uv_bin:
        return None, None
    try:
        out = subprocess.run(
            [uv_bin, "python", "list"], capture_output=True, text=True, check=False, timeout=30
        ).stdout
        versions = {
            m.group(1)
            for line in out.splitlines()
            if "freethreaded" not in line
            for m in [re.search(r"cpython-(\d+\.\d+\.\d+)", line)]
            if m
        }
        if versions:
            sorted_vers = sorted(versions, key=lambda v: tuple(map(int, v.split("."))))
            latest = sorted_vers[-1]
            minor = ".".join(latest.split(".")[:2])
            return latest, minor
    except (OSError, subprocess.SubprocessError):
        pass
    return None, None


def _upgrade_runtimes(dry_run: bool = False) -> None:
    """Оновити mise, uv, Node.js, Python, rclone та відповідні файли версій."""
    console.print("[bold cyan]Системні залежності[/bold cyan]")

    # 1. mise
    mise_bin = get_mise_bin()
    if not mise_bin:
        console.print("  [yellow]⚠[/yellow]  mise не знайдено, пропускаю")
    else:
        if dry_run:
            console.print("  [dim][dry-run] mise self-update[/dim]")
        else:
            _step([mise_bin, "self-update", "--yes"], "mise оновлено", quiet=True)

    # 2. uv
    uv_bin = _project_uv() or find_uv()
    if mise_bin:
        runtime_dir = _runtime_dir() or Path.home()
        if dry_run:
            console.print("  [dim][dry-run] mise upgrade uv[/dim]")
        else:
            run_mise(runtime_dir, "upgrade", "uv", quiet=True)
            run_mise(runtime_dir, "install", "uv@latest", quiet=True)
            console.print("  [green]✓[/green] uv оновлено через mise")
    elif uv_bin:
        if dry_run:
            console.print("  [dim][dry-run] uv self update[/dim]")
        else:
            _step([uv_bin, "self", "update"], "uv оновлено", quiet=True)

    # 3. rclone
    rclone_bin = None
    if os.access(_MANAGED_RCLONE, os.X_OK):
        rclone_bin = str(_MANAGED_RCLONE)
    else:
        rclone_bin = shutil.which("rclone")

    if rclone_bin:
        if dry_run:
            console.print("  [dim][dry-run] rclone selfupdate[/dim]")
        else:
            _step([rclone_bin, "selfupdate"], "rclone оновлено", quiet=True)
    else:
        console.print("  [dim]rclone не знайдено[/dim]")

    # 4. Node.js (оновлення версії в mise.toml та встановлення)
    latest_node, node_major = _get_latest_node_version()
    if node_major and mise_bin:
        # Шукаємо всі mise.toml файли
        mise_configs: list[Path] = []
        runtime_dir = _runtime_dir()
        if runtime_dir and (runtime_dir / "mise.toml").is_file():
            mise_configs.append(runtime_dir / "mise.toml")
        cli_dir = _get_cli_dir()
        if cli_dir and (cli_dir / "mise.toml").is_file():
            mise_configs.append(cli_dir / "mise.toml")
        global_mise = Path.home() / ".config/mise/config.toml"
        if global_mise.is_file():
            mise_configs.append(global_mise)

        for cfg in mise_configs:
            changes = _update_mise_toml(cfg, node_ver=node_major, dry_run=dry_run)
            if changes:
                console.print(f"  [green]✓[/green] {cfg.name}: {', '.join(changes)}")

        # Оновлення engines.node у package.json
        if runtime_dir and (runtime_dir / "package.json").is_file():
            changes = _update_package_json_engines(
                runtime_dir / "package.json", node_major, dry_run=dry_run
            )
            if changes:
                console.print(f"  [green]✓[/green] package.json: {', '.join(changes)}")

        if dry_run:
            console.print(f"  [dim][dry-run] mise install node@{latest_node}[/dim]")
        else:
            status = f"Встановлюю Node.js {latest_node} (mise)..."
            if run_mise(
                runtime_dir or Path.cwd(),
                "install",
                f"node@{latest_node}",
                status=status,
                quiet=True,
            ):
                subprocess.run(
                    [mise_bin, "use", "-g", f"node@{node_major}"], check=False, capture_output=True
                )
                console.print(f"  [green]✓[/green] Node.js оновлено до {latest_node}")
            else:
                console.print("  [yellow]⚠[/yellow]  Не вдалося встановити Node.js через mise")

    # 5. Python (оновлення патчу/версії)
    if uv_bin:
        latest_py, py_minor = _get_latest_python_version()
        if dry_run:
            console.print("  [dim][dry-run] uv python upgrade[/dim]")
        else:
            _step([uv_bin, "python", "upgrade"], "Python оновлено", quiet=True)
            if py_minor:
                # Оновлюємо версію в mise.toml якщо змінився мінор
                cli_dir = _get_cli_dir()
                if cli_dir and (cli_dir / "mise.toml").is_file():
                    changes = _update_mise_toml(
                        cli_dir / "mise.toml", python_ver=py_minor, dry_run=dry_run
                    )
                    if changes:
                        console.print(
                            f"  [green]✓[/green] {cli_dir.name}/mise.toml: {', '.join(changes)}"
                        )
                if mise_bin:
                    subprocess.run(
                        [mise_bin, "use", "-g", f"python@{latest_py}"],
                        check=False,
                        capture_output=True,
                    )


def _upgrade_node_packages(dry_run: bool = False) -> None:
    """Оновити package.json та npm пакети до найновіших версій через npm-check-updates."""
    console.print("[bold cyan]Node.js пакети (package.json)[/bold cyan]")
    apps_dir = _find_apps_dir()
    if not apps_dir or not apps_dir.exists():
        console.print("  [dim]Директорію додатків не знайдено[/dim]")
        return

    # Знаходимо директорії з package.json (наприклад, apps/grunt)
    targets: list[Path] = []
    for root, dirs, files in os.walk(apps_dir):
        # Пропускаємо node_modules, .cache, .git
        dirs[:] = [d for d in dirs if d not in {"node_modules", ".cache", ".git", ".venv", "dist"}]
        if "package.json" in files:
            targets.append(Path(root))

    if not targets:
        console.print("  [dim]package.json не знайдено[/dim]")
        return

    mise = get_mise_bin()
    exec_prefix = [mise, "exec", "--"] if mise else []

    for target in targets:
        rel_path = (
            target.relative_to(apps_dir.parent) if apps_dir.parent in target.parents else target
        )
        console.print(f"  [dim]Перевіряю {rel_path}/package.json...[/dim]")

        # 1. Запуск ncu для аналізу та оновлення package.json
        cmd = [*exec_prefix, "npx", "-y", "npm-check-updates", "--jsonUpgraded"]
        if not dry_run:
            cmd.append("-u")

        status = f"Оновлюю версії у {target.name}/package.json (ncu)..."
        try:
            with console.status(f"[dim]{status}[/dim]", spinner="dots"):
                res = subprocess.run(
                    cmd, cwd=target, capture_output=True, text=True, check=False, timeout=120
                )
            output = res.stdout.strip()
            start = output.find("{")
            end = output.rfind("}")
            upgrades: dict[str, str] = {}
            if start != -1 and end != -1:
                upgrades = json.loads(output[start : end + 1])
        except Exception as e:
            console.print(f"  [yellow]⚠[/yellow]  {rel_path}: помилка ncu: {e}")
            continue

        if not upgrades:
            console.print(f"  [green]✓[/green] {rel_path}: всі пакети в package.json вже найновіші")
            continue

        count = len(upgrades)
        console.print(f"  [yellow]![/yellow] {rel_path}: оновлено [bold]{count}[/bold] пакетів:")
        for pkg, new_ver in list(upgrades.items())[:12]:
            console.print(f"    [cyan]{pkg}[/cyan] → [green]{new_ver}[/green]")
        if len(upgrades) > 12:
            console.print(f"    [dim]… і ще {len(upgrades) - 12} пакетів[/dim]")

        if dry_run:
            console.print("  [dim][dry-run] npm install пропущено[/dim]")
        else:
            # 2. Встановлення нових пакетів і оновлення package-lock.json
            inst_status = f"Встановлюю пакети та оновлюю package-lock.json ({rel_path})..."
            npm_res = run_captured([*exec_prefix, "npm", "install"], cwd=target, status=inst_status)
            if npm_res == 0:
                console.print(
                    f"  [green]✓[/green] {rel_path}: package.json та package-lock.json оновлено"
                )
            else:
                console.print(
                    f"  [yellow]⚠[/yellow]  {rel_path}: npm install завершився з кодом {npm_res}"
                )


def _upgrade_python_packages(dry_run: bool = False) -> None:
    """Оновити pyproject.toml, uv.lock та Python пакети до найновіших версій."""
    console.print("[bold cyan]Python пакети (pyproject.toml + uv.lock)[/bold cyan]")
    apps_dir = _find_apps_dir()
    if not apps_dir or not (apps_dir / "grunt").exists():
        console.print("  [dim]Фреймворк grunt не знайдено[/dim]")
        return

    framework_dir = apps_dir / "grunt"
    uv_bin = _project_uv() or find_uv()
    if not uv_bin:
        console.print("  [yellow]⚠[/yellow]  uv не знайдено")
        return

    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["PWD"] = str(framework_dir)

    # 1. uv lock --upgrade
    lock_cmd = [uv_bin, "lock", "--upgrade"]
    if dry_run:
        lock_cmd.append("--dry-run")

    status = "Оновлюю uv.lock до найновіших версій пакетів..."
    if run_captured(lock_cmd, cwd=framework_dir, env=env, status=status) != 0:
        console.print("  [yellow]⚠[/yellow]  uv lock --upgrade завершився з помилкою")
        return

    # 2. Читання оновленого uv.lock та оновлення pyproject.toml
    lock_file = framework_dir / "uv.lock"
    if lock_file.exists():
        import tomllib

        lock_data = tomllib.loads(lock_file.read_text(encoding="utf-8"))
        locked = {
            _canon(p["name"]): p["version"]
            for p in lock_data.get("package", [])
            if "name" in p and "version" in p
        }

        changes = _update_pyproject_deps(framework_dir / "pyproject.toml", locked, dry_run=dry_run)
        if changes:
            cnt = len(changes)
            console.print(f"  [yellow]![/yellow] grunt: оновлено [bold]{cnt}[/bold] залежностей:")
            for c in changes[:12]:
                console.print(f"    [dim]{c}[/dim]")
            if len(changes) > 12:
                console.print(f"    [dim]… і ще {len(changes) - 12}[/dim]")
            console.print("  [green]✓[/green] grunt/pyproject.toml та uv.lock оновлено")
        else:
            console.print("  [green]✓[/green] grunt: всі залежності найновіших версій")

    # 3. Синхронізація venv
    if dry_run:
        console.print("  [dim][dry-run] uv sync пропущено[/dim]")
    else:
        sync_status = "Синхронізую Python пакети (uv sync --all-extras --inexact)..."
        if (
            run_captured(
                [uv_bin, "sync", "--all-extras", "--inexact"],
                cwd=framework_dir,
                env=env,
                status=sync_status,
            )
            == 0
        ):
            console.print("  [green]✓[/green] Python пакети фреймворку оновлені")
        else:
            console.print("  [yellow]⚠[/yellow]  uv sync завершився з помилкою")

    # 4. Оновлення залежностей додатків (grunt app deps --upgrade)
    if not dry_run:
        deps_status = "Оновлюю залежності додатків (grunt app deps --upgrade)..."
        run_captured(
            [
                uv_bin,
                "run",
                "python",
                "-m",
                FRAMEWORK_CLI_MODULE,
                "app",
                "deps",
                "--upgrade",
            ],
            cwd=framework_dir,
            env=env,
            status=deps_status,
        )

    # 5. Оновлення pyproject.toml встановлених додатків
    venv_python = framework_dir / ".venv" / "bin" / "python"
    if venv_python.exists():
        script = (
            "import importlib.metadata, json; "
            "print(json.dumps({d.metadata['Name'].lower(): d.version "
            "for d in importlib.metadata.distributions()}))"
        )
        dist_cmd = [str(venv_python), "-c", script]
        res = subprocess.run(dist_cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0:
            installed = json.loads(res.stdout or "{}")
            for app_dir in sorted(apps_dir.iterdir()):
                if app_dir.is_dir() and app_dir.name != "grunt":
                    pyproject = app_dir / "pyproject.toml"
                    if pyproject.exists():
                        app_changes = _update_pyproject_deps(pyproject, installed, dry_run=dry_run)
                        if app_changes:
                            n_chg = len(app_changes)
                            console.print(f"  [green]✓[/green] {app_dir.name}: оновлено {n_chg}")


def _upgrade_cli_itself(dry_run: bool = False) -> None:
    """Оновити залежності самого grunt-cli та перевстановити його."""
    console.print("[bold cyan]CLI (grunt-cli)[/bold cyan]")
    cli_dir = _get_cli_dir()
    if not cli_dir or not (cli_dir / "pyproject.toml").exists():
        console.print("  [dim]Директорію grunt-cli не знайдено, пропускаю[/dim]")
        return

    uv_bin = find_uv() or "uv"
    if not dry_run:
        status = "Оновлюю uv.lock для grunt-cli..."
        run_captured([uv_bin, "lock", "--upgrade"], cwd=cli_dir, status=status)

    lock_file = cli_dir / "uv.lock"
    if lock_file.exists():
        import tomllib

        lock_data = tomllib.loads(lock_file.read_text(encoding="utf-8"))
        locked = {
            _canon(p["name"]): p["version"]
            for p in lock_data.get("package", [])
            if "name" in p and "version" in p
        }
        changes = _update_pyproject_deps(cli_dir / "pyproject.toml", locked, dry_run=dry_run)
        if changes:
            console.print(
                f"  [green]✓[/green] grunt-cli/pyproject.toml: оновлено {len(changes)} залежностей"
            )

    if dry_run:
        console.print("  [dim][dry-run] Перевстановлення grunt-cli пропущено[/dim]")
    else:
        run_captured([uv_bin, "sync"], cwd=cli_dir, status="Синхронізую venv grunt-cli...")
        run_captured(
            [uv_bin, "tool", "install", "--editable", ".", "--force"],
            cwd=cli_dir,
            status="Перевстановлюю grunt-cli...",
        )
        console.print("  [green]✓[/green] grunt-cli актуалізовано")


_UPGRADE_COMPONENTS = ("all", "runtimes", "packages", "python", "node")


@click.command()
@click.argument("component", required=False, type=click.Choice(_UPGRADE_COMPONENTS), default="all")
@click.option(
    "--dry-run",
    "-n",
    is_flag=True,
    default=False,
    help="Показати, що буде оновлено, без внесення змін у файли",
)
@click.option(
    "--skip-runtimes",
    is_flag=True,
    default=False,
    help="Не оновлювати системні рантайми (mise, uv, node, python, rclone)",
)
@click.option(
    "--skip-packages",
    is_flag=True,
    default=False,
    help="Не оновлювати пакети Python та Node.js",
)
@click.option(
    "--skip-python",
    is_flag=True,
    default=False,
    help="Не оновлювати Python та його пакети",
)
@click.option(
    "--skip-node",
    "--skip-npm",
    "skip_node",
    is_flag=True,
    default=False,
    help="Не оновлювати Node.js та npm пакети",
)
@click.option(
    "--skip-cli",
    is_flag=True,
    default=False,
    help="Не оновлювати сам grunt-cli",
)
@click.option(
    "--skip-migrate",
    is_flag=True,
    default=False,
    help="Не запускати міграції БД після оновлення",
)
@click.option(
    "--keep-old",
    is_flag=True,
    default=False,
    help="Не видаляти старі версії рантаймів і не чистити кеші",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    help="Повний вивід підпроцесів замість стислого",
)
def upgrade(
    component: str,
    dry_run: bool,
    skip_runtimes: bool,
    skip_packages: bool,
    skip_python: bool,
    skip_node: bool,
    skip_cli: bool,
    skip_migrate: bool,
    keep_old: bool,
    verbose: bool,
) -> None:
    """⚡ Оновити всі залежності до найновіших версій.

    \b
    Оновлює до найновіших версій:
      • Системні інструменти: mise, uv, Node.js, Python, rclone
      • Файли конфігурації версій: mise.toml, package.json, pyproject.toml
      • Lock-файли та пакети: uv.lock, package-lock.json
      • Залежності всіх додатків проєкту та самого grunt-cli

    \b
    Приклади:
      grunt upgrade                 оновити все
      grunt upgrade --dry-run       подивитися, які версії оновляться
      grunt upgrade runtimes        тільки системні інструменти (uv, mise, node, python, rclone)
      grunt upgrade packages        тільки пакети та їхні файли версій
      grunt upgrade python          тільки Python і його пакети
      grunt upgrade node            тільки Node.js та npm пакети
      grunt upgrade --skip-migrate  без міграцій БД
    """
    helpers.VERBOSE = verbose

    console.print("[bold]⚡ Grunt Upgrade — Оновлення залежностей до найновіших версій[/bold]")
    if dry_run:
        console.print("  [yellow]Режим перегляду (--dry-run): файли не будуть змінені[/yellow]")
    console.print()

    bench = get_bench_dir()
    production = bool(bench and installed_units(bench))

    do_runtimes = not skip_runtimes and component in ("all", "runtimes")
    do_python = (
        not skip_python
        and not (skip_packages and component == "all")
        and component in ("all", "packages", "python")
    )
    do_node = (
        not skip_node
        and not (skip_packages and component == "all")
        and component in ("all", "packages", "node")
    )
    do_cli = not skip_cli and component in ("all",)

    # 1. Системні рантайми (mise, uv, node, python, rclone)
    if do_runtimes:
        _upgrade_runtimes(dry_run=dry_run)
        console.print()

    # 2. Node.js пакети & package.json
    if do_node:
        _upgrade_node_packages(dry_run=dry_run)
        console.print()

    # 3. Python пакети & pyproject.toml + uv.lock
    if do_python:
        _upgrade_python_packages(dry_run=dry_run)
        console.print()

    # 4. Сам grunt-cli
    if do_cli:
        _upgrade_cli_itself(dry_run=dry_run)
        console.print()

    # 5. Міграції БД
    migrated = True
    if not skip_migrate and not dry_run and (do_python or do_node):
        console.print("[bold cyan]Міграція БД[/bold cyan]")
        migrated = _run_migrations(None)
        console.print()

    # 6. Перезапуск сервісів (якщо прод)
    if production and not dry_run:
        console.print("[bold cyan]Перезапуск сервісів[/bold cyan]")
        _restart_production(migrated)
        console.print()

    # 7. Прибирання старих рантаймів
    if not keep_old and not dry_run and do_runtimes:
        console.print("[bold cyan]Прибирання[/bold cyan]")
        removed, kept, notes = _cleanup_runtimes()
        if not removed and not kept:
            console.print("  [green]✓[/green] Старих версій рантаймів немає")
        else:
            _print_cleanup_summary(removed, kept, notes)
        console.print()

    console.print("[bold green]✅ Grunt Upgrade завершено[/bold green]")
