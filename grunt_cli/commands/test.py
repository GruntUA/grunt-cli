"""grunt test — запуск тестів проекту або CLI."""

from __future__ import annotations
import subprocess
import sys
import os
from pathlib import Path
import click
from grunt_cli.helpers import console, get_bench_dir, find_uv

@click.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def test(args: tuple[str, ...]) -> None:
    """Запускає тести (проектні або внутрішні для CLI).

    \b
    Якщо ви в папці проекту, запустить тести проекту через pytest.
    В іншому випадку спробує запустити внутрішні тести CLI.
    """
    cwd = Path.cwd()
    
    # 1. Шукаємо проектний pyproject.toml
    project_root = None
    for parent in [cwd, *cwd.parents]:
        if (parent / "pyproject.toml").exists():
            project_root = parent
            break
            
    if project_root:
        console.print(f"[dim]Виявлено проект у {project_root}. Запускаю проектні тести...[/dim]")
        uv_bin = find_uv()
        
        # Перевіряємо, чи є папка backend/tests або tests
        t_paths = ["backend/tests", "tests"]
        found_t = None
        for p in t_paths:
            if (project_root / p).is_dir():
                found_t = p
                break
        
        cmd = []
        if uv_bin:
            cmd = [uv_bin, "run", "pytest"]
        else:
            cmd = ["pytest"]
            
        if found_t and not args:
            cmd.append(found_t)
            
        cmd.extend(args)
        
        result = subprocess.run(cmd, cwd=str(project_root))
        raise SystemExit(result.returncode)

    # 2. Якщо не в проекті — запускаємо тести самого CLI
    cli_dir = Path(__file__).resolve().parent.parent.parent
    tests_dir = cli_dir / "tests"

    if tests_dir.is_dir():
        console.print("[dim]Запускаю внутрішні тести Grunt CLI...[/dim]")
        cmd = [sys.executable, "-m", "pytest", *args]
        result = subprocess.run(cmd, cwd=str(cli_dir))
        raise SystemExit(result.returncode)

    console.print("[red]✗[/red] Не знайдено ні проектних тестів, ні тестів CLI.")
    raise SystemExit(1)
