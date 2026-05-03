"""grunt fixtures — управління тестовими даними (dump/load)."""

from __future__ import annotations

import json
from pathlib import Path

import click

from grunt_cli.helpers import console, run_venv_script


@click.group()
def fixtures() -> None:
    """Команди для управління тестовими даними."""


@fixtures.command("dump")
@click.argument("doctype")
@click.option("-o", "--output", default=None, help="Вихідний файл (за замовчуванням: <doctype>_fixtures.json)")
@click.option("--limit", default=None, type=int, help="Максимум записів")
@click.option("--filters", default=None, help='JSON фільтри, напр. {"status": "Active"}')
@click.option("--site", default=None, help="Назва сайту")
def fixtures_dump(doctype: str, output: str | None, limit: int | None, filters: str | None, site: str | None) -> None:
    """Експортувати записи DocType у JSON файл.

    \b
    Приклади:
      grunt fixtures dump Invoice
      grunt fixtures dump Invoice -o my_invoices.json --limit 100
      grunt fixtures dump Invoice --filters '{"status": "Draft"}'
    """
    parsed_filters: dict = {}
    if filters:
        try:
            parsed_filters = json.loads(filters)
        except json.JSONDecodeError:
            console.print(f"[red]✗[/red] Невірний JSON у --filters: {filters}")
            raise SystemExit(1)

    output_file = output or f"{doctype.lower()}_fixtures.json"
    per_page = limit or 1000
    filters_repr = repr(parsed_filters)
    output_repr = repr(output_file)

    script = f"""
import asyncio, json
from grunt.app import grunt
from grunt.cli.utils import _site_session
import os

site = os.environ.get('GRUNT_SITE')

async def _run():
    async with _site_session(site) as (session, _):
        items = await grunt.get_list({doctype!r}, session=session, per_page={per_page}, filters={filters_repr})
        result = {{"doctype": {doctype!r}, "records": items, "count": len(items)}}
        out_file = {output_repr}
        import pathlib
        pathlib.Path(out_file).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Exported {{len(items)}} records to {{out_file}}")

asyncio.run(_run())
"""
    rc = run_venv_script(script, site=site)
    if rc == -1:
        console.print("[red]✗[/red] Backend venv не знайдено. Запустіть у папці проекту.")
    raise SystemExit(0 if rc in (0, -1) else rc)


@fixtures.command("load")
@click.argument("file", type=click.Path(exists=True))
@click.option("--mode", type=click.Choice(["create", "upsert", "update"]), default="create",
              help="Режим: create (помилка якщо існує), upsert, update")
@click.option("--skip-errors", is_flag=True, help="Продовжити при помилках")
@click.option("--site", default=None, help="Назва сайту")
def fixtures_load(file: str, mode: str, skip_errors: bool, site: str | None) -> None:
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

    if not doctype or not isinstance(records, list):
        console.print("[red]✗[/red] Файл повинен мати ключі 'doctype' та 'records'")
        raise SystemExit(1)

    records_repr = json.dumps(records, ensure_ascii=False)
    skip_flag = "True" if skip_errors else "False"

    script = f"""
import asyncio, json
from grunt.app import grunt
from grunt.cli.utils import _site_session
import os

site = os.environ.get('GRUNT_SITE')
doctype = {doctype!r}
mode = {mode!r}
skip_errors = {skip_flag}
records = json.loads({records_repr!r})

SKIP_FIELDS = {{"id", "docstatus", "creation", "modified", "modified_by"}}

async def _run():
    success = 0
    errors = 0
    async with _site_session(site) as (session, _):
        for i, rec in enumerate(records, 1):
            rec_id = rec.get("id") or rec.get("name")
            rec_clean = {{k: v for k, v in rec.items() if k not in SKIP_FIELDS}}
            try:
                if mode == "create":
                    await grunt.new_doc(doctype, rec_clean, session=session)
                elif mode == "update":
                    if not rec_id:
                        raise ValueError("id/name required for update mode")
                    await grunt.set_value(doctype, rec_id, rec_clean, session=session)
                else:  # upsert
                    try:
                        if rec_id:
                            await grunt.set_value(doctype, rec_id, rec_clean, session=session)
                        else:
                            await grunt.new_doc(doctype, rec_clean, session=session)
                    except Exception:
                        await grunt.new_doc(doctype, rec_clean, session=session)
                success += 1
            except Exception as e:
                errors += 1
                print(f"  ! Запис {{i}}: {{e}}")
                if not skip_errors:
                    await session.commit()
                    print(f"Завантажено: {{success}} успішно, {{errors}} помилок")
                    raise SystemExit(1)
        await session.commit()
    print(f"Завантажено: {{success}} успішно, {{errors}} помилок")

asyncio.run(_run())
"""
    rc = run_venv_script(script, site=site)
    if rc == -1:
        console.print("[red]✗[/red] Backend venv не знайдено. Запустіть у папці проекту.")
    raise SystemExit(0 if rc in (0, -1) else rc)
