"""grunt update — оновлення CLI, фреймворку та додатків через git."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import click

from grunt_cli.commands.restart import installed_units, restart_units
from grunt_cli.helpers import (
    FRAMEWORK_CLI_MODULE,
    ask_github_token,
    console,
    find_uv,
    get_bench_dir,
    get_current_site,
    get_mise_bin,
    get_site_dir,
    github_repo_path,
    run_mise,
    venv_delegate,
)

# Реліз = анотований тег vX.Y.Z (`grunt release` у фреймворку). Пре-релізи
# (v1.2.0-rc1) на прод не ставимо.
_RELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def _git(path: Path, *args: str, env: dict[str, str] | None = None):
    return subprocess.run(["git", *args], cwd=str(path), capture_output=True, text=True, env=env)


def _short_head(path: Path) -> str:
    return _git(path, "rev-parse", "--short", "HEAD").stdout.strip()


def _git_fetch(path: Path, label: str, *args: str) -> bool:
    """``git fetch`` з одним повтором після запиту токена GitHub."""
    # Без інтерактивного запиту логіна від git — токен питаємо самі.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    remote = _git(path, "remote", "get-url", "origin").stdout.strip()
    github_path = github_repo_path(remote)

    for attempt in range(2):
        result = _git(path, "fetch", *args, env=env)
        auth_error = result.returncode != 0 and any(
            marker in result.stderr.lower()
            for marker in ("could not read username", "authentication failed", "not found")
        )
        if not (auth_error and attempt == 0 and github_path and sys.stdin.isatty()):
            break
        if not ask_github_token(github_path):
            break

    if result.returncode == 0:
        return True
    if auth_error:
        console.print(f"  [yellow]⚠[/yellow]  {label}: немає доступу до {remote}")
        console.print(
            "    [dim]Запустіть grunt update у терміналі — він запитає токен GitHub[/dim]"
        )
    else:
        console.print(f"  [red]✗[/red] {label}: помилка оновлення з git")
        stderr = (result.stderr or result.stdout).strip()
        if stderr:
            console.print(f"    [dim]{stderr}[/dim]")
    return False


def _git_pull(path: Path, label: str) -> bool:
    """Виконує git fetch + rebase у вказаній директорії. Повертає True якщо успішно."""
    if not (path / ".git").exists():
        console.print(f"  [yellow]⚠[/yellow]  {label}: не є git-репозиторієм, пропускаю")
        return False

    branch_result = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "?"
    old_hash = _short_head(path)

    console.print(f"  [dim]Оновлюю {label} ({branch})...[/dim]")

    # fetch + rebase на @{upstream} замість git pull: pull бере ціль з
    # .git/FETCH_HEAD, а паралельний fetch (напр. autofetch у VS Code) дописує
    # туди дублікат — і pull падає з "Cannot rebase onto multiple branches".
    if not _git_fetch(path, label):
        return False
    result = _git(path, "rebase", "--autostash", "@{upstream}")
    if result.returncode != 0:
        if any((path / ".git" / d).exists() for d in ("rebase-merge", "rebase-apply")):
            # Конфлікт — повертаємо репозиторій у стан до оновлення.
            _git(path, "rebase", "--abort")
        console.print(f"  [red]✗[/red] {label}: помилка оновлення з git")
        stderr = (result.stderr or result.stdout).strip()
        if stderr:
            console.print(f"    [dim]{stderr}[/dim]")
        return False

    _report_change(path, label, old_hash, _short_head(path))
    return True


def release_tags(path: Path) -> list[str]:
    """Реліз-теги репозиторію, від найновішого."""
    found = {}
    for tag in _git(path, "tag", "--list", "v[0-9]*").stdout.split():
        if m := _RELEASE_TAG.match(tag):
            found[tag] = tuple(int(n) for n in m.groups())
    return sorted(found, key=found.__getitem__, reverse=True)


def _current_tag(path: Path) -> str | None:
    """Реліз-тег, на якому стоїть HEAD (відʼєднаний), або None."""
    if _git(path, "symbolic-ref", "-q", "HEAD").returncode == 0:
        return None  # на гілці
    tags = _git(path, "tag", "--points-at", "HEAD").stdout.split()
    found = [t for t in tags if _RELEASE_TAG.match(t)]
    return found[0] if found else None


def _lost_migrations(path: Path, target: str) -> list[str]:
    """Міграції БД, які є в поточному коді, але відсутні в ``target``.

    Якщо такі є, база вже пройшла міграцію, про яку старий код нічого не знає.
    Відкат коду тут не допоможе, потрібне відновлення бекапу.
    """
    out = _git(
        path,
        "diff",
        "--name-only",
        "--diff-filter=D",
        "HEAD",
        target,
        "--",
        ":(glob)**/migrations/versions/*.py",
    ).stdout
    return sorted(Path(line).stem for line in out.split())


def _git_checkout_tag(path: Path, label: str, tag: str | None, force: bool = False) -> bool:
    """Поставити репозиторій на реліз ``tag`` (None — найновіший)."""
    if not (path / ".git").exists():
        console.print(f"  [yellow]⚠[/yellow]  {label}: не є git-репозиторієм, пропускаю")
        return False
    console.print(f"  [dim]Оновлюю {label} (релізи)...[/dim]")
    if not _git_fetch(path, label, "--tags", "--force"):
        return False

    tags = release_tags(path)
    target = tag or (tags[0] if tags else None)
    if target is None or target not in tags:
        console.print(f"  [red]✗[/red] {label}: немає релізу {target or '(жодного тегу vX.Y.Z)'}")
        return False

    current = _current_tag(path)
    if current == target:
        console.print(f"  [green]✓[/green] {label}: вже на {target}")
        return True
    # Локальні правки на проді не відкладаємо мовчки (як autostash у гілці).
    if _git(path, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        console.print(f"  [red]✗[/red] {label}: є незакомічені зміни — реліз не встановлено")
        return False

    lost = _lost_migrations(path, target)
    if lost and not force:
        console.print(
            f"  [red]✗[/red] {label}: у {target} немає міграцій БД, які вже застосовано: "
            + ", ".join(lost)
        )
        console.print(
            "    [dim]Старий код не працюватиме з такою базою. Спершу відновіть бекап,"
            " зроблений до оновлення (grunt db restore), потім повторіть з --force[/dim]"
        )
        return False

    old_hash = _short_head(path)
    result = _git(path, "checkout", "-q", "--detach", target)
    if result.returncode != 0:
        console.print(f"  [red]✗[/red] {label}: не вдалося перейти на {target}")
        console.print(f"    [dim]{(result.stderr or result.stdout).strip()}[/dim]")
        return False

    was = current or old_hash
    console.print(f"  [green]✓[/green] {label}: {was} → {target}")
    if lost:
        console.print(
            "    [yellow]Відкат повз міграції БД: " + ", ".join(lost) + " (--force)[/yellow]"
        )
    _report_change(path, label, old_hash, _short_head(path), quiet=True)
    return True


def _switch_to_branch(path: Path, label: str) -> bool:
    """Повернути відʼєднаний HEAD (після релізу) на гілку origin/HEAD."""
    if _git(path, "symbolic-ref", "-q", "HEAD").returncode == 0:
        return True
    ref = _git(path, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD").stdout.strip()
    branch = ref.removeprefix("origin/") or "master"
    result = _git(path, "checkout", "-q", branch)
    if result.returncode != 0:
        console.print(f"  [red]✗[/red] {label}: не вдалося перейти на гілку {branch}")
        return False
    console.print(f"  [dim]{label}: повернуто на гілку {branch}[/dim]")
    return True


def _update_repo(
    path: Path,
    label: str,
    *,
    tag: str | None,
    branch: bool,
    production: bool,
    force: bool = False,
) -> bool:
    """Оновити репозиторій: на реліз-тег або на голову гілки.

    \b
    --branch          → гілка
    --tag [vX.Y.Z]    → реліз (без значення — найновіший)
    HEAD уже на тезі  → найновіший реліз
    прод і є релізи   → найновіший реліз
    інакше            → гілка (розробка; репо без тегів)
    """
    if branch:
        return _switch_to_branch(path, label) and _git_pull(path, label)
    has_git = (path / ".git").exists()
    if tag is not None or (has_git and (_current_tag(path) or (production and release_tags(path)))):
        return _git_checkout_tag(path, label, None if tag in (None, "latest") else tag, force)
    return _git_pull(path, label)


def _report_change(
    path: Path, label: str, old_hash: str, new_hash: str, quiet: bool = False
) -> None:
    if old_hash == new_hash:
        if not quiet:
            console.print(f"  [green]✓[/green] {label}: вже актуальний ({old_hash})")
        return
    if not quiet:
        console.print(f"  [green]✓[/green] {label}: оновлено {old_hash} → {new_hash}")

    # Відображення статистики змін
    diff_result = _git(path, "diff", "--stat", f"{old_hash}..{new_hash}")
    stats = diff_result.stdout.strip() if diff_result.returncode == 0 else ""
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


def _install_deps(path: Path, label: str) -> bool:
    """Встановлює залежності через mise; True, якщо відпрацювала задача ``deps``."""
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
            return bool(run_mise(path, "run", "deps", env=env))
    return False


# rclone, який фреймворк сам завантажує, коли на сервері його немає
# (grunt.storage.cloud.rclone.INSTALL_DIR).
_MANAGED_RCLONE = (
    Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "grunt/bin/rclone"
)


def _runtime_dir() -> Path | None:
    """Директорія з mise.toml, де описані рантайми проєкту."""
    bench = get_bench_dir()
    if bench and (bench / "apps" / "grunt" / "mise.toml").exists():
        return bench / "apps" / "grunt"
    site = get_site_dir()
    if site and (site / "mise.toml").exists():
        return site
    return None


def _step(cmd: list[str], label: str, cwd: Path | None = None, quiet: bool = False) -> bool:
    """Один крок оновлення рантаймів: ✓ або ⚠ з останнім рядком помилки."""
    result = subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, capture_output=quiet, text=True, check=False
    )
    if result.returncode == 0:
        console.print(f"  [green]✓[/green] {label}")
        return True
    console.print(f"  [yellow]⚠[/yellow]  {label}: завершилось з помилкою")
    if quiet and (lines := (result.stderr or result.stdout).strip().splitlines()):
        console.print(f"    [dim]{lines[-1]}[/dim]")
    return False


def _update_runtimes() -> None:
    """Оновити mise, рантайми з mise.toml (Node.js, uv), Python і rclone.

    \b
    mise self-update   сам mise (не вийде, якщо він з пакета ОС — тоді через пакетний менеджер)
    mise upgrade       найновіші версії в межах mise.toml (node = "26" → останній 26.x)
    uv python upgrade  найновіший патч Python; venv дивиться на теку мінорної версії
                       (cpython-3.15-…), тож підхоплює його без перестворення
    rclone selfupdate  лише rclone, який завантажив сам фреймворк
    """
    mise_bin = get_mise_bin()
    if not mise_bin:
        console.print("  [yellow]⚠[/yellow]  mise не знайдено, пропускаю оновлення рантаймів")
    else:
        _step([mise_bin, "self-update", "--yes"], "mise оновлено", quiet=True)
        runtime_dir = _runtime_dir()
        if runtime_dir is None:
            console.print("  [dim]mise.toml не знайдено[/dim]")
        else:
            console.print("  [dim]Оновлюю рантайми з mise.toml (Node.js, uv тощо)...[/dim]")
            if run_mise(runtime_dir, "install") and run_mise(runtime_dir, "upgrade"):
                console.print("  [green]✓[/green] Рантайми з mise.toml оновлені")
            else:
                console.print("  [yellow]⚠[/yellow]  Оновлення рантаймів завершилось з помилкою")

    # uv міг щойно оновитися через mise — шукаємо його після.
    uv_bin = find_uv()
    if uv_bin:
        console.print("  [dim]Оновлюю Python (uv python upgrade)...[/dim]")
        _step([uv_bin, "python", "upgrade"], "Python оновлено", quiet=True)

    if os.access(_MANAGED_RCLONE, os.X_OK):
        _step([str(_MANAGED_RCLONE), "selfupdate"], "rclone оновлено", quiet=True)


def _in_use_paths() -> set[str]:
    """Реальні шляхи інтерпретаторів, на які щось спирається: ``home`` кожного
    venv у домашній теці (venv-и фреймворку, додатків, uv tool, свої) та
    виконувані файли запущених процесів (сервер на старому Python ще працює)."""
    used: set[str] = set()
    home = Path.home()
    skip = {"node_modules", ".cache", ".git", ".npm", "site-packages", "dist"}
    for root, dirs, files in os.walk(home):
        depth = len(Path(root).relative_to(home).parts)
        # не заходимо в кеші/залежності; venv лежить не глибше ~/a/b/c/d/.venv
        dirs[:] = [d for d in dirs if d not in skip and depth < 6]
        if "pyvenv.cfg" not in files:
            continue
        try:
            for line in (Path(root) / "pyvenv.cfg").read_text().splitlines():
                key, _, value = line.partition("=")
                if key.strip() == "home" and value.strip():
                    used.add(os.path.realpath(value.strip()))
        except OSError:
            continue
    for exe in Path("/proc").glob("[0-9]*/exe"):
        try:
            used.add(os.path.realpath(exe))
        except OSError:
            continue
    return used


def _cleanup_runtimes() -> None:
    """Прибрати рантайми, які оновлення залишило без діла.

    \b
    uv python   версії, на які не вказує жоден venv і не працює жоден процес
    mise prune  старі версії інструментів mise.toml (node, uv, python) —
                лише їх: rclone та інше, поставлене mise вручну, не чіпаємо
    uv cache prune, npm cache verify — невикористане з кешів
    """
    import json  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    import tomllib  # noqa: PLC0415

    used = _in_use_paths()

    uv_bin = find_uv()
    if uv_bin:
        listed = subprocess.run(
            [uv_bin, "python", "list", "--only-installed", "--output-format", "json"],
            capture_output=True,
            text=True,
        ).stdout
        try:
            installs = json.loads(listed or "[]")
        except ValueError:
            installs = []
        managed = Path.home() / ".local" / "share" / "uv" / "python"
        unused: dict[str, str] = {}
        for py in installs:
            path = os.path.realpath(py.get("path") or "")
            if not path.startswith(f"{managed}/"):
                continue  # системний Python
            install_dir = path.removeprefix(f"{managed}/").split("/", 1)[0]
            in_use = any(u.startswith(f"{managed}/{install_dir}/") for u in used)
            if not in_use:
                unused[py["key"]] = py.get("version") or py["key"]
        for key, version in sorted(unused.items()):
            _step([uv_bin, "python", "uninstall", key], f"Видалено Python {version}", quiet=True)
        subprocess.run([uv_bin, "cache", "prune"], capture_output=True, check=False)

    mise_bin = get_mise_bin()
    if mise_bin:
        tools: set[str] = set()
        runtime_dir = _runtime_dir()
        cli_dir = _get_cli_dir()
        for cfg in (runtime_dir and runtime_dir / "mise.toml", cli_dir and cli_dir / "mise.toml"):
            if cfg and cfg.is_file():
                with cfg.open("rb") as f:
                    tools.update(tomllib.load(f).get("tools", {}))
        installs = Path.home() / ".local" / "share" / "mise" / "installs"
        running = sorted(
            name for name in tools if any(u.startswith(f"{installs}/{name}/") for u in used)
        )
        if running:
            # Старий node/python може тримати запущений процес — його версію
            # не знаємо напевно, тож ці інструменти чистимо наступного разу.
            console.print(f"  [dim]Зараз використовуються, не чищу: {', '.join(running)}[/dim]")
        prune = sorted(tools - set(running))
        if prune:
            _step([mise_bin, "prune", "--yes", *prune], "Старі версії mise прибрано", quiet=True)

    npm = shutil.which("npm")
    if npm:
        subprocess.run([npm, "cache", "verify"], capture_output=True, check=False)


def _update_python_packages(upgrade: bool = False) -> None:
    """Оновити Python пакети (uv sync --locked за uv.lock, без нього --upgrade; або pip).

    *upgrade* (розробка): спершу ``uv lock --upgrade`` — найновіші версії в
    uv.lock, який потім треба закомітити.
    """
    import os  # noqa: PLC0415
    import shutil  # noqa: PLC0415

    # Перевіряємо наявність uv
    uv_bin = find_uv()
    if uv_bin:
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        app_dir = _find_apps_dir()
        cwd_dir = str(app_dir / "grunt") if app_dir else None
        if cwd_dir:
            env["PWD"] = cwd_dir
        # uv.lock під git: ставимо рівно закомічені версії (нові приходять
        # комітом/релізом) і не переписуємо lock — інакше брудне дерево
        # зупинить наступне оновлення. Без lock (старий фреймворк) — --upgrade.
        locked = bool(cwd_dir) and (Path(cwd_dir) / "uv.lock").exists()
        mode = "--locked" if locked else "--upgrade"
        if locked and upgrade:
            console.print("  [dim]Оновлюю uv.lock (uv lock --upgrade)...[/dim]")
            if subprocess.run([uv_bin, "lock", "--upgrade"], cwd=cwd_dir, env=env).returncode:
                console.print("  [yellow]⚠[/yellow]  uv lock --upgrade завершився з помилкою")
                return
        console.print(f"  [dim]Оновлюю Python пакети (uv sync {mode})...[/dim]")
        # --inexact: keep packages outside the framework's lock — the apps
        # (editable) and their dependencies, installed by `grunt app deps`.
        result = subprocess.run(
            [uv_bin, "sync", mode, "--all-extras", "--inexact"],
            cwd=cwd_dir,
            check=False,
            env=env,
        )
        if result.returncode != 0:
            console.print(f"  [yellow]⚠[/yellow]  uv sync {mode} завершився з помилкою")
            return
        apps = subprocess.run(
            [
                uv_bin,
                "run",
                "python",
                "-m",
                FRAMEWORK_CLI_MODULE,
                "app",
                "deps",
                *(["--upgrade"] if upgrade else []),
            ],
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


_UV_UPDATE = re.compile(r"^Update (\S+) v(\S+) -> v(\S+)$", re.M)


def _outdated_packages() -> tuple[list[str], list[str]]:
    """``(оновлення, мажорні)`` пакетів фреймворку й додатків.

    Оновлення — те, що візьме --upgrade-packages: ``uv lock --upgrade``
    (у межах діапазонів, заблоковане чужим піном — ні), пакети лише додатків
    (``grunt app deps --outdated``) і ``npm update`` (wanted). Мажорні — npm
    версії поза діапазонами package.json: їх змінюють руками.
    """
    import json  # noqa: PLC0415
    import shutil  # noqa: PLC0415

    apps_dir = _find_apps_dir()
    grunt_dir = apps_dir / "grunt" if apps_dir else None
    if grunt_dir is None or not grunt_dir.is_dir():
        return [], []

    def output(cmd: list[str]) -> str:
        try:
            result = subprocess.run(cmd, cwd=grunt_dir, capture_output=True, text=True)
        except OSError:
            return ""
        return result.stdout + result.stderr

    # uv та npm — версії з mise.toml фреймворку, а не застарілі з PATH оболонки
    mise = get_mise_bin()
    via_mise = [mise, "exec", "--"] if mise else []
    updates: list[str] = []
    majors: list[str] = []
    if (grunt_dir / "uv.lock").exists():
        uv = [*via_mise, "uv"] if mise else [find_uv() or "uv"]
        plan = output([*uv, "lock", "--upgrade", "--dry-run"])
        updates += [f"{n} {a} → {b}" for n, a, b in _UV_UPDATE.findall(plan)]
    python = grunt_dir / ".venv" / "bin" / "python"
    if python.exists():
        apps = output([str(python), "-m", FRAMEWORK_CLI_MODULE, "app", "deps", "--outdated"])
        updates += [line.strip() for line in apps.splitlines() if " → " in line]
    if (grunt_dir / "node_modules").is_dir():
        npm = [*via_mise, "npm"] if mise else [shutil.which("npm") or "npm"]
        # npm outdated виходить з кодом 1, коли щось застаріло — дивимось лише на JSON
        try:
            outdated = json.loads(
                subprocess.run(
                    [*npm, "outdated", "--json"], cwd=grunt_dir, capture_output=True, text=True
                ).stdout
                or "{}"
            )
        except (OSError, ValueError):
            outdated = {}
        for name, info in outdated.items():
            current, wanted, latest = info.get("current"), info.get("wanted"), info.get("latest")
            if not current:
                continue
            if wanted and wanted != current:
                updates.append(f"{name} {current} → {wanted}")
            if latest and latest != (wanted or current):
                majors.append(f"{name} {wanted or current} → {latest}")
    return updates, majors


def _interactive() -> bool:
    return sys.stdin.isatty()


def _ask_upgrade_packages() -> bool:
    """Розробка: показати новіші версії пакетів і спитати, чи оновити lock-файли."""
    console.print("  [dim]Перевіряю новіші версії пакетів...[/dim]")
    outdated, majors = _outdated_packages()
    if majors:
        console.print(
            f"  [dim]Поза діапазонами package.json ({len(majors)}, міняти вручну):"
            f" {', '.join(majors)}[/dim]"
        )
    if not outdated:
        console.print("  [green]✓[/green] Пакети — найновіших версій, які дозволяють діапазони")
        return False
    console.print(f"  [yellow]![/yellow] Вийшли новіші версії {len(outdated)} пакетів:")
    for line in outdated[:15]:
        console.print(f"    [dim]{line}[/dim]")
    if len(outdated) > 15:
        console.print(f"    [dim]… і ще {len(outdated) - 15}[/dim]")
    if not _interactive():
        console.print("  [dim]Оновити lock-файли: grunt update --upgrade-packages[/dim]")
        return False
    return click.confirm("  Оновити uv.lock і package-lock.json (потім закомітити)?", default=True)


def _run_npm_install(app_dir: Path, upgrade: bool = False) -> None:
    """Встановити npm пакети; *upgrade* — ``npm update`` (найновіші в межах
    package.json, з переписаним package-lock.json)."""
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

    if upgrade:
        console.print(f"  [dim]Оновлюю npm пакети ({app_dir.name}, npm update)...[/dim]")
        if subprocess.run([*npm_run, "update"], cwd=str(app_dir), check=False).returncode == 0:
            console.print("  [green]✓[/green] npm пакети оновлені (package-lock.json змінено)")
            return
        console.print("  [yellow]⚠[/yellow]  npm update завершився з помилкою")
        return

    console.print(f"  [dim]Встановлюю npm пакети ({app_dir.name})...[/dim]")
    no_lock = [*npm_run, "install", "--no-package-lock"]

    if _package_lock_stale(app_dir):
        # Із застарілим lock звичайний install гарантовано впаде з ERESOLVE —
        # одразу розв'язуємо за package.json.
        _warn_stale_lock(app_dir.name)
    else:
        result = subprocess.run([*npm_run, "install"], cwd=str(app_dir), check=False)
        # Без `npm audit fix`: він переписує закомічений package-lock.json фреймворку,
        # і наступний git pull конфліктує. Версії пакетів приходять лише з lock-файла.
        if result.returncode == 0:
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
    # Editable-встановлення (uv tool install --editable, як робить bootstrap):
    # код, що зараз виконується, і є робочою копією репозиторію.
    import grunt_cli  # noqa: PLC0415

    source = Path(grunt_cli.__file__).resolve().parent.parent
    if (source / ".git").exists():
        return source

    default_dir = Path.home() / ".grunt-cli"
    if (default_dir / ".git").exists():
        return default_dir
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
@click.option(
    "--upgrade-packages",
    is_flag=True,
    default=False,
    help="Розробка: оновити uv.lock і package-lock.json до найновіших версій (потім закомітити)",
)
@click.option(
    "--no-upgrade-packages",
    is_flag=True,
    default=False,
    help="Розробка: не перевіряти й не пропонувати новіші версії пакетів",
)
@click.option("--skip-packages", is_flag=True, default=False, help="Не оновлювати Python пакети")
@click.option("--skip-npm", is_flag=True, default=False, help="Не встановлювати npm пакети")
@click.option("--skip-migrate", is_flag=True, default=False, help="Не запускати міграції БД")
@click.option(
    "--no-deps", is_flag=True, default=False, help="Не встановлювати залежності після оновлення"
)
@click.option(
    "--keep-old",
    is_flag=True,
    default=False,
    help="Не видаляти старі версії Python/Node.js/uv і не чистити кеші",
)
@click.option(
    "--no-restart",
    is_flag=True,
    default=False,
    help="Не збирати фронтенд і не перезапускати сервіси (прод)",
)
@click.option(
    "--tag",
    is_flag=False,
    flag_value="latest",
    default=None,
    metavar="[vX.Y.Z]",
    help="Фреймворк на реліз-тег (без значення — найновіший; з версією — закріпити/відкотити)."
    " Додатки — на свій найновіший реліз",
)
@click.option(
    "--branch",
    "follow_branch",
    is_flag=True,
    default=False,
    help="Голова гілки замість релізів (і повернення з тегу на гілку)",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Відкотити реліз, навіть якщо в базі вже є його міграції (після відновлення бекапу)",
)
@click.option("--site", default=None, help="Назва сайту (для migrate)")
def update(
    component: str | None,
    update_cli: bool,
    update_framework: bool,
    update_apps: bool,
    update_deps: bool,
    upgrade_packages: bool,
    no_upgrade_packages: bool,
    skip_packages: bool,
    skip_npm: bool,
    skip_migrate: bool,
    no_deps: bool,
    keep_old: bool,
    no_restart: bool,
    tag: str | None,
    follow_branch: bool,
    force: bool,
    site: str | None,
) -> None:
    """Оновити CLI, фреймворк, додатки, пакети та схему БД.

    \b
    Послідовність:
      1. git fetch + rebase для CLI, фреймворку та додатків
      2. mise self-update, mise install + upgrade (Node.js, uv у межах mise.toml),
         uv python upgrade (патч Python), rclone selfupdate
      3. uv sync --locked --inexact + grunt app deps (клонує відсутні додатки з
         depends_on, ставить Python пакети фреймворку й додатків)
      4. npm install
      5. grunt migrate (Alembic + DocType-таблиці + fixtures)
      6. прод (є systemd-сервіси): mise run build + перезапуск сервісів
      7. прибирання: невикористані версії Python (uv) і mise-інструментів,
         кеші uv/npm (--keep-old — не чистити)

    \b
    Версії: на проді (є systemd-сервіси) фреймворк і додатки ставляться на
    найновіший реліз-тег vX.Y.Z; репозиторій без тегів, як і в розробці,
    оновлюється до голови гілки. Репозиторій, уже поставлений на тег,
    оновлюється до новішого тегу.

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
      grunt update --tag            фреймворк і додатки — на найновіші релізи
      grunt update framework --tag v0.2.0   закріпити (або відкотити) версію
      grunt update --branch         голова гілки замість релізів
      grunt update --upgrade-packages   розробка: найновіші пакети без питання

    \b
    Пакети на проді ставляться рівно за закоміченими lock-файлами: новіші
    версії приходять релізом фреймворку (--upgrade-packages там заборонено —
    брудне дерево зупинило б наступне оновлення). У розробці grunt update
    сам показує новіші версії пакетів і питає, чи оновити lock-файли
    (без терміналу — лише показує; --no-upgrade-packages — не перевіряти).
    """
    if upgrade_packages and no_upgrade_packages:
        raise click.UsageError("--upgrade-packages і --no-upgrade-packages взаємовиключні")
    if tag is not None and follow_branch:
        raise click.UsageError("--tag і --branch взаємовиключні")
    bench = get_bench_dir()
    production = bool(bench and installed_units(bench))
    if upgrade_packages and production:
        raise click.UsageError(
            "--upgrade-packages — лише в розробці: на проді пакети ставляться за lock-файлами"
            " з релізу фреймворку"
        )
    app_tag = None if tag is None else "latest"

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
            _update_repo(
                cli_dir, "grunt-cli", tag=None, branch=follow_branch, production=production
            )
            if not no_deps:
                # editable-встановлення підхоплює код і так, а нові залежності
                # CLI ставить лише перевстановлення (mise-задача install).
                console.print("  [dim]Встановлюю grunt-cli (mise run install)...[/dim]")
                run_mise(cli_dir, "install")
                run_mise(cli_dir, "run", "install")
            updated_something = True
        console.print()

    # ── 2. Framework ────────────────────────────────────────────────
    # Задача фреймворку `deps` уже робить `npm install` — крок 6 тоді не дублює його.
    framework_deps_done = False
    if update_all or update_framework:
        console.print("[bold cyan]Фреймворк[/bold cyan]")
        apps_dir = _find_apps_dir()
        framework_dir = apps_dir / "grunt" if apps_dir else None

        if framework_dir is None or not framework_dir.exists():
            console.print("  [yellow]⚠[/yellow]  Grunt framework не знайдено")
        else:
            _update_repo(
                framework_dir,
                "grunt",
                tag=tag,
                branch=follow_branch,
                production=production,
                force=force,
            )
            if not no_deps:
                framework_deps_done = _install_deps(framework_dir, "grunt")
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
                    _update_repo(
                        app_dir,
                        app_dir.name,
                        tag=app_tag,
                        branch=follow_branch,
                        production=production,
                        force=force,
                    )
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
    # У розробці новіші версії пакетів не чекають, доки про них згадають:
    # grunt update сам показує їх і питає (на проді — лише за lock-файлами).
    if not (production or upgrade_packages or skip_packages or no_upgrade_packages):
        console.print("[bold cyan]Новіші пакети[/bold cyan]")
        upgrade_packages = _ask_upgrade_packages()
        console.print()

    if not skip_packages:
        console.print("[bold cyan]Python пакети[/bold cyan]")
        _update_python_packages(upgrade=upgrade_packages)
        updated_something = True
        console.print()
    else:
        console.print("[dim]Python пакети пропущено (--skip-packages)[/dim]")
        console.print()

    # ── 6. npm пакети ──────────────────────────────────────────────
    if not skip_npm:
        console.print("[bold cyan]npm пакети[/bold cyan]")
        apps_dir = _find_apps_dir()
        if framework_deps_done and not upgrade_packages:
            console.print("  [green]✓[/green] npm пакети вже встановлені (mise run deps)")
        elif apps_dir and (apps_dir / "grunt").exists():
            _run_npm_install(apps_dir / "grunt", upgrade=upgrade_packages)
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

    # ── 9. Прибирання ───────────────────────────────────────────────
    # Після перезапуску: старий Python може бути потрібен сервісам, доки вони
    # не стартували на новому.
    if (update_all or update_deps) and not keep_old:
        console.print("[bold cyan]Прибирання[/bold cyan]")
        _cleanup_runtimes()
        console.print()

    # ── Фінал ───────────────────────────────────────────────────────
    if not updated_something:
        console.print("[yellow]Нічого не оновлено[/yellow]")
    elif restarted:
        console.print("[bold green]✅ Оновлення завершено[/bold green]")
    else:
        console.print("[bold red]✗ Оновлення завершено з помилками[/bold red]")
        raise SystemExit(1)
