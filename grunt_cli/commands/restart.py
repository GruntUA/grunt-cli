"""grunt restart — перезапуск продакшн-сервісів проєкту (systemd)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import click

from grunt_cli.helpers import console, get_bench_dir

SYSTEMD_DIR = Path("/etc/systemd/system")


@click.command()
@click.option("--web", "only_web", is_flag=True, help="Лише веб-сервіс (uvicorn)")
@click.option("--worker", "only_worker", is_flag=True, help="Лише фоновий воркер")
def restart(only_web: bool, only_worker: bool) -> None:
    """Перезапустити сервіси проєкту: <bench>-web і <bench>-worker.

    \b
    Сервіси встановлює `grunt setup production`. У розробці перезапускайте
    `grunt serve` у його терміналі.
    """
    bench = get_bench_dir()
    if bench is None:
        console.print("[red]✗[/red] Bench не знайдено. Запустіть у папці проєкту.")
        raise SystemExit(1)

    kinds = [k for k, only in (("web", only_web), ("worker", only_worker)) if only] or [
        "web",
        "worker",
    ]
    units = [f"{bench.name}-{kind}.service" for kind in kinds]
    missing = [u for u in units if not (SYSTEMD_DIR / u).exists()]
    if missing:
        console.print(f"[red]✗[/red] Сервіс не встановлено: {', '.join(missing)}")
        console.print(
            "  Спершу [cyan]grunt setup production[/cyan] (або в розробці — grunt serve)."
        )
        raise SystemExit(1)
    if not restart_units(units):
        raise SystemExit(1)


def installed_units(bench: Path) -> list[str]:
    """Встановлені systemd-сервіси проєкту (порожньо — це розробка, не прод)."""
    units = [f"{bench.name}-{kind}.service" for kind in ("web", "worker")]
    return [u for u in units if (SYSTEMD_DIR / u).exists()]


def restart_units(units: list[str]) -> bool:
    """``sudo systemctl restart`` + перевірка, що сервіси піднялися."""
    console.print(f"[dim]sudo systemctl restart {' '.join(units)}[/dim]")
    if subprocess.run(["sudo", "systemctl", "restart", *units]).returncode != 0:
        console.print("[red]✗[/red] Не вдалося перезапустити")
        return False

    # Дати сервісам кілька секунд: помилка імпорту чи конфігу валить їх не одразу.
    time.sleep(5)
    failed = [u for u in units if not _is_active(u)]
    for unit in units:
        if unit in failed:
            console.print(f"[red]✗[/red] {unit} не запустився")
        else:
            console.print(f"[green]✓[/green] {unit}")
    if failed:
        console.print(f"  Журнал: [cyan]journalctl -u {failed[0]} -n 50 --no-pager[/cyan]")
        return False
    return True


def _is_active(unit: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", unit], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() == "active"
