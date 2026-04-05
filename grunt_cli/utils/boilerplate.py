"""
Grunt App Boilerplate Generator.

Provides interactive scaffolding for new Grunt applications.
Called by: grunt app create <name>
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.tree import Tree

console = Console()


# ── Validation ───────────────────────────────────────────────────────────────


def is_valid_app_name(name: str) -> bool:
    """App name must be snake_case and start with a letter."""
    return bool(re.match(r"^[a-z][a-z0-9_]*$", name))


def is_valid_module_name(name: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9_]*$", name))


def is_valid_email(addr: str) -> bool:
    import email.headerregistry  # noqa: PLC0415

    try:
        email.headerregistry.Address(addr_spec=addr)
        return "@" in addr
    except Exception:
        return False


# ── Public entry point ────────────────────────────────────────────────────────


def make_boilerplate(dest: Path, app_name: str, no_git: bool = False) -> None:
    """Interactively create a new Grunt app at dest/app_name."""
    if not is_valid_app_name(app_name):
        console.print(
            "[red]✗[/red] Назва додатку повинна бути у форматі [bold]snake_case[/bold] "
            "(тільки малі літери, цифри, підкреслення; починається з літери)."
        )
        raise SystemExit(1)

    app_dir = dest / app_name
    if app_dir.exists():
        console.print(f"[red]✗[/red] Директорія [cyan]{app_dir}[/cyan] вже існує.")
        raise SystemExit(1)

    hooks = _get_user_inputs(app_name)
    _create_app_boilerplate(dest, hooks, no_git=no_git)


# ── Interactive prompts ───────────────────────────────────────────────────────


def _prompt_validated(prompt_text: str, validator, error_msg: str, default: str | None = None) -> str:
    while True:
        value = click.prompt(prompt_text, default=default) if default is not None else click.prompt(prompt_text)
        if validator(value):
            return value
        console.print(f"  [red]![/red] {error_msg}")


def _get_user_inputs(app_name: str) -> dict:
    default_title = app_name.replace("_", " ").title()

    console.print(Panel(f"Новий Ґрунт додаток: [bold cyan]{app_name}[/bold cyan]", expand=False))
    console.print()

    title = _prompt_validated(
        "Назва (title)",
        validator=lambda v: bool(v.strip()),
        error_msg="Назва не може бути порожньою.",
        default=default_title,
    )

    description = click.prompt("Опис", default=f"{title} — Grunt app")
    author = click.prompt("Автор (ім'я або організація)")

    email = _prompt_validated(
        "Email автора",
        validator=is_valid_email,
        error_msg="Невірний формат email.",
    )

    version = click.prompt("Версія", default="0.1.0")
    icon = click.prompt("Іконка (emoji)", default="📦")
    color = click.prompt("Колір accent (hex)", default="#2D6A4F")

    module = _prompt_validated(
        "Назва модуля (snake_case)",
        validator=is_valid_module_name,
        error_msg="Назва модуля повинна бути у форматі snake_case.",
        default=app_name,
    )

    use_git = click.confirm("\nІніціалізувати git репозиторій?", default=True)
    console.print()

    return {
        "app_name": app_name,
        "title": title,
        "description": description,
        "author": author,
        "email": email,
        "version": version,
        "icon": icon,
        "color": color,
        "module": module,
        "use_git": use_git,
    }


# ── Directory scaffold ────────────────────────────────────────────────────────


def _create_app_boilerplate(dest: Path, hooks: dict, no_git: bool = False) -> None:
    app_name: str = hooks["app_name"]
    module: str = hooks["module"]
    app_dir = dest / app_name

    for subdir in [
        app_dir / module / "doctypes",
        app_dir / module / "fixtures",
        app_dir / module / "templates",
    ]:
        subdir.mkdir(parents=True)

    _write_grunt_app_py(app_dir, module, hooks)
    _write_app_json(app_dir, module, hooks)
    _write_install_py(app_dir, hooks)
    _write_readme(app_dir, hooks)
    _write_gitignore(app_dir)
    _write_module_init(app_dir, module, hooks)
    _write_hooks_py(app_dir, module, hooks)
    _write_tasks_py(app_dir, module, hooks)
    _write_routes_py(app_dir, module, hooks)
    _write_doctypes_init(app_dir, module)
    _write_fixtures_init(app_dir, module)
    _write_workspace_fixture(app_dir, module, hooks)

    if not no_git and hooks.get("use_git", True):
        _init_git(app_dir)

    _print_summary(app_dir, app_name)


# ── File writers ──────────────────────────────────────────────────────────────


def _write_grunt_app_py(app_dir: Path, module: str, h: dict) -> None:
    (app_dir / "grunt_app.py").write_text(
        grunt_app_template.format(
            title=h["title"],
            app_name=h["app_name"],
            version=h["version"],
            description=h["description"],
            author=h["author"],
            email=h["email"],
            icon=h["icon"],
            color=h["color"],
            module=module,
        ),
        encoding="utf-8",
    )


def _write_app_json(app_dir: Path, module: str, h: dict) -> None:
    data = {
        "name": h["app_name"],
        "title": h["title"],
        "version": h["version"],
        "description": h["description"],
        "author": h["author"],
        "email": h["email"],
        "icon": h["icon"],
        "color": h["color"],
        "modules": [module],
        "depends_on": [],
    }
    (app_dir / "app.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_install_py(app_dir: Path, h: dict) -> None:
    (app_dir / "install.py").write_text(
        install_template.format(title=h["title"], app_name=h["app_name"]),
        encoding="utf-8",
    )


def _write_readme(app_dir: Path, h: dict) -> None:
    (app_dir / "README.md").write_text(
        readme_template.format(
            title=h["title"],
            description=h["description"],
            author=h["author"],
            email=h["email"],
            app_name=h["app_name"],
        ),
        encoding="utf-8",
    )


def _write_gitignore(app_dir: Path) -> None:
    (app_dir / ".gitignore").write_text(gitignore_template, encoding="utf-8")


def _write_module_init(app_dir: Path, module: str, h: dict) -> None:
    (app_dir / module / "__init__.py").write_text(
        f'"""Module {module} for {h["title"]}."""\n',
        encoding="utf-8",
    )


def _write_hooks_py(app_dir: Path, module: str, h: dict) -> None:
    (app_dir / module / "hooks.py").write_text(
        hooks_template.format(title=h["title"]),
        encoding="utf-8",
    )


def _write_tasks_py(app_dir: Path, module: str, h: dict) -> None:
    (app_dir / module / "tasks.py").write_text(
        tasks_template.format(title=h["title"]),
        encoding="utf-8",
    )


def _write_routes_py(app_dir: Path, module: str, h: dict) -> None:
    (app_dir / module / "routes.py").write_text(
        routes_template.format(title=h["title"], app_name=h["app_name"]),
        encoding="utf-8",
    )


def _write_doctypes_init(app_dir: Path, module: str) -> None:
    (app_dir / module / "doctypes" / "__init__.py").write_text("", encoding="utf-8")


def _write_fixtures_init(app_dir: Path, module: str) -> None:
    (app_dir / module / "fixtures" / "__init__.py").write_text("", encoding="utf-8")


def _write_workspace_fixture(app_dir: Path, module: str, h: dict) -> None:
    data = [
        {
            "name": h["app_name"],
            "label": h["title"],
            "icon": h["icon"],
            "color": h["color"],
            "description": h["description"],
            "items": [],
        }
    ]
    (app_dir / module / "fixtures" / "00_workspace.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# ── Git ───────────────────────────────────────────────────────────────────────


def _init_git(app_dir: Path) -> None:
    try:
        subprocess.run(["git", "init", str(app_dir)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(app_dir), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(app_dir), "commit", "-m", "Initial commit (grunt app create)"],
            check=True,
            capture_output=True,
        )
        console.print("  [dim]git: репозиторій ініціалізовано з initial commit.[/dim]")
    except subprocess.CalledProcessError as exc:
        console.print(f"  [yellow]![/yellow] git: не вдалося ініціалізувати — {exc}", err=True)
    except FileNotFoundError:
        console.print("  [yellow]![/yellow] git: не знайдено, пропускаємо.")


# ── Summary ───────────────────────────────────────────────────────────────────


def _print_summary(app_dir: Path, app_name: str) -> None:
    tree = Tree(f"[bold cyan]{app_name}/[/bold cyan]")
    _build_tree(tree, app_dir, app_dir)

    console.print(f"[green]✓[/green] Додаток [bold]{app_name}[/bold] створено у {app_dir}")
    console.print()
    console.print(tree)
    console.print()
    console.print("Наступні кроки:")
    console.print(f"  [cyan]grunt app install {app_name}[/cyan]")
    console.print("  [cyan]grunt serve --reload[/cyan]")


def _build_tree(node, base: Path, current: Path) -> None:
    """Recursively build a Rich Tree from the directory."""
    for p in sorted(current.iterdir()):
        if p.name == ".git":
            continue
        if p.is_dir():
            branch = node.add(f"[bold]{p.name}/[/bold]")
            _build_tree(branch, base, p)
        else:
            node.add(f"[dim]{p.name}[/dim]")


# ── Templates ─────────────────────────────────────────────────────────────────

grunt_app_template = '''\
"""{title}."""

APP_NAME = "{app_name}"
APP_TITLE = "{title}"
APP_VERSION = "{version}"
APP_DESCRIPTION = "{description}"
APP_AUTHOR = "{author}"
APP_EMAIL = "{email}"
APP_ICON = "{icon}"
APP_COLOR = "{color}"
MODULES = ["{module}"]
DEPENDS_ON = []
'''

install_template = '''\
"""Installation hook for {title}.

Called automatically after `grunt app install {app_name}`.
Use this file for setup that fixtures cannot cover (e.g. role creation,
initial settings, computed seed data).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

import structlog

logger = structlog.get_logger()


async def after_install(session: AsyncSession, site_name: str) -> None:
    """Run once when the app is first installed on a site."""
    logger.info("{app_name}.install", site=site_name, status="ok")
    # TODO: add roles, settings, or other one-time setup here
'''

hooks_template = '''\
"""Event hooks for {title}.

Register handlers with @on("<event>").

Supported events:
  before_save     — before a document is saved (new or existing)
  after_save      — after a document is saved
  before_delete   — before a document is deleted
  after_delete    — after a document is deleted
  on_transition   — after a workflow state transition
  on_submit       — after a document is submitted
"""

from __future__ import annotations

from typing import Any

# from grunt.core.hooks import on
# import structlog
#
# logger = structlog.get_logger()
#
#
# @on("before_save")
# async def my_before_save_hook(
#     doctype: str,
#     doc: dict[str, Any],
#     user: Any,
#     session: Any,
#     **kwargs: Any,
# ) -> None:
#     if doctype != "MyDocType":
#         return
#     # your logic here
'''

tasks_template = '''\
"""Background tasks for {title}.

Tasks are discovered automatically from this file if the module
is listed in MODULES and the app is installed.

Usage:
    from grunt.core.tasks.broker import retryable_task

    @retryable_task()
    async def my_task(param: str) -> None:
        ...

Dispatch from anywhere:
    await my_task.kiq(param="value")
"""

from __future__ import annotations

# from grunt.core.tasks.broker import retryable_task
# import structlog
#
# logger = structlog.get_logger()
#
#
# @retryable_task()
# async def example_task(doc_id: str) -> None:
#     logger.info("example_task.start", doc_id=doc_id)
'''

routes_template = '''\
"""Custom FastAPI routes for {title}.

This router is mounted automatically at /api/v1/x/{app_name}/ when
the module is registered. Use it for endpoints not covered by the
generic /docs/* CRUD API.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/{app_name}", tags=["{title}"])


# @router.get("/ping")
# async def ping() -> dict:
#     return {{"status": "ok", "app": "{app_name}"}}
'''

readme_template = '''\
# {title}

{description}

## Встановлення

```bash
grunt app install {app_name}
grunt serve --reload
```

## Розробка

```bash
# Додати DocType
grunt doctype scaffold MyDocType --app {app_name}

# Переглянути встановлені DocTypes
grunt doctype list
```

## Автор

{author} <{email}>
'''

gitignore_template = '''\
# Python
__pycache__/
*.py[cod]
*.pyo
*.pyd
.Python
*.egg-info/
dist/
build/
.eggs/
.venv/
venv/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Grunt
*.db
*.db-shm
*.db-wal
.env
.env.*
!.env.example
'''
