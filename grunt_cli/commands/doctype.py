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
        console.print(f"[red]✗[/red] Сервер недоступний. Запусти [cyan]grunt serve[/cyan]")
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
        console.print(f"[red]✗[/red] Сервер недоступний. Запусти [cyan]grunt serve[/cyan]")
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
            console.print(f"[red]✗[/red] Сервер недоступний. Запусти [cyan]grunt serve[/cyan]")
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
        body = resp.json()
        result = body.get("data", body)
    except httpx.ConnectError:
        console.print("[red]✗[/red] Сервер недоступний. Запусти [cyan]grunt serve[/cyan]")
        return

    console.print(f"[green]✓[/green] Синхронізовано: {result.get('table_name', name)}")
    added = result.get("columns_added") or []
    if added:
        console.print(f"  Додано колонки: {', '.join(added)}")
    else:
        console.print("  [dim]Змін у схемі не було[/dim]")
