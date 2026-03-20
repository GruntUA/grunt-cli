"""grunt doctype * — управління DocTypes."""

from __future__ import annotations

import click
import httpx
from rich import box
from rich.table import Table

from grunt_cli.helpers import DEFAULT_API, auth_headers, console


@click.group()
def doctype() -> None:
    """Команди для управління DocTypes."""


@doctype.command("list")
@click.option("--module", "-m", default=None, help="Фільтр по модулю")
@click.option("--api", default=DEFAULT_API, show_default=True)
def doctype_list(module: str | None, api: str) -> None:
    """Виводить список усіх DocTypes."""
    try:
        params = {"module": module} if module else {}
        resp = httpx.get(
            f"{api}/api/v1/meta/doctypes",
            headers=auth_headers(),
            params=params,
            timeout=5.0,
        )
        resp.raise_for_status()
        doctypes = resp.json()["data"]
    except httpx.ConnectError:
        console.print(f"[red]✗[/red] Не можу підключитись до {api}. Запусти [cyan]grunt serve[/cyan]")
        return

    if not doctypes:
        console.print("[dim]DocTypes не знайдено[/dim]")
        return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("Назва", style="cyan")
    table.add_column("Label")
    table.add_column("Модуль", style="dim")
    table.add_column("Полів", justify="right")
    table.add_column("Child", justify="center")

    for dt in doctypes:
        table.add_row(
            dt["name"],
            dt["label"],
            dt["module"],
            str(len(dt.get("fields", []))),
            "✓" if dt.get("is_child") else "",
        )

    console.print(table)
    console.print(f"[dim]Всього: {len(doctypes)}[/dim]")


@doctype.command("show")
@click.argument("name")
@click.option("--api", default=DEFAULT_API, show_default=True)
def doctype_show(name: str, api: str) -> None:
    """Показує деталі DocType включно з полями."""
    try:
        resp = httpx.get(
            f"{api}/api/v1/meta/doctypes/{name}",
            headers=auth_headers(),
            timeout=5.0,
        )
        if resp.status_code == 404:
            console.print(f"[red]✗[/red] DocType '{name}' не знайдено")
            return
        resp.raise_for_status()
        dt = resp.json()["data"]
    except httpx.ConnectError:
        console.print("[red]✗[/red] Сервер недоступний")
        return

    console.print(f"\n[bold]{dt['name']}[/bold]  [dim]{dt['label']}[/dim]")
    console.print(f"Модуль: [cyan]{dt['module']}[/cyan]\n")

    table = Table(box=box.SIMPLE, show_header=True)
    table.add_column("fieldname", style="cyan")
    table.add_column("label")
    table.add_column("type", style="magenta")
    table.add_column("required", justify="center")
    table.add_column("in_list", justify="center")

    layout_skip = {"Section", "Column", "Tab"}
    for f in dt.get("fields", []):
        if f["fieldtype"] in layout_skip:
            continue
        table.add_row(
            f["fieldname"],
            f["label"],
            f["fieldtype"],
            "✓" if f.get("required") else "",
            "✓" if f.get("in_list_view") else "",
        )

    console.print(table)


@doctype.command("sync")
@click.argument("name")
@click.option("--api", default=DEFAULT_API, show_default=True)
def doctype_sync(name: str, api: str) -> None:
    """Синхронізує DocType зі схемою БД."""
    try:
        resp = httpx.post(
            f"{api}/api/v1/meta/doctypes/{name}/sync",
            headers=auth_headers(),
            timeout=10.0,
        )
        if resp.status_code == 404:
            console.print(f"[red]✗[/red] DocType '{name}' не знайдено")
            return
        resp.raise_for_status()
        result = resp.json()["data"]
    except httpx.ConnectError:
        console.print("[red]✗[/red] Сервер недоступний. Запусти [cyan]grunt serve[/cyan]")
        return

    console.print(f"[green]✓[/green] Синхронізовано: {result.get('table_name', name)}")
    added = result.get("columns_added") or []
    if added:
        console.print(f"  Додано колонки: {', '.join(added)}")
    else:
        console.print("  [dim]Змін у схемі не було[/dim]")
