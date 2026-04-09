"""grunt fixtures — управління тестовими даними (dump/load)."""

from __future__ import annotations

import json
from pathlib import Path

import click
import httpx
from rich.progress import track

from grunt_cli.helpers import DEFAULT_API, auth_headers, console


@click.group()
def fixtures() -> None:
    """Команди для управління тестовими даними."""


@fixtures.command("dump")
@click.argument("doctype")
@click.option("-o", "--output", default=None, help="Вихідний файл (за замовчуванням: <doctype>_fixtures.json)")
@click.option("--limit", default=None, type=int, help="Максимум записів")
@click.option("--filters", default=None, help='JSON фільтри, напр. {\"status\": \"Active\"}')
@click.option("--api", default=DEFAULT_API, show_default=True)
def fixtures_dump(doctype: str, output: str | None, limit: int | None, filters: str | None, api: str) -> None:
    """Експортувати записи DocType у JSON файл для тестування.

    \b
    Приклади:
      grunt fixtures dump Invoice
      grunt fixtures dump Invoice -o my_invoices.json --limit 100
      grunt fixtures dump Invoice --filters '{"status": "Draft"}'
    """
    # Parse filters
    parsed_filters = {}
    if filters:
        try:
            parsed_filters = json.loads(filters)
        except json.JSONDecodeError:
            console.print(f"[red]✗[/red] Невірний JSON у --filters: {filters}")
            raise SystemExit(1)

    # Fetch records
    try:
        resp = httpx.get(
            f"{api}/api/v1/docs/{doctype}",
            headers=auth_headers(),
            params={"per_page": limit or 1000, **parsed_filters},
            timeout=30.0,
        )
        if resp.status_code == 404:
            console.print(f"[red]✗[/red] DocType '{doctype}' не знайдено")
            raise SystemExit(1)
        resp.raise_for_status()
        body = resp.json()
    except httpx.ConnectError:
        console.print("[red]✗[/red] Сервер недоступний. Запусти [cyan]grunt serve[/cyan]")
        raise SystemExit(1)

    records = body.get("data", [])
    if not records:
        console.print(f"[yellow]![/yellow] Записів для '{doctype}' не знайдено")
        return

    # Prepare output
    fixture_data = {
        "doctype": doctype,
        "records": records,
        "count": len(records),
    }

    output_file = output or f"{doctype.lower()}_fixtures.json"
    Path(output_file).write_text(json.dumps(fixture_data, ensure_ascii=False, indent=2), encoding="utf-8")

    console.print(f"[green]✓[/green] Експортовано [cyan]{len(records)}[/cyan] записів")
    console.print(f"  Файл: [dim]{output_file}[/dim]")
    console.print(f"  Завантажити: [dim]grunt fixtures load {output_file}[/dim]")


@fixtures.command("load")
@click.argument("file", type=click.Path(exists=True))
@click.option("--mode", type=click.Choice(["create", "upsert", "update"]), default="create",
              help="Режим: create (помилка якщо існує), upsert (update if exists), update (тільки update)")
@click.option("--skip-errors", is_flag=True, help="Продовжити при помилках")
@click.option("--api", default=DEFAULT_API, show_default=True)
def fixtures_load(file: str, mode: str, skip_errors: bool, api: str) -> None:
    """Завантажити тестові дані з JSON файлу.

    \b
    Приклади:
      grunt fixtures load invoices.json
      grunt fixtures load invoices.json --mode upsert
      grunt fixtures load invoices.json --skip-errors
    """
    try:
        data = json.loads(Path(file).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        console.print(f"[red]✗[/red] Помилка JSON у файлі: {e}")
        raise SystemExit(1)

    doctype = data.get("doctype")
    records = data.get("records", [])

    if not doctype or not records:
        console.print("[red]✗[/red] Файл повинен мати ключи 'doctype' и 'records'")
        raise SystemExit(1)

    console.print(f"Завантажу {len(records)} записів у [cyan]{doctype}[/cyan]...")

    success = 0
    errors = 0

    for i, rec in track(enumerate(records, 1), total=len(records), description="Завантаження..."):
        # Remove system fields
        rec_clean = {k: v for k, v in rec.items() if k not in ("id", "docstatus", "creation", "modified", "modified_by")}
        rec_id = rec.get("id") or rec.get("name")

        try:
            if mode == "create":
                resp = httpx.post(
                    f"{api}/api/v1/docs/{doctype}",
                    headers=auth_headers(),
                    json=rec_clean,
                    timeout=10.0,
                )
            elif mode == "upsert":
                # Try update first, fall back to create
                if rec_id:
                    resp = httpx.put(
                        f"{api}/api/v1/docs/{doctype}/{rec_id}",
                        headers=auth_headers(),
                        json=rec_clean,
                        timeout=10.0,
                    )
                    if resp.status_code == 404:
                        resp = httpx.post(
                            f"{api}/api/v1/docs/{doctype}",
                            headers=auth_headers(),
                            json=rec_clean,
                            timeout=10.0,
                        )
                else:
                    resp = httpx.post(
                        f"{api}/api/v1/docs/{doctype}",
                        headers=auth_headers(),
                        json=rec_clean,
                        timeout=10.0,
                    )
            else:  # mode == "update"
                if not rec_id:
                    raise ValueError("id/name field required for update mode")
                resp = httpx.put(
                    f"{api}/api/v1/docs/{doctype}/{rec_id}",
                    headers=auth_headers(),
                    json=rec_clean,
                    timeout=10.0,
                )

            if resp.status_code in (200, 201):
                success += 1
            else:
                errors += 1
                if not skip_errors:
                    console.print(f"  [red]✗[/red] Запис {i}: {resp.status_code} {resp.text[:100]}")
                    if not skip_errors:
                        raise SystemExit(1)
        except Exception as e:
            errors += 1
            if not skip_errors:
                console.print(f"  [red]✗[/red] Запис {i}: {e}")
                raise SystemExit(1)

    console.print(f"\n[green]✓[/green] Завантажено: {success} успішно, {errors} помилок")
    if errors > 0 and not skip_errors:
        raise SystemExit(1)
