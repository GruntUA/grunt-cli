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
from jinja2 import Environment, PackageLoader, select_autoescape
from rich.console import Console
from rich.panel import Panel
from rich.tree import Tree

console = Console()

# ── Jinja Environment ─────────────────────────────────────────────────────────

env = Environment(
    loader=PackageLoader("grunt_cli", "templates"),
    autoescape=select_autoescape(),
)


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
        if default is not None:
            value = click.prompt(prompt_text, default=default)
        else:
            value = click.prompt(prompt_text)
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
    content = env.get_template("grunt_app.py.j2").render(
        title=h["title"],
        app_name=h["app_name"],
        version=h["version"],
        description=h["description"],
        author=h["author"],
        email=h["email"],
        icon=h["icon"],
        color=h["color"],
        module=module,
    )
    (app_dir / "grunt_app.py").write_text(content, encoding="utf-8")


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
    content = env.get_template("install.py.j2").render(
        title=h["title"],
        app_name=h["app_name"],
    )
    (app_dir / "install.py").write_text(content, encoding="utf-8")


def _write_readme(app_dir: Path, h: dict) -> None:
    content = env.get_template("README.md.j2").render(
        title=h["title"],
        description=h["description"],
        author=h["author"],
        email=h["email"],
        app_name=h["app_name"],
    )
    (app_dir / "README.md").write_text(content, encoding="utf-8")


def _write_gitignore(app_dir: Path) -> None:
    content = env.get_template("gitignore.j2").render()
    (app_dir / ".gitignore").write_text(content, encoding="utf-8")


def _write_module_init(app_dir: Path, module: str, h: dict) -> None:
    (app_dir / module / "__init__.py").write_text(
        f'"""Module {module} for {h["title"]}."""\n',
        encoding="utf-8",
    )


def _write_hooks_py(app_dir: Path, module: str, h: dict) -> None:
    content = env.get_template("hooks.py.j2").render(title=h["title"])
    (app_dir / module / "hooks.py").write_text(content, encoding="utf-8")


def _write_tasks_py(app_dir: Path, module: str, h: dict) -> None:
    content = env.get_template("tasks.py.j2").render(title=h["title"])
    (app_dir / module / "tasks.py").write_text(content, encoding="utf-8")


def _write_routes_py(app_dir: Path, module: str, h: dict) -> None:
    content = env.get_template("routes.py.j2").render(
        title=h["title"],
        app_name=h["app_name"],
    )
    (app_dir / module / "routes.py").write_text(content, encoding="utf-8")


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


# (Templates moved to grunt_cli/templates/)
