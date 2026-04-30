"""grunt doctype * — управління DocTypes."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import click
import httpx
from rich import box
from rich.table import Table

from grunt_cli.helpers import (
    DEFAULT_API,
    auth_headers,
    console,
    get_bench_dir,
    get_current_site,
    get_site_dir,
    get_token,
)


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


@doctype.command("test-gen")
@click.argument("name")
@click.option("--output", "-o", default=None, help="Вихідний файл (за замовчуванням: stdout)")
@click.option("--api", default=DEFAULT_API, show_default=True)
def doctype_test_gen(name: str, output: str | None, api: str) -> None:
    """Генерує pytest тести для DocType на основі його метаданих.

    \b
    Приклади:
      grunt doctype test-gen Invoice
      grunt doctype test-gen Invoice -o tests/test_invoice.py
    """
    try:
        resp = httpx.get(
            f"{api}/api/v1/meta/doctypes/{name}",
            headers=auth_headers(),
            timeout=5.0,
        )
        if resp.status_code == 404:
            console.print(f"[red]✗[/red] DocType '{name}' не знайдено")
            raise SystemExit(1)
        resp.raise_for_status()
        dt = resp.json()["data"]
    except httpx.ConnectError:
        console.print("[red]✗[/red] Сервер недоступний. Запусти [cyan]grunt serve[/cyan]")
        raise SystemExit(1)

    content = _generate_tests(dt)

    if output:
        from pathlib import Path  # noqa: PLC0415
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        console.print(f"[green]✓[/green] Тести збережено у [cyan]{output}[/cyan]")
        console.print(f"  Запуск: [dim]pytest {output} -v[/dim]")
    else:
        print(content)


_FIELDTYPE_TO_PY: dict[str, str] = {
    "Data":        "str | None",
    "Text":        "str | None",
    "LongText":    "str | None",
    "RichText":    "str | None",
    "Code":        "str | None",
    "Select":      "str | None",
    "Link":        "str | None",
    "Attach":      "str | None",
    "Image":       "str | None",
    "Color":       "str | None",
    "Signature":   "str | None",
    "Int":         "int | None",
    "Float":       "float | None",
    "Check":       "bool",
    "Date":        "datetime.date | None",
    "Datetime":    "datetime.datetime | None",
    "Time":        "datetime.time | None",
    "JSON":        "dict | list | None",
    "Geolocation": "dict | None",
    "MultiLink":   "list[str]",
}

_NON_PHYSICAL = {"Section", "Column", "Tab", "Empty"}


def _make_controller(name: str, fields: list[dict] | None = None) -> str:
    skip_names = {"name", "id", "docstatus", "owner", "created_at", "modified_at", "modified_by"}
    physical = [
        f for f in (fields or [])
        if f.get("fieldtype") not in _NON_PHYSICAL and f.get("fieldname") not in skip_names
    ]

    needs_datetime = any(
        f["fieldtype"] in {"Date", "Datetime", "Time"} for f in physical
    )
    datetime_import = "import datetime\n" if needs_datetime else ""

    I = "    "   # 4-space indent
    II = I * 2  # 8-space indent

    if physical:
        field_lines = "\n".join(
            f"{II}{f['fieldname']}: {_FIELDTYPE_TO_PY.get(f['fieldtype'], 'Any')}"
            + (f"  # {f['label']}" if f.get("label") and f["label"] != f["fieldname"] else "")
            for f in physical
            if f["fieldtype"] not in {"Table", "MultiLink"}
        )
        table_lines = "\n".join(
            f"{II}{f['fieldname']}: list[dict]  # Table: {f.get('options', '?')}"
            for f in physical
            if f["fieldtype"] == "Table"
        )
        all_field_lines = "\n".join(filter(None, [field_lines, table_lines]))
        type_block = (
            f"{I}# begin: auto-generated types\n"
            f"{I}# This code is auto-generated. Do not modify anything in this block.\n"
            f"\n"
            f"{I}if TYPE_CHECKING:\n"
            f"{all_field_lines}\n"
            f"{I}# end: auto-generated types\n"
            f"\n"
        )
        typing_imports = "from typing import TYPE_CHECKING, Any\n"
    else:
        type_block = ""
        typing_imports = "from typing import Any\n"

    return (
        f'"""{name} controller.\n'
        f"\n"
        f"Business logic for {name} DocType.\n"
        f'"""\n'
        f"\n"
        f"from __future__ import annotations\n"
        f"\n"
        f"{datetime_import}"
        f"{typing_imports}"
        f"\n"
        f"\n"
        f"class {name}Controller:\n"
        f'{I}"""Controller for {name} documents."""\n'
        f"\n"
        f"{type_block}"
        f"{I}def __init__(self, doc: dict[str, Any], session: Any | None = None) -> None:\n"
        f"{II}self.doc = doc\n"
        f"{II}self.session = session\n"
        f"\n"
        f"{I}async def before_insert(self) -> None:\n"
        f'{II}"""Called before inserting a new document."""\n'
        f"\n"
        f"{I}async def after_insert(self) -> None:\n"
        f'{II}"""Called after inserting a new document."""\n'
        f"\n"
        f"{I}async def before_save(self) -> None:\n"
        f'{II}"""Called before saving (new or existing)."""\n'
        f"\n"
        f"{I}async def after_save(self) -> None:\n"
        f'{II}"""Called after saving."""\n'
        f"\n"
        f"{I}async def before_delete(self) -> None:\n"
        f'{II}"""Called before deletion."""\n'
        f"\n"
        f"{I}async def after_delete(self) -> None:\n"
        f'{II}"""Called after deletion."""\n'
        f"\n"
        f"{I}async def validate(self) -> None:\n"
        f'{II}"""Called during validation — raise ValueError to block save."""\n'
    )


def _fake_value(fieldtype: str, fieldname: str, options: str | None = None) -> object:
    """Generate a realistic fake value for a field type."""
    mapping: dict[str, object] = {
        "Data":        f"Test {fieldname.replace('_', ' ').title()}",
        "Text":        f"Test {fieldname} value",
        "LongText":    f"Long text for {fieldname}",
        "Int":         42,
        "Float":       3.14,
        "Check":       True,
        "Date":        "2026-01-15",
        "Datetime":    "2026-01-15T10:00:00",
        "Time":        "10:00:00",
        "Color":       "#2D6A4F",
        "RichText":    "<p>Test content</p>",
        "Code":        "# test code",
        "Rating":      4,
        "Percent":     75.0,
        "Duration":    3600.0,
        "JSON":        {},
    }
    if fieldtype == "Select" and options:
        first_opt = options.split("\n")[0].strip()
        return first_opt if first_opt else "Option1"
    return mapping.get(fieldtype, f"test_{fieldname}")


def _generate_tests(dt: dict) -> str:
    name = dt["name"]
    snake = name.lower().replace(" ", "_")
    fields = dt.get("fields", [])

    skip_types = {"Section", "Column", "Tab", "Table", "Empty", "Attach", "Image",
                  "MultiLink", "Link", "Geolocation", "Signature", "BarCode", "HTMLEditor"}
    skip_names = {"name", "id", "docstatus", "idx", "owner", "creation",
                  "modified", "modified_at", "modified_by", "created_at", "created_by"}

    required_fields = [
        f for f in fields
        if f.get("required") and f["fieldtype"] not in skip_types and f["fieldname"] not in skip_names
    ]
    optional_fields = [
        f for f in fields
        if not f.get("required") and f["fieldtype"] not in skip_types and f["fieldname"] not in skip_names
    ][:3]  # take up to 3 optional fields for the update test

    def fields_dict(flist: list) -> str:
        items = []
        for f in flist:
            val = _fake_value(f["fieldtype"], f["fieldname"], f.get("options"))
            items.append(f'        "{f["fieldname"]}": {val!r}')
        return "{\n" + ",\n".join(items) + (",\n    }" if items else "    }")

    required_dict = fields_dict(required_fields)

    # For update test, use optional fields if any, else change a required field
    update_flist = optional_fields if optional_fields else required_fields[:1]
    update_dict = fields_dict(update_flist)

    required_assertions = "\n".join(
        f'        assert data["{f["fieldname"]}"] == {_fake_value(f["fieldtype"], f["fieldname"], f.get("options"))!r}'
        for f in required_fields
    )

    missing_required_comment = (
        "# No required fields defined — empty payload may succeed" if not required_fields
        else "# Required fields omitted intentionally"
    )
    missing_required_expected = (
        "assert resp.status_code in (200, 201, 422)"
        if not required_fields
        else "assert resp.status_code == 422"
    )

    return f'''"""Tests for the {name} DocType.

Auto-generated by: grunt doctype test-gen {name}

Usage:
    pytest tests/test_{snake}.py -v

Requires the grunt test conftest.py fixture (client, auth_headers, setup_db).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


DOCTYPE = "{name}"
BASE_URL = f"/api/v1/docs/{{DOCTYPE}}"


# ── Sample payloads ───────────────────────────────────────────────────────────

VALID_PAYLOAD = {required_dict}

UPDATE_PAYLOAD = {update_dict}


# ── CRUD tests ────────────────────────────────────────────────────────────────


class Test{name}CRUD:
    """Basic CRUD tests for the {name} DocType."""

    async def test_create_{snake}(self, client: AsyncClient, auth_headers: dict) -> None:
        """Create a valid {name} document."""
        resp = await client.post(BASE_URL, json=VALID_PAYLOAD, headers=auth_headers)
        assert resp.status_code in (200, 201), resp.text
        data = resp.json()["data"]
        assert data.get("id")
{required_assertions}

    async def test_get_{snake}(self, client: AsyncClient, auth_headers: dict) -> None:
        """Fetch a {name} by id."""
        create = await client.post(BASE_URL, json=VALID_PAYLOAD, headers=auth_headers)
        assert create.status_code in (200, 201), create.text
        doc_id = create.json()["data"]["id"]

        resp = await client.get(f"{{BASE_URL}}/{{doc_id}}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == doc_id

    async def test_list_{snake}(self, client: AsyncClient, auth_headers: dict) -> None:
        """List {name} documents."""
        await client.post(BASE_URL, json=VALID_PAYLOAD, headers=auth_headers)

        resp = await client.get(BASE_URL, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert isinstance(body["data"], list)
        assert len(body["data"]) >= 1

    async def test_update_{snake}(self, client: AsyncClient, auth_headers: dict) -> None:
        """Update a {name} document."""
        create = await client.post(BASE_URL, json=VALID_PAYLOAD, headers=auth_headers)
        assert create.status_code in (200, 201), create.text
        doc_id = create.json()["data"]["id"]

        resp = await client.put(f"{{BASE_URL}}/{{doc_id}}", json=UPDATE_PAYLOAD, headers=auth_headers)
        assert resp.status_code == 200, resp.text

    async def test_delete_{snake}(self, client: AsyncClient, auth_headers: dict) -> None:
        """Delete a {name} document and verify it\'s gone."""
        create = await client.post(BASE_URL, json=VALID_PAYLOAD, headers=auth_headers)
        assert create.status_code in (200, 201), create.text
        doc_id = create.json()["data"]["id"]

        del_resp = await client.delete(f"{{BASE_URL}}/{{doc_id}}", headers=auth_headers)
        assert del_resp.status_code in (200, 204), del_resp.text

        get_resp = await client.get(f"{{BASE_URL}}/{{doc_id}}", headers=auth_headers)
        assert get_resp.status_code == 404


# ── Validation tests ──────────────────────────────────────────────────────────


class Test{name}Validation:
    """Input validation tests for the {name} DocType."""

    async def test_missing_required_fields(self, client: AsyncClient, auth_headers: dict) -> None:
        """Posting an empty payload should fail validation if required fields exist."""
        {missing_required_comment}
        resp = await client.post(BASE_URL, json={{}}, headers=auth_headers)
        {missing_required_expected}

    async def test_list_with_filter(self, client: AsyncClient, auth_headers: dict) -> None:
        """List endpoint accepts filter query params without error."""
        resp = await client.get(BASE_URL, params={{"per_page": "5", "page": "1"}}, headers=auth_headers)
        assert resp.status_code == 200

    async def test_get_nonexistent(self, client: AsyncClient, auth_headers: dict) -> None:
        """Fetching a non-existent document returns 404."""
        resp = await client.get(f"{{BASE_URL}}/nonexistent-id-00000", headers=auth_headers)
        assert resp.status_code == 404

    async def test_delete_nonexistent(self, client: AsyncClient, auth_headers: dict) -> None:
        """Deleting a non-existent document returns 404."""
        resp = await client.delete(f"{{BASE_URL}}/nonexistent-id-00000", headers=auth_headers)
        assert resp.status_code == 404


# ── Auth tests ────────────────────────────────────────────────────────────────


class Test{name}Auth:
    """Authentication tests for the {name} DocType."""

    async def test_unauthenticated_list(self, client: AsyncClient) -> None:
        """List without auth token should return 401 or 403."""
        resp = await client.get(BASE_URL)
        assert resp.status_code in (401, 403)

    async def test_unauthenticated_create(self, client: AsyncClient) -> None:
        """Create without auth token should return 401 or 403."""
        resp = await client.post(BASE_URL, json=VALID_PAYLOAD)
        assert resp.status_code in (401, 403)
'''


@doctype.command("export")
@click.argument("name")
@click.option("-o", "--output", default=None, help="Вихідний файл (за замовчуванням: <name>.json)")
@click.option("--include-children", is_flag=True, help="Включити залежні Child DocTypes")
@click.option("--api", default=DEFAULT_API, show_default=True)
def doctype_export(name: str, output: str | None, include_children: bool, api: str) -> None:
    """Експортувати метадані DocType у JSON для версіонування та обміну.

    \b
    Приклади:
      grunt doctype export Invoice
      grunt doctype export Invoice -o Invoice_backup.json
      grunt doctype export Invoice --include-children
    """
    try:
        resp = httpx.get(
            f"{api}/api/v1/meta/doctypes/{name}",
            headers=auth_headers(),
            timeout=5.0,
        )
        if resp.status_code == 404:
            console.print(f"[red]✗[/red] DocType '{name}' не знайдено")
            raise SystemExit(1)
        resp.raise_for_status()
        dt = resp.json()["data"]
    except httpx.ConnectError:
        console.print("[red]✗[/red] Сервер недоступний. Запусти [cyan]grunt serve[/cyan]")
        raise SystemExit(1)

    export_data = {"doctype": dt}

    # Include child doctypes if requested
    if include_children:
        child_doctypes = []
        for field in dt.get("fields", []):
            if field.get("fieldtype") == "Table":
                child_name = field.get("options")
                if child_name:
                    try:
                        child_resp = httpx.get(
                            f"{api}/api/v1/meta/doctypes/{child_name}",
                            headers=auth_headers(),
                            timeout=5.0,
                        )
                        if child_resp.status_code == 200:
                            child_doctypes.append(child_resp.json()["data"])
                    except httpx.ConnectError:
                        pass
        if child_doctypes:
            export_data["children"] = child_doctypes

    output_file = output or f"{name}.json"
    from pathlib import Path  # noqa: PLC0415
    Path(output_file).write_text(json.dumps(export_data, ensure_ascii=False, indent=2), encoding="utf-8")

    console.print(f"[green]✓[/green] Експортовано DocType [cyan]{name}[/cyan]")
    console.print(f"  Файл: [dim]{output_file}[/dim]")
    if include_children and export_data.get("children"):
        console.print(f"  Включено {len(export_data['children'])} child DocTypes")
    console.print(f"  Імпорт: [dim]grunt doctype import {output_file}[/dim]")


@doctype.command("import")
@click.argument("file", type=click.Path(exists=True))
@click.option("--update", is_flag=True, help="Оновити якщо уже існує (без флага - помилка при дублюванні)")
@click.option("--api", default=DEFAULT_API, show_default=True)
def doctype_import(file: str, update: bool, api: str) -> None:
    """Імпортувати метадані DocType з JSON файлу.

    \b
    Приклади:
      grunt doctype import Invoice.json
      grunt doctype import Invoice.json --update
    """
    from pathlib import Path  # noqa: PLC0415

    try:
        data = json.loads(Path(file).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        console.print(f"[red]✗[/red] Помилка JSON: {e}")
        raise SystemExit(1)

    doctypes_to_import = []

    # Extract main doctype
    if "doctype" in data:
        doctypes_to_import.append(data["doctype"])
    elif isinstance(data, dict) and "name" in data:
        doctypes_to_import.append(data)
    else:
        console.print("[red]✗[/red] Файл повинен мати ключ 'doctype' або 'name'")
        raise SystemExit(1)

    # Extract child doctypes if present
    if "children" in data:
        doctypes_to_import.extend(data["children"])

    imported = 0
    errors = 0

    for dt in doctypes_to_import:
        dt_name = dt.get("name")
        is_child = dt.get("is_child", False)

        try:
            # Check if exists
            check = httpx.get(
                f"{api}/api/v1/meta/doctypes/{dt_name}",
                headers=auth_headers(),
                timeout=5.0,
            )

            if check.status_code == 200 and not update:
                console.print(f"  [yellow]![/yellow] {dt_name}: уже існує (використай --update для зміни)")
                errors += 1
                continue

            if check.status_code == 200 and update:
                # Update
                resp = httpx.put(
                    f"{api}/api/v1/meta/doctypes/{dt_name}",
                    headers=auth_headers(),
                    json=dt,
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    imported += 1
                    marker = " (дочірній)" if is_child else ""
                    console.print(f"  [cyan]~[/cyan] {dt_name}{marker}: оновлено")
                else:
                    errors += 1
                    console.print(f"  [red]✗[/red] {dt_name}: {resp.status_code} {resp.text[:80]}")
            else:
                # Create
                resp = httpx.post(
                    f"{api}/api/v1/meta/doctypes",
                    headers=auth_headers(),
                    json=dt,
                    timeout=10.0,
                )
                if resp.status_code in (200, 201):
                    imported += 1
                    marker = " (дочірній)" if is_child else ""
                    console.print(f"  [green]✓[/green] {dt_name}{marker}: створено")
                else:
                    errors += 1
                    console.print(f"  [red]✗[/red] {dt_name}: {resp.status_code} {resp.text[:80]}")

        except httpx.ConnectError:
            console.print("[red]✗[/red] Сервер недоступний. Запусти [cyan]grunt serve[/cyan]")
            raise SystemExit(1)
        except Exception as e:
            errors += 1
            console.print(f"  [red]✗[/red] {dt_name}: {e}")

    console.print(f"\n[green]✓[/green] Імпортовано: {imported} успішно, {errors} помилок")
    if errors > 0 and not update:
        console.print("  💡 Використай [cyan]--update[/cyan] для оновлення існуючих")


@doctype.command("sync")
@click.argument("name")
@click.option("--api", default=DEFAULT_API, show_default=True)
def doctype_sync(name: str, api: str) -> None:
    """Синхронізує DocType зі схемою БД."""

    def _local_sync() -> int:
        bench_dir = get_bench_dir()
        if bench_dir:
            site_dir = get_current_site()
            backend_dir = bench_dir / "apps" / "grunt" / "backend"
            venv_candidates = [
                bench_dir / ".venv",
                bench_dir / "apps" / "grunt" / ".venv",
            ]
            run_cwd = bench_dir
        else:
            site_dir = get_site_dir()
            backend_dir = Path.cwd() / "apps" / "grunt" / "backend"
            venv_candidates = [
                Path.cwd() / ".venv",
                Path.cwd() / "apps" / "grunt" / ".venv",
            ]
            run_cwd = Path.cwd()

        if not site_dir:
            console.print("[red]✗[/red] Сайт не знайдено")
            return 1

        python_bin = next(
            (cand / "bin" / "python" for cand in venv_candidates if (cand / "bin" / "python").exists()),
            None,
        )
        venv_dir = python_bin.parent.parent if python_bin else None

        if not python_bin or not python_bin.exists() or not venv_dir:
            checked = ", ".join(str(p) for p in venv_candidates)
            console.print(f"[red]✗[/red] Python venv не знайдено. Перевірено: {checked}")
            return 1

        script = f"""
import asyncio
from grunt.core.metadata.compiler import get_table_name, sync_table
from grunt.core.metadata.registry import doctype_registry
from grunt.core.site.manager import current_site, site_manager
from grunt.core.startup import load_core_doctypes

TARGET_NAME = {name!r}

async def main():
    sites = site_manager.get_sites()
    target = sites[0] if sites else None
    if not target:
        print("ERROR: no sites found")
        raise SystemExit(1)

    token = current_site.set(target)
    try:
        eng = site_manager.get_engine(target)
        maker = site_manager.get_session_maker(target)
        async with maker() as session:
            await doctype_registry.load_all(session)
            await load_core_doctypes(session, eng)
            dt = await doctype_registry.get(TARGET_NAME)
            await sync_table(dt, eng, session=session)
            await session.commit()
            print(get_table_name(dt.module, dt.name))
    finally:
        current_site.reset(token)

asyncio.run(main())
"""

        env = {
            **os.environ,
            "DOTENV_PATH": str(site_dir / ".env"),
            "PYTHONPATH": str(backend_dir),
            "VIRTUAL_ENV": str(venv_dir),
            "PATH": str(venv_dir / "bin") + os.pathsep + os.environ.get("PATH", ""),
        }

        result = subprocess.run(
            [str(python_bin), "-c", script],
            capture_output=True,
            text=True,
            cwd=str(run_cwd),
            env=env,
        )

        if result.returncode != 0:
            if result.stderr.strip():
                console.print(f"[red]✗[/red] {result.stderr.strip()}")
            else:
                console.print("[red]✗[/red] Локальна синхронізація не вдалася")
            return result.returncode

        table_name = (result.stdout or "").strip().splitlines()
        synced = table_name[-1] if table_name else name
        console.print(f"[green]✓[/green] Синхронізовано локально: {synced}")
        return 0

    token = get_token()
    if not token:
        console.print("[dim]Токен не знайдено, запускаю локальну синхронізацію без авторизації...[/dim]")
        raise SystemExit(_local_sync())

    try:
        resp = httpx.post(
            f"{api}/api/v1/meta/doctypes/{name}/sync",
            headers=auth_headers(),
            timeout=10.0,
        )
        if resp.status_code == 404:
            console.print(f"[red]✗[/red] DocType '{name}' не знайдено")
            return
        if resp.status_code in (401, 403):
            console.print("[yellow]![/yellow] Немає доступу через API, запускаю локальну синхронізацію...")
            raise SystemExit(_local_sync())
        resp.raise_for_status()
        body = resp.json()
        result = body.get("data", body)
    except httpx.ConnectError:
        console.print("[yellow]![/yellow] Сервер недоступний, запускаю локальну синхронізацію...")
        raise SystemExit(_local_sync())

    console.print(f"[green]✓[/green] Синхронізовано: {result.get('table_name', name)}")
    added = result.get("columns_added") or []
    if added:
        console.print(f"  Додано колонки: {', '.join(added)}")
    else:
        console.print("  [dim]Змін у схемі не було[/dim]")


@doctype.command("apply")
@click.argument("names", nargs=-1, metavar="[NAME...]")
@click.option("--app", default=None, help="Застосувати всі DocTypes з вказаного додатку")
@click.option("--all", "all_apps", is_flag=True, help="Застосувати всі DocTypes з усіх додатків")
@click.option("--site", default=None, help="Назва сайту")
def doctype_apply(names: tuple[str, ...], app: str | None, all_apps: bool, site: str | None) -> None:
    """Застосувати DocType JSON з диска прямо в БД — без HTTP і авторизації.

    Реєструє нові DocTypes і оновлює існуючі разом із синхронізацією схеми таблиці.
    Запускається через venv проекту — сервер не потрібен.

    \b
    Приклади:
      grunt doctype apply InfraObjectType MltMap
      grunt doctype apply --app int_map
      grunt doctype apply --all
    """
    import os  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    from grunt_cli.helpers import get_bench_dir, get_current_site, get_site_dir  # noqa: PLC0415

    bench_dir = get_bench_dir()
    if bench_dir:
        site_dir = (
            (bench_dir / "sites" / site) if site
            else get_current_site()
        )
        backend_dir = bench_dir / "apps" / "grunt" / "backend"
        venv_dir = bench_dir / ".venv"
        apps_root = bench_dir / "apps"
    else:
        site_dir = get_site_dir()
        backend_dir = Path.cwd() / "apps" / "grunt" / "backend"
        venv_dir = Path.cwd() / ".venv"
        apps_root = Path.cwd() / "apps"

    if not site_dir:
        console.print("[red]✗[/red] Сайт не знайдено")
        raise SystemExit(1)

    # Collect JSON files
    json_files: list[Path] = []

    if names:
        for name in names:
            matches = list(apps_root.glob(f"**/{name}/{name}.json"))
            if not matches:
                console.print(f"  [yellow]![/yellow] {name}: JSON не знайдено в {apps_root}")
            else:
                json_files.extend(matches)
    elif app:
        app_path = apps_root / app
        if not app_path.exists():
            console.print(f"[red]✗[/red] Додаток '{app}' не знайдено в {apps_root}")
            raise SystemExit(1)
        json_files.extend(sorted(app_path.glob("**/doctypes/*/*.json")))
    elif all_apps:
        json_files.extend(sorted(apps_root.glob("**/doctypes/*/*.json")))
    else:
        console.print("[red]✗[/red] Вкажи [cyan]NAME[/cyan], [cyan]--app APP[/cyan] або [cyan]--all[/cyan]")
        raise SystemExit(1)

    if not json_files:
        console.print("[yellow]Нічого застосовувати[/yellow]")
        return

    # Build inline Python script executed in the grunt venv
    json_paths_repr = repr([str(p) for p in json_files])
    script = f"""
import asyncio, json, sys
from pathlib import Path
from sqlalchemy import update as sa_update
from grunt.core.db.system_tables import GruntMetaDoctype
from grunt.core.metadata.compiler import sync_table
from grunt.core.metadata.doctype import DocType
from grunt.core.metadata.registry import doctype_registry
from grunt.core.site.manager import current_site, site_manager
from grunt.core.startup import load_core_doctypes

async def main():
    sites = site_manager.get_sites()
    target = sites[0] if sites else None
    if not target:
        print("ERROR: no sites found"); sys.exit(1)
    token = current_site.set(target)
    try:
        eng = site_manager.get_engine(target)
        maker = site_manager.get_session_maker(target)
        json_files = {json_paths_repr}
        registered = updated = errors = 0
        async with maker() as session:
            await doctype_registry.load_all(session)
            await load_core_doctypes(session, eng)
            for path in json_files:
                dt_name = Path(path).stem
                try:
                    dt_data = json.loads(Path(path).read_text(encoding="utf-8"))
                    dt_obj = DocType.model_validate(dt_data)
                    if dt_name in doctype_registry._doctypes:
                        await session.execute(
                            sa_update(GruntMetaDoctype)
                            .where(GruntMetaDoctype.name == dt_name)
                            .values(module=dt_obj.module, data=dt_obj.model_dump(mode="json"))
                        )
                        doctype_registry._doctypes[dt_name] = dt_obj
                        await sync_table(dt_obj, eng, session=session)
                        await session.flush()
                        print(f"  ~ {{dt_name}}: оновлено")
                        updated += 1
                    else:
                        await doctype_registry.register(dt_obj, session, eng)
                        await session.flush()
                        print(f"  + {{dt_name}}: зареєстровано")
                        registered += 1
                except Exception as e:
                    print(f"  ! {{dt_name}}: {{e}}", file=sys.stderr)
                    errors += 1
            await session.commit()
        parts = []
        if registered: parts.append(f"{{registered}} зареєстровано")
        if updated:    parts.append(f"{{updated}} оновлено")
        if errors:     parts.append(f"{{errors}} помилок")
        print("\\n" + ", ".join(parts) if parts else "\\nЗмін не було")
    finally:
        current_site.reset(token)

asyncio.run(main())
"""

    python_bin = venv_dir / "bin" / "python"
    env = {
        **os.environ,
        "DOTENV_PATH": str(site_dir / ".env"),
        "PYTHONPATH": str(backend_dir),
        "VIRTUAL_ENV": str(venv_dir),
        "PATH": str(venv_dir / "bin") + os.pathsep + os.environ.get("PATH", ""),
    }

    result = subprocess.run(
        [str(python_bin), "-c", script],
        env=env,
        cwd=str(bench_dir or Path.cwd()),
    )
    sys.exit(result.returncode)


@doctype.command("scaffold")
@click.argument("name")
@click.option("--app", default=None, help="Папка app куди розмістити DocType (за замовчуванням: шукати в apps/)")
@click.option("--force", is_flag=True, help="Перезаписати існуючі файли")
@click.option("--py-only", "py_only", is_flag=True, help="Перегенерувати тільки Python контролер")
def doctype_scaffold(name: str, app: str | None, force: bool, py_only: bool) -> None:
    """Створити новий DocType з шаблонами JSON, Python контролером і JS скриптом.

    \b
    Структура:
      apps/{app}/doctypes/{Name}/
        ├── {Name}.json      # метадані DocType
        ├── {Name}.py        # контролер
        ├── {Name}.js        # client script
        └── __init__.py

    \b
    Приклади:
      grunt doctype scaffold Invoice
      grunt doctype scaffold Invoice --app crm
      grunt doctype scaffold Invoice --force
    """
    # Validate name
    if not name or name[0].islower():
        console.print("[red]✗[/red] Ім'я DocType повинно починатися з великої літери")
        raise SystemExit(1)

    # --py-only: find existing dir and regenerate controller only
    if py_only:
        apps_root = Path("grunt_apps") if Path("grunt_apps").exists() else Path("apps")
        matches = list(apps_root.glob(f"**/{name}/{name}.json"))
        if not matches:
            console.print(f"[red]✗[/red] DocType '{name}' не знайдено в {apps_root}")
            raise SystemExit(1)
        if len(matches) > 1:
            console.print("Знайдено кілька:")
            for i, m in enumerate(matches, 1):
                console.print(f"  [cyan]{i}[/cyan]. {m.parent.relative_to(apps_root)}")
            choice = click.prompt("Номер", type=click.IntRange(1, len(matches)))
            dt_dir = matches[choice - 1].parent
        else:
            dt_dir = matches[0].parent
        json_file = dt_dir / f"{name}.json"
        fields: list[dict] = []
        try:
            fields = json.loads(json_file.read_text(encoding="utf-8")).get("fields", [])
        except Exception:
            pass
        py_file = dt_dir / f"{name}.py"
        py_file.write_text(_make_controller(name, fields), encoding="utf-8")
        console.print(f"[green]✓[/green] Контролер перегенеровано: [dim]{py_file}[/dim]")
        return

    # Find app directory
    if not app:
        # Auto-detect: look for apps/ or grunt_apps/
        for potential in [Path("grunt_apps"), Path("apps")]:
            if potential.is_dir():
                apps_dir = potential
                break
        else:
            console.print("[red]✗[/red] Папка apps/ або grunt_apps/ не знайдена")
            console.print("  Перейди у базову директорію проекту або вкажи [cyan]--app[/cyan]")
            raise SystemExit(1)
        # Choose app dir — prompt if multiple exist
        app_dirs = sorted(
            [d for d in apps_dir.iterdir() if d.is_dir() and not d.name.startswith(".")],
            key=lambda d: d.name,
        )
        if not app_dirs:
            console.print(f"[red]✗[/red] Немає додатків у {apps_dir}")
            raise SystemExit(1)
        if len(app_dirs) == 1:
            app_path = app_dirs[0]
        else:
            console.print("Оберіть додаток:")
            for i, d in enumerate(app_dirs, 1):
                console.print(f"  [cyan]{i}[/cyan]. {d.name}")
            choice = click.prompt("Номер", type=click.IntRange(1, len(app_dirs)))
            app_path = app_dirs[choice - 1]
        app_name = app_path.name
    else:
        apps_dir = Path("grunt_apps") if Path("grunt_apps").exists() else Path("apps")
        app_path = apps_dir / app
        app_name = app

    if not app_path.is_dir():
        console.print(f"[red]✗[/red] Додаток '{app_name}' не знайдено в {apps_dir}")
        raise SystemExit(1)

    # Find doctype container (could be doctypes or {module}/doctypes)
    doctype_base = None
    for potential in app_path.glob("*/doctypes"):
        doctype_base = potential.parent  # the module dir
        break
    if not doctype_base:
        doctype_base = app_path

    doctype_dir = doctype_base / "doctypes" / name
    if doctype_dir.exists() and not force:
        console.print(f"[red]✗[/red] Папка {doctype_dir} вже існує")
        console.print("  Використай [cyan]--force[/cyan] для перезаписання")
        raise SystemExit(1)

    doctype_dir.mkdir(parents=True, exist_ok=True)

    # Determine module name (for JSON metadata)
    # If structure is myapp/{module}/doctypes/{Name}, module is {module}
    # Otherwise it's the app name
    module_name = doctype_base.name if doctype_base != app_path else app_name

    # 1. JSON файл
    json_content = {
        "name": name,
        "label": name,
        "module": module_name,
        "doctype": "DocType",
        "is_system": False,
        "fields": [
            {"fieldname": "name", "label": "Назва", "fieldtype": "Data", "required": True}
        ],
    }
    json_file = doctype_dir / f"{name}.json"
    json_file.write_text(json.dumps(json_content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 2. Python контролер
    py_file = doctype_dir / f"{name}.py"
    py_file.write_text(_make_controller(name, json_content["fields"]), encoding="utf-8")

    # 3. JavaScript client script
    js_content = f'''/**
 * {name} Client Script
 *
 * Called in the UI when editing {name} documents.
 */

function on_load(frm) {{
    // Code that runs when form loads
    console.log('Loaded {name}', frm.doc)
}}

function on_change(frm, fieldname) {{
    // Code that runs when a field changes
    console.log('Changed field:', fieldname)
}}

function validate(frm) {{
    // Return false to prevent save
    if (true) {{
        return true
    }}
}}

function before_save(frm) {{
    // Called before saving
}}

function after_save(frm) {{
    // Called after saving
}}
'''
    js_file = doctype_dir / f"{name}.js"
    js_file.write_text(js_content, encoding="utf-8")

    # 4. __init__.py
    init_file = doctype_dir / "__init__.py"
    init_file.write_text("", encoding="utf-8")

    # Show summary
    try:
        rel_path = doctype_dir.relative_to(Path.cwd())
    except ValueError:
        rel_path = doctype_dir

    console.print(f"[green]✓[/green] Створено DocType [bold]{name}[/bold]")
    console.print(f"  Місце: [dim]{rel_path}[/dim]")
    console.print("  Файли:")
    console.print(f"    ├── [cyan]{name}.json[/cyan]     (метадані)")
    console.print(f"    ├── [cyan]{name}.py[/cyan]       (контролер)")
    console.print(f"    ├── [cyan]{name}.js[/cyan]       (client script)")
    console.print("    └── [cyan]__init__.py[/cyan]")
    console.print()
    console.print("Наступні кроки:")
    console.print(f"1. Відредагуй [cyan]{name}.json[/cyan] додай нові поля")
    console.print("2. Запусти: [cyan]grunt serve --reload[/cyan]")
    console.print(f"3. Перейди на http://localhost:5173/desk/list/{name}")

