"""grunt update — оновлення CLI, фреймворку та додатків через git."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import click

from grunt_cli import helpers
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
    run_captured,
    run_mise,
    venv_delegate,
)

# Реліз = анотований тег vX.Y.Z (`grunt release` у фреймворку). Пре-релізи
# (v1.2.0-rc1) на прод не ставимо.
_RELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

_TAG_FETCH = ("--tags", "--force")
# (репозиторій, аргументи fetch), уже стягнуті наперед у цьому запуску (_prefetch).
_prefetched: set[tuple[Path, tuple[str, ...]]] = set()


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
    if (path, ()) not in _prefetched and not _git_fetch(path, label):
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
    if (path, _TAG_FETCH) not in _prefetched and not _git_fetch(path, label, *_TAG_FETCH):
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
    if _wants_release(path, tag=tag, branch=branch, production=production):
        return _git_checkout_tag(path, label, None if tag in (None, "latest") else tag, force)
    return _git_pull(path, label)


def _wants_release(path: Path, *, tag: str | None, branch: bool, production: bool) -> bool:
    """Чи _update_repo поставить репозиторій на реліз-тег (а не на гілку)."""
    if branch:
        return False
    has_git = (path / ".git").exists()
    return tag is not None or (
        has_git and bool(_current_tag(path) or (production and release_tags(path)))
    )


def _prefetch(repos: list[tuple[Path, tuple[str, ...]]]) -> None:
    """``git fetch`` усіх репозиторіїв разом — час іде на мережу, а не на git.

    Без запиту токена: що не вдалося стягнути тут, ще раз стягне _git_fetch
    у _update_repo — уже з повтором після токена і зрозумілим повідомленням.
    """
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    def fetch(item: tuple[Path, tuple[str, ...]]) -> bool:
        path, args = item
        return _git(path, "fetch", *args, env=env).returncode == 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        for item, ok in zip(repos, pool.map(fetch, repos), strict=True):
            if ok:
                _prefetched.add(item)


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


def _install_deps(path: Path, label: str) -> bool | None:
    """Встановлює залежності через mise.

    True — відпрацювала задача ``deps``, False — вона впала, None — її немає.
    """
    run_mise(path, "install", quiet=True, status=f"Оновлюю рантайми для {label}...")

    mise_toml = path / "mise.toml"
    if mise_toml.exists():
        import tomllib  # noqa: PLC0415

        with mise_toml.open("rb") as f:
            tasks = tomllib.load(f).get("tasks", {})
        if "deps" in tasks:
            # deps-задача сама викликає npm install — із застарілим lock вона б упала.
            env = None
            if _package_lock_stale(path):
                _warn_stale_lock(label)
                env = _NPM_NO_LOCK_ENV
            status = f"Встановлюю пакети для {label} (mise run deps)..."
            if run_mise(path, "run", "deps", env=env, quiet=True, status=status):
                console.print(f"  [green]✓[/green] Пакети {label} встановлені")
                return True
            console.print(
                f"  [yellow]⚠[/yellow]  Пакети {label}: mise run deps завершився з помилкою"
            )
            return False
    return None


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


def _project_uv() -> str | None:
    """uv, якого вимагає mise.toml фреймворку, — звідки б не запустили grunt update.

    find_uv() дає mise-шим, а шим обирає версію за поточною текою: з кореня
    бенча він падає «No version is set for shim: uv». ``mise which``
    у теці mise.toml повертає сам бінарник потрібної версії."""
    mise_bin = get_mise_bin()
    runtime_dir = _runtime_dir()
    if mise_bin and runtime_dir:
        result = subprocess.run(
            [mise_bin, "which", "uv"],
            cwd=str(runtime_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and (path := result.stdout.strip()):
            return path
    return find_uv()


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
            status = "Оновлюю рантайми з mise.toml (Node.js, uv тощо)..."
            if run_mise(runtime_dir, "install", quiet=True, status=status) and run_mise(
                runtime_dir, "upgrade", quiet=True, status=status
            ):
                console.print("  [green]✓[/green] Рантайми з mise.toml оновлені")
            else:
                console.print("  [yellow]⚠[/yellow]  Оновлення рантаймів завершилось з помилкою")

    # uv міг щойно оновитися через mise — шукаємо його після.
    uv_bin = _project_uv()
    if uv_bin:
        _step([uv_bin, "python", "upgrade"], "Python оновлено", quiet=True)

    if os.access(_MANAGED_RCLONE, os.X_OK):
        _step([str(_MANAGED_RCLONE), "selfupdate"], "rclone оновлено", quiet=True)


def _in_use() -> dict[str, list[str]]:
    """``{реальний шлях: [хто ним користується]}`` для інтерпретаторів, на які
    щось спирається: ``home`` кожного venv у домашній теці (фреймворк, додатки,
    uv tool, свої) і виконувані файли запущених процесів (сервер на старому
    Python ще працює, доки його не перезапустили)."""
    used: dict[str, list[str]] = {}
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
                    used.setdefault(os.path.realpath(value.strip()), []).append(
                        _venv_user(Path(root))
                    )
        except OSError:
            continue
    for exe in Path("/proc").glob("[0-9]*/exe"):
        try:
            path = os.path.realpath(exe)
        except OSError:
            continue
        used.setdefault(path, []).append(_process_user(exe.parent))
    return used


def _venv_user(venv: Path) -> str:
    """«venv ~/x → як перевести його на поточний Python»."""
    home = Path.home()
    shown = "~/" + str(venv.relative_to(home)) if venv.is_relative_to(home) else str(venv)
    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    tools = Path(os.environ.get("UV_TOOL_DIR") or home / ".local/share/uv/tools")
    if venv.parent == tools:
        return f"uv tool {venv.name} → uv tool install --reinstall --python {py} {venv.name}"
    if (venv.parent / "pyproject.toml").is_file():
        project = (
            "~/" + str(venv.parent.relative_to(home)) if venv.is_relative_to(home) else venv.parent
        )
        return f"venv {shown} → cd {project} && uv sync --python {py}"
    # Окремий venv без проєкту: пакети не описані ніде, крім нього самого —
    # зберегти їх список, перестворити, поставити назад.
    reqs = f"/tmp/{venv.name.lstrip('.') or 'venv'}-requirements.txt"
    fix = (
        f"uv pip freeze --python {shown} > {reqs}"
        f" && uv venv --clear --python {py} {shown}"
        f" && uv pip install --python {shown} -r {reqs}"
    )
    return f"venv {shown} → {fix}"


def _process_user(proc: Path) -> str:
    """«процес 123 (grunt serve, 6 дн) → kill 123»."""
    try:
        argv = [
            a.decode(errors="replace") for a in (proc / "cmdline").read_bytes().split(b"\0") if a
        ]
    except OSError:
        argv = []
    # python /path/bin/grunt serve → grunt serve
    args = argv[1:] if argv and Path(argv[0]).name.startswith("python") and len(argv) > 1 else argv
    command = " ".join([Path(args[0]).name, *args[1:3]]) if args else "?"
    pid = proc.name
    try:
        state = (proc / "stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        state = ""
    if state == "T":
        # Зупинений (Ctrl+Z) не обробить SIGTERM, доки його не розбудити.
        fix = f"kill {pid} && kill -CONT {pid}"
        return f"процес {pid} ({command}, {_age(proc)}, зупинений Ctrl+Z) → {fix}"
    return f"процес {pid} ({command}, {_age(proc)}) → kill {pid}"


def _age(proc: Path) -> str:
    try:
        start = int((proc / "stat").read_text().rsplit(")", 1)[1].split()[19])
        # btime, не /proc/uptime: у контейнері (LXC) uptime — від старту
        # контейнера, а час старту процесу — від завантаження хоста.
        btime = next(
            int(line.split()[1])
            for line in Path("/proc/stat").read_text().splitlines()
            if line.startswith("btime ")
        )
        seconds = time.time() - (btime + start / os.sysconf("SC_CLK_TCK"))
    except (OSError, ValueError, IndexError, StopIteration):
        return "?"
    if seconds >= 86400:
        return f"{int(seconds // 86400)} дн"
    if seconds >= 3600:
        return f"{int(seconds // 3600)} год"
    return f"{max(int(seconds // 60), 1)} хв"


_CACHE_TIMEOUT = 120


def _quick(cmd: list[str], env: dict[str, str] | None = None) -> None:
    """Чистка кешу — не варта того, щоб чекати на неї довше за пару хвилин."""
    try:
        subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            timeout=_CACHE_TIMEOUT,
            env={**os.environ, **(env or {})},
        )
    except subprocess.TimeoutExpired:
        console.print(
            f"  [yellow]⚠[/yellow]  {' '.join(cmd[-2:])}: довше {_CACHE_TIMEOUT} с, пропущено"
        )


def _uv_cache_holders() -> str:
    """Запущені ``uv run`` (тримають блокування кешу uv), напр. «процес 123 (uv run uvicorn)»."""
    found = []
    for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            argv = cmdline.read_bytes().split(b"\0")
        except OSError:
            continue
        if len(argv) > 2 and argv[0].endswith(b"uv") and argv[1] == b"run":
            name = argv[2].decode(errors="replace")
            found.append(f"процес {cmdline.parent.name} (uv run {name})")
    return ", ".join(sorted(found))


def _print_cleanup_summary(removed: list[str], kept: list[str], notes: list[str]) -> None:
    """Зведення прибирання під підсумком оновлення: що звільнено, що ще
    тримають (хто і як його звільнити) — його прибере наступний `grunt update`."""
    if removed:
        console.print(f"  [dim]Видалено старі рантайми: {', '.join(removed)}[/dim]")
    if kept:
        console.print("  [yellow]Залишено старі рантайми (ще використовуються):[/yellow]")
        # Рядок на кожного користувача; спільну назву рантайму — один раз.
        shown = None
        for line in kept:
            label, _, user = line.partition(" — ")
            who, _, fix = user.partition(" → ")
            if label != shown:
                console.print(f"    {label}")
                shown = label
            console.print(f"      [dim]— {who}[/dim]")
            if fix:
                console.print(f"        [dim]звільнити:[/dim] [cyan]{fix}[/cyan]")
        console.print("  [dim]Наступний grunt update прибере їх, щойно вони звільняться.[/dim]")
    for note in notes:
        console.print(f"  [dim]{note}[/dim]")


def _current_pythons() -> set[Path]:
    """Теки Python, на яких працюють фреймворк (його .venv) і сам grunt-cli —
    вони поточні, а не «старі», навіть коли вільні."""
    found = {Path(os.path.realpath(sys.executable)).parent.parent}
    apps_dir = _find_apps_dir()
    cfg = apps_dir / "grunt" / ".venv" / "pyvenv.cfg" if apps_dir else None
    if cfg and cfg.is_file():
        for line in cfg.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "home" and value.strip():
                found.add(Path(os.path.realpath(value.strip())).parent)
    return found


def _users_of(used: dict[str, list[str]], directory: Path) -> list[str]:
    """Усі, хто користується чимось у *directory* — один Python можуть
    тримати кілька venv і процесів одночасно."""
    prefix = f"{directory}/"
    return [w for path, who in used.items() if path.startswith(prefix) for w in who]


_MISE_PRUNABLE = re.compile(r"^mise (\S+?)@(\S+) is prunable", re.M)


def _cleanup_runtimes(prune_caches: bool = True) -> tuple[list[str], list[str], list[str]]:
    """Прибрати рантайми, які оновлення залишило без діла.

    Повертає ``(видалено, залишено, примітки)`` — рядки для зведення
    наприкінці; примітки — те, що пропущено, але це нормально (кеш uv, поки
    працює grunt serve).

    \b
    uv python   версії, на які не вказує жоден venv і не працює жоден процес
    mise        старі версії інструментів mise.toml (node, uv, python), так само
                лише вільні; rclone та інше, поставлене mise вручну, не чіпаємо
    uv cache prune, npm cache verify — невикористане з кешів (лише з *prune_caches*)
    """
    import json  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    import tomllib  # noqa: PLC0415

    used = _in_use()
    removed: list[str] = []
    kept: list[str] = []
    notes: list[str] = []

    def remove(cmd: list[str], label: str) -> None:
        if _step(cmd, f"Видалено {label}", quiet=True):
            removed.append(label)
        else:
            kept.append(f"{label} — не вдалося видалити")

    uv_bin = _project_uv()
    if uv_bin:
        listed = subprocess.run(
            [uv_bin, "python", "list", "--only-installed", "--output-format", "json"],
            capture_output=True,
            text=True,
        )
        if listed.returncode:
            error = (listed.stderr or "").strip().splitlines() or [f"код {listed.returncode}"]
            notes.append(f"Python (uv) не чищено — uv python list: {error[-1]}")
        try:
            installs = json.loads(listed.stdout or "[]") if not listed.returncode else []
        except ValueError:
            installs = []
        managed = Path.home() / ".local" / "share" / "uv" / "python"
        current = _current_pythons()
        seen: set[str] = set()
        for py in installs:
            path = os.path.realpath(py.get("path") or "")
            if not path.startswith(f"{managed}/") or py["key"] in seen:
                continue  # системний Python; minor-посилання дублює версію
            seen.add(py["key"])
            install_dir = managed / path.removeprefix(f"{managed}/").split("/", 1)[0]
            label = f"Python {py.get('version') or py['key']} (uv)"
            if install_dir in current:
                continue
            if users := _users_of(used, install_dir):
                kept.extend(f"{label} — {who}" for who in users)
            else:
                remove([uv_bin, "python", "uninstall", py["key"]], label)
        if not prune_caches:
            pass  # кеші чистимо раз на _CACHE_PRUNE_EVERY
        elif holders := _uv_cache_holders():
            # prune бере ексклюзивне блокування кешу, а `uv run` (grunt serve)
            # тримає спільне весь час, поки працює — prune чекав би вічно.
            notes.append(f"Кеш uv не чищено — його тримає {holders}")
        else:
            _quick([uv_bin, "cache", "prune"], {"UV_LOCK_TIMEOUT": "30"})

    mise_bin = get_mise_bin()
    if mise_bin:
        tools: set[str] = set()
        runtime_dir = _runtime_dir()
        cli_dir = _get_cli_dir()
        for cfg in (runtime_dir and runtime_dir / "mise.toml", cli_dir and cli_dir / "mise.toml"):
            if cfg and cfg.is_file():
                with cfg.open("rb") as f:
                    tools.update(tomllib.load(f).get("tools", {}))
        if tools:
            plan = subprocess.run(
                [mise_bin, "prune", "--dry-run", *sorted(tools)],
                capture_output=True,
                text=True,
            )
            installs = Path.home() / ".local" / "share" / "mise" / "installs"
            for tool, version in _MISE_PRUNABLE.findall(plan.stdout + plan.stderr):
                label = f"{tool} {version} (mise)"
                if users := _users_of(used, installs / tool / version):
                    kept.extend(f"{label} — {who}" for who in users)
                else:
                    remove([mise_bin, "uninstall", f"{tool}@{version}"], label)

    npm = shutil.which("npm")
    if npm and prune_caches:
        _quick([npm, "cache", "verify"])
    return removed, kept, notes


def _update_python_packages(upgrade: bool = False) -> bool:
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
        if (
            locked
            and upgrade
            and run_captured(
                [uv_bin, "lock", "--upgrade"],
                cwd=cwd_dir,
                env=env,
                status="Оновлюю uv.lock (uv lock --upgrade)...",
            )
        ):
            console.print("  [yellow]⚠[/yellow]  uv lock --upgrade завершився з помилкою")
            return False
        # --inexact: keep packages outside the framework's lock — the apps
        # (editable) and their dependencies, installed by `grunt app deps`.
        if run_captured(
            [uv_bin, "sync", mode, "--all-extras", "--inexact"],
            cwd=cwd_dir,
            env=env,
            status=f"Оновлюю Python пакети (uv sync {mode})...",
        ):
            console.print(f"  [yellow]⚠[/yellow]  uv sync {mode} завершився з помилкою")
            return False
        apps = run_captured(
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
            env=env,
            status="Встановлюю залежності додатків (grunt app deps)...",
        )
        if apps != 0:
            console.print(
                "  [yellow]⚠[/yellow]  Залежності додатків не встановились (grunt app deps)"
            )
            return False
        console.print("  [green]✓[/green] Python пакети оновлені (фреймворк + додатки)")
        return True

    # Fallback на pip
    pip_bin = shutil.which("pip") or shutil.which("pip3")
    if pip_bin:
        console.print("  [dim]uv не знайдено, оновлюю через pip...[/dim]")
        result = subprocess.run([pip_bin, "install", "--upgrade", "pip"], check=False)
        if result.returncode != 0:
            console.print("  [yellow]⚠[/yellow]  pip update завершився з помилкою")
            return False
        console.print("  [green]✓[/green] Python пакети оновлені")
        return True
    console.print("  [yellow]⚠[/yellow]  Ні uv, ні pip не знайдено")
    return False


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

    def npm_outdated() -> dict:
        npm = [*via_mise, "npm"] if mise else [shutil.which("npm") or "npm"]
        # npm outdated виходить з кодом 1, коли щось застаріло — дивимось лише на JSON
        try:
            return json.loads(
                subprocess.run(
                    [*npm, "outdated", "--json"], cwd=grunt_dir, capture_output=True, text=True
                ).stdout
                or "{}"
            )
        except (OSError, ValueError):
            return {}

    uv = [*via_mise, "uv"] if mise else [find_uv() or "uv"]
    python = grunt_dir / ".venv" / "bin" / "python"
    # Три незалежні запити до реєстрів пакетів — разом, а не по черзі.
    with ThreadPoolExecutor(max_workers=3) as pool:
        plan = (
            pool.submit(output, [*uv, "lock", "--upgrade", "--dry-run"])
            if (grunt_dir / "uv.lock").exists()
            else None
        )
        apps = (
            pool.submit(
                output, [str(python), "-m", FRAMEWORK_CLI_MODULE, "app", "deps", "--outdated"]
            )
            if python.exists()
            else None
        )
        npm = pool.submit(npm_outdated) if (grunt_dir / "node_modules").is_dir() else None

    updates: list[str] = []
    majors: list[str] = []
    if plan:
        updates += [f"{n} {a} → {b}" for n, a, b in _UV_UPDATE.findall(plan.result())]
    if apps:
        updates += [line.strip() for line in apps.result().splitlines() if " → " in line]
    if npm:
        for name, info in npm.result().items():
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


def _run_npm_install(app_dir: Path, upgrade: bool = False) -> bool:
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
            return False
        npm_run = [npm]

    if upgrade:
        status = f"Оновлюю npm пакети ({app_dir.name}, npm update)..."
        if run_captured([*npm_run, "update"], cwd=app_dir, status=status) == 0:
            console.print("  [green]✓[/green] npm пакети оновлені (package-lock.json змінено)")
            return True
        console.print("  [yellow]⚠[/yellow]  npm update завершився з помилкою")
        return False

    status = f"Встановлюю npm пакети ({app_dir.name})..."
    no_lock = [*npm_run, "install", "--no-package-lock"]

    if _package_lock_stale(app_dir):
        # Із застарілим lock звичайний install гарантовано впаде з ERESOLVE —
        # одразу розв'язуємо за package.json.
        _warn_stale_lock(app_dir.name)
    else:
        result = run_captured([*npm_run, "install"], cwd=app_dir, status=status)
        # Без `npm audit fix`: він переписує закомічений package-lock.json фреймворку,
        # і наступний git pull конфліктує. Версії пакетів приходять лише з lock-файла.
        if result == 0:
            console.print("  [green]✓[/green] npm пакети встановлені")
            return True
        console.print("  [dim]Повторна спроба без package-lock.json...[/dim]")

    if run_captured(no_lock, cwd=app_dir, status=status) == 0:
        console.print("  [green]✓[/green] npm пакети встановлені (без package-lock.json)")
        return True

    # Чиста установка, але старий node_modules відкладаємо, а не видаляємо:
    # якщо й вона впаде, повертаємо його, щоб було з чим зібрати фронтенд.
    nm = app_dir / "node_modules"
    backup = app_dir / "node_modules.bak"
    if nm.exists():
        console.print("  [dim]Чиста установка node_modules, повторна спроба...[/dim]")
        shutil.rmtree(backup, ignore_errors=True)
        nm.rename(backup)
        if run_captured(no_lock, cwd=app_dir, status=status) == 0:
            shutil.rmtree(backup, ignore_errors=True)
            console.print("  [green]✓[/green] npm пакети встановлені (чиста установка)")
            return True
        shutil.rmtree(nm, ignore_errors=True)
        backup.rename(nm)
        console.print("  [dim]Повернуто попередній node_modules[/dim]")

    console.print("  [yellow]⚠[/yellow]  npm install завершився з помилкою")
    return False


def _run_migrations(site: str | None) -> bool:
    """Повна ``grunt migrate`` фреймворку: Alembic + DocType-таблиці + fixtures.

    Окремим процесом із venv проєкту — там уже новий код після git pull.
    """
    if get_current_site() is None:
        console.print("  [yellow]⚠[/yellow]  grunt.site не знайдено")
        return False
    code = venv_delegate("migrate", site=site, quiet=True, status="Застосовую міграції...")
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

    if not run_mise(
        bench / "apps" / "grunt", "build", quiet=True, status="Збираю фронтенд (mise run build)..."
    ):
        console.print("  [yellow]⚠[/yellow]  Збірка фронтенду не вдалася — сервіси НЕ перезапущено")
        return False
    console.print("  [green]✓[/green] Фронтенд зібрано")
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


# ── Пропуск кроків, де нічого не змінилось ──────────────────────────
# Після успішного кроку запамʼятовуємо відбиток того, від чого він залежить;
# наступний запуск із тим самим відбитком крок пропускає. Невдалий крок
# відбиток не оновлює — його повторить наступний grunt update. Видалити
# файл (або --full) — пройти всі кроки.
_STATE_FILE = (
    Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "grunt/update-state.json"
)
_CACHE_PRUNE_EVERY = 7 * 86400

# Від цих файлів залежить, що встановлено: пакети, рантайми, depends_on.
_DEP_FILES = (
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "package-lock.json",
    "mise.toml",
    "app.json",
)


class _State:
    """Відбитки, на яких кроки grunt update востаннє пройшли успішно."""

    def __init__(self, full: bool):
        self.full = full
        self.skipped = False
        try:
            self.data = json.loads(_STATE_FILE.read_text())
        except (OSError, ValueError):
            self.data = {}

    def fresh(self, key: str, fingerprint: str | None) -> bool:
        """Крок *key* уже пройдено на цьому відбитку — його можна пропустити."""
        if self.full or fingerprint is None or self.data.get(key) != fingerprint:
            return False
        self.skipped = True
        return True

    def due(self, key: str, every: float) -> bool:
        """Періодичний крок: востаннє був довше ніж *every* секунд тому."""
        return self.full or time.time() - float(self.data.get(key) or 0) >= every

    def mark(self, key: str, value: str | float | None) -> None:
        if value is None:
            return
        self.data[key] = value
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = _STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1))
            tmp.replace(_STATE_FILE)
        except OSError:
            pass  # без стану наступний запуск просто пройде всі кроки


def _deps_fingerprint(*dirs: Path) -> str:
    """Відбиток залежностей: вміст _DEP_FILES і наявність .venv/node_modules
    (видалили node_modules — встановити заново)."""
    h = hashlib.sha256()
    for d in dirs:
        h.update(f"{d}\0{(d / '.venv').is_dir()}{(d / 'node_modules').is_dir()}\0".encode())
        for name in _DEP_FILES:
            try:
                h.update(name.encode() + b"\0" + (d / name).read_bytes() + b"\0")
            except OSError:
                h.update(name.encode() + b"\0-\0")
    return h.hexdigest()


def _project_dirs() -> list[Path]:
    """Фреймворк і всі додатки з apps/."""
    apps_dir = _find_apps_dir()
    if apps_dir is None or not apps_dir.is_dir():
        return []
    return sorted(p for p in apps_dir.iterdir() if p.is_dir() and not p.name.startswith("."))


def _code_fingerprint(dirs: list[Path]) -> str | None:
    """Відбиток коду: HEAD, незакомічені правки й нові файли кожного репозиторію.

    None — якщо є тека не під git: її зміни не відстежити, крок не пропускаємо.
    """
    if not dirs:
        return None
    h = hashlib.sha256()
    for d in dirs:
        if not (d / ".git").exists():
            return None
        head = _git(d, "rev-parse", "HEAD").stdout
        diff = _git(d, "diff", "HEAD").stdout
        h.update(f"{d}\0{head}\0{diff}\0".encode())
        # Нові файли (свіжий DocType у розробці) — за назвою, розміром і часом зміни.
        untracked = _git(d, "ls-files", "--others", "--exclude-standard", "-z").stdout
        for name in untracked.split("\0"):
            try:
                st = (d / name).stat() if name else None
            except OSError:
                st = None
            if st:
                h.update(f"{name}\0{st.st_size}\0{st.st_mtime_ns}\0".encode())
    return h.hexdigest()


def _runtime_fingerprint() -> str:
    """Python фреймворку й Node.js — після їх оновлення сервіси треба перезапустити."""
    h = hashlib.sha256()
    apps_dir = _find_apps_dir()
    exes = [apps_dir / "grunt" / ".venv" / "bin" / "python"] if apps_dir else []
    mise_bin = get_mise_bin()
    runtime_dir = _runtime_dir()
    if mise_bin and runtime_dir:
        node = subprocess.run(
            [mise_bin, "which", "node"], cwd=str(runtime_dir), capture_output=True, text=True
        )
        if node.returncode == 0 and node.stdout.strip():
            exes.append(Path(node.stdout.strip()))
    for exe in exes:
        try:
            real = Path(os.path.realpath(exe))
            h.update(f"{real}\0{real.stat().st_mtime_ns}\0".encode())
        except OSError:
            h.update(f"{exe}\0-\0".encode())
    return h.hexdigest()


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
    "--upgrade",
    "do_upgrade",
    is_flag=True,
    default=False,
    help="Оновити всі залежності та файли версій до останьої версії (еквівалент grunt upgrade)",
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
@click.option(
    "--full",
    is_flag=True,
    default=False,
    help="Пройти всі кроки, навіть ті, де з минулого запуску нічого не змінилось",
)
@click.option("--site", default=None, help="Назва сайту (для migrate)")
@click.option(
    "-v", "--verbose", is_flag=True, help="Повний вивід uv/mise/npm/міграцій замість стислого"
)
def update(
    component: str | None,
    update_cli: bool,
    update_framework: bool,
    update_apps: bool,
    update_deps: bool,
    do_upgrade: bool,
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
    full: bool,
    site: str | None,
    verbose: bool,
) -> None:
    """Оновити CLI, фреймворк, додатки, пакети та схему БД.

    \b
    Послідовність:
      1. git fetch + rebase для CLI
      2. mise self-update, mise install + upgrade (Node.js, uv у межах mise.toml),
         uv python upgrade (патч Python), rclone selfupdate — до залежностей
         фреймворку, щоб venv створював уже новий uv
      3. git fetch + rebase для фреймворку та додатків (+ mise run deps)
      4. uv sync --locked --inexact + grunt app deps (клонує відсутні додатки з
         depends_on, ставить Python пакети фреймворку й додатків)
      5. npm install
      6. grunt migrate (Alembic + DocType-таблиці + fixtures)
      7. прод (є systemd-сервіси): mise run build + перезапуск сервісів
      8. прибирання: невикористані версії Python (uv) і mise-інструментів,
         кеші uv/npm раз на тиждень (--keep-old — не чистити)

    \b
    Кроки, де з минулого успішного запуску нічого не змінилось, пропускаються:
    встановлення пакетів (ті самі lock-файли, pyproject.toml, mise.toml,
    app.json), міграції (той самий код фреймворку й додатків), збірка й
    перезапуск на проді (той самий код і рантайми). git fetch усіх
    репозиторіїв іде паралельно. --full — пройти всі кроки (напр. після
    grunt db restore, якщо базу треба домігрувати).

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
      grunt update --upgrade        найновіші версії залежностей (grunt upgrade)
      grunt update --upgrade-packages   розробка: найновіші пакети без питання
      grunt update -v               повний вивід підпроцесів (для діагностики)
      grunt update --full           не пропускати кроки без змін

    \b
    Пакети на проді ставляться рівно за закоміченими lock-файлами: новіші
    версії приходять релізом фреймворку (--upgrade-packages там заборонено —
    брудне дерево зупинило б наступне оновлення). У розробці grunt update
    сам показує новіші версії пакетів і питає, чи оновити lock-файли
    (без терміналу — лише показує; --no-upgrade-packages — не перевіряти).
    """
    if do_upgrade:
        from grunt_cli.commands.upgrade import upgrade as upgrade_cmd

        ctx = click.get_current_context()
        ctx.invoke(
            upgrade_cmd,
            component="all",
            dry_run=False,
            skip_runtimes=False,
            skip_packages=skip_packages,
            skip_python=skip_packages,
            skip_node=skip_npm,
            skip_cli=False,
            skip_migrate=skip_migrate,
            keep_old=keep_old,
            verbose=verbose,
        )
        return

    helpers.VERBOSE = verbose
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
    # Відкат із --force іде після відновлення бекапу — базу треба мігрувати.
    state = _State(full=full or force)

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

    # ── 0. git fetch усіх репозиторіїв разом ────────────────────────
    _prefetched.clear()
    to_fetch: list[tuple[Path, str | None]] = []
    if (update_all or update_cli) and (cli_dir := _get_cli_dir()):
        to_fetch.append((cli_dir, None))
    for d in _project_dirs():
        if d.name == "grunt" and (update_all or update_framework):
            to_fetch.append((d, tag))
        elif d.name != "grunt" and (update_all or update_apps):
            to_fetch.append((d, app_tag))
    fetch_plan = []
    for d, t in to_fetch:
        if (d / ".git").exists():
            release = _wants_release(d, tag=t, branch=follow_branch, production=production)
            fetch_plan.append((d, _TAG_FETCH if release else ()))
    _prefetch(fetch_plan)

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
                key, fp = f"cli:{cli_dir}", _deps_fingerprint(cli_dir)
                status = "Встановлюю grunt-cli (mise run install)..."
                if state.fresh(key, fp):
                    console.print("  [green]✓[/green] grunt-cli: залежності без змін")
                elif run_mise(cli_dir, "install", quiet=True, status=status) and run_mise(
                    cli_dir, "run", "install", quiet=True, status=status
                ):
                    console.print("  [green]✓[/green] grunt-cli встановлено")
                    state.mark(key, fp)
                else:
                    console.print("  [yellow]⚠[/yellow]  Встановлення grunt-cli не вдалося")
            updated_something = True
        console.print()

    # ── 2. Системні залежності (рантайми) ────────────────────────
    # До `mise run deps` фреймворку й додатків: інакше venv перестворить ще
    # старий uv, який не знає новішого Python (поставив би 3.15.0rc2 замість
    # 3.15.0), а `uv python upgrade` після нього вже нічого не змінить.
    if update_all or update_deps:
        console.print("[bold cyan]Системні залежності[/bold cyan]")
        _update_runtimes()
        updated_something = True
        console.print()

    # ── 3. Framework ────────────────────────────────────────────────
    # Задача фреймворку `deps` уже робить `uv sync`, `grunt app deps` і
    # `npm install` — кроки 5 і 6 тоді не дублюють їх.
    framework_deps_done = False
    # Відбиток додатків, з яким щойно відпрацювала `deps` фреймворку (None — не працювала).
    apps_fp_at_deps: str | None = None
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
                key, fp = f"deps:{framework_dir}", _deps_fingerprint(framework_dir)
                if state.fresh(key, fp):
                    console.print("  [green]✓[/green] Пакети grunt: без змін")
                    framework_deps_done = True
                else:
                    result = _install_deps(framework_dir, "grunt")
                    framework_deps_done = result is True
                    if framework_deps_done:
                        apps_fp_at_deps = _deps_fingerprint(
                            *(d for d in _project_dirs() if d.name != "grunt")
                        )
                    if result is not False:
                        state.mark(key, _deps_fingerprint(framework_dir))
            updated_something = True
        console.print()

    # ── 4. Apps ─────────────────────────────────────────────────────
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
                        # Без змін — мовчки: рядок «вже актуальний» уже виведено вище.
                        key, fp = f"deps:{app_dir}", _deps_fingerprint(app_dir)
                        if (
                            not state.fresh(key, fp)
                            and _install_deps(app_dir, app_dir.name) is not False
                        ):
                            state.mark(key, _deps_fingerprint(app_dir))
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
        project = _project_dirs()
        key = f"packages:{_find_apps_dir()}"
        fp = _deps_fingerprint(*project) if project else None
        apps_fp = _deps_fingerprint(*(d for d in project if d.name != "grunt"))
        if upgrade_packages:
            if _update_python_packages(upgrade=True):
                state.mark(key, _deps_fingerprint(*_project_dirs()))
        elif state.fresh(key, fp):
            console.print("  [green]✓[/green] Python пакети: без змін")
        elif apps_fp_at_deps == apps_fp:
            # Додатки після `mise run deps` фреймворку не змінились — вона все й поставила.
            console.print("  [green]✓[/green] Python пакети вже встановлені (mise run deps)")
            state.mark(key, fp)
        elif _update_python_packages(upgrade=False):
            state.mark(key, _deps_fingerprint(*_project_dirs()))
        updated_something = True
        console.print()
    else:
        console.print("[dim]Python пакети пропущено (--skip-packages)[/dim]")
        console.print()

    # ── 6. npm пакети ──────────────────────────────────────────────
    if not skip_npm:
        console.print("[bold cyan]npm пакети[/bold cyan]")
        apps_dir = _find_apps_dir()
        grunt_dir = apps_dir / "grunt" if apps_dir else None
        key = f"npm:{grunt_dir}"
        if framework_deps_done and not upgrade_packages:
            console.print("  [green]✓[/green] npm пакети вже встановлені (mise run deps)")
        elif grunt_dir and grunt_dir.exists():
            if not upgrade_packages and state.fresh(key, _deps_fingerprint(grunt_dir)):
                console.print("  [green]✓[/green] npm пакети: без змін")
            elif _run_npm_install(grunt_dir, upgrade=upgrade_packages):
                state.mark(key, _deps_fingerprint(grunt_dir))
            updated_something = True
        else:
            console.print("  [dim]Grunt app директорія не знайдена[/dim]")
        console.print()
    else:
        console.print("[dim]npm пакети пропущено (--skip-npm)[/dim]")
        console.print()

    # ── 7. Міграція БД ──────────────────────────────────────────────
    migrated = True
    # Відбиток коду рахуємо після пакетів: npm/uv могли переписати lock-файли.
    code_fp = _code_fingerprint(_project_dirs())
    if not skip_migrate:
        console.print("[bold cyan]Міграція БД[/bold cyan]")
        site_dir = get_current_site()
        key = f"migrate:{site_dir}:{site or ''}"
        site_conf = site_dir / "grunt.site" if site_dir else None
        # Конфіг сайту — у ньому список встановлених додатків.
        fp = (
            code_fp
            and hashlib.sha256(
                code_fp.encode()
                + (site_conf.read_bytes() if site_conf and site_conf.is_file() else b"")
            ).hexdigest()
        )
        if state.fresh(key, fp):
            console.print("  [green]✓[/green] Код не змінився з останньої міграції — пропущено")
        else:
            migrated = _run_migrations(site)
            if migrated:
                state.mark(key, fp)
        updated_something = True
        console.print()
    else:
        console.print("[dim]Міграція БД пропущена (--skip-migrate)[/dim]")
        console.print()

    # ── 8. Перезапуск ───────────────────────────────────────────────
    restarted = True
    if updated_something and not no_restart:
        console.print("[bold cyan]Перезапуск[/bold cyan]")
        key = f"restart:{bench}"
        fp = None
        if production and code_fp:
            fp = hashlib.sha256(f"{code_fp}\0{_runtime_fingerprint()}".encode()).hexdigest()
        if migrated and state.fresh(key, fp):
            console.print(
                "  [green]✓[/green] Код і рантайми не змінились — збірка й перезапуск не потрібні"
            )
        else:
            restarted = _restart_production(migrated)
            if restarted:
                state.mark(key, fp)
        console.print()

    # ── 9. Прибирання ───────────────────────────────────────────────
    # Після перезапуску: старий Python може бути потрібен сервісам, доки вони
    # не стартували на новому.
    removed: list[str] = []
    kept: list[str] = []
    notes: list[str] = []
    if (update_all or update_deps) and not keep_old:
        console.print("[bold cyan]Прибирання[/bold cyan]")
        prune_caches = state.due("caches", _CACHE_PRUNE_EVERY)
        removed, kept, notes = _cleanup_runtimes(prune_caches)
        if prune_caches:
            state.mark("caches", time.time())
        if not removed and not kept:
            console.print("  [green]✓[/green] Старих версій рантаймів немає")
        console.print()

    # ── Фінал ───────────────────────────────────────────────────────
    if not updated_something:
        console.print("[yellow]Нічого не оновлено[/yellow]")
    elif restarted:
        console.print("[bold green]✅ Оновлення завершено[/bold green]")
        _print_cleanup_summary(removed, kept, notes)
        if state.skipped:
            console.print(
                "  [dim]Кроки без змін пропущено; виконати все: grunt update --full[/dim]"
            )
    else:
        console.print("[bold red]✗ Оновлення завершено з помилками[/bold red]")
        raise SystemExit(1)
