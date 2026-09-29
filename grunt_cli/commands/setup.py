"""grunt setup production — systemd + nginx для продакшн-сервера за Cloudflare."""

from __future__ import annotations

import getpass
import json
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path

import click
import httpx
from jinja2 import Environment, PackageLoader

from grunt_cli.helpers import console, get_bench_dir, get_current_site, run_mise

# https://www.cloudflare.com/ips/ — з цих адрес nginx довіряє CF-Connecting-IP.
CLOUDFLARE_RANGES = (
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
)

_PLACEHOLDER_SECRETS = {"", "change-me", "change-me-to-a-random-64-char-string"}

_templates = Environment(
    loader=PackageLoader("grunt_cli", "templates/production"),
    keep_trailing_newline=True,
)


@click.group()
def setup() -> None:
    """Налаштування сервера."""


@setup.command("production")
@click.option("--site", default=None, help="Сайт (за замовчуванням — активний)")
@click.option("--port", default=8000, show_default=True, help="Порт uvicorn (лише 127.0.0.1)")
def production(site: str | None, port: int) -> None:
    """Продакшн: prod-значення в .env, збірка фронту, systemd-сервіси й nginx.

    \b
    Сервіси: <bench>-web (uvicorn, один процес) і <bench>-worker (taskiq).
    nginx приймає трафік від Cloudflare і бере справжній IP відвідувача
    з CF-Connecting-IP лише для адрес Cloudflare.
    Спершу все генерується в <bench>/config/production/, і лише потім
    (після підтвердження) встановлюється через sudo.
    """
    bench = get_bench_dir()
    if bench is None:
        console.print("[red]✗[/red] Bench не знайдено. Запустіть у папці проєкту.")
        raise SystemExit(1)
    site_dir = bench / "sites" / site if site else get_current_site()
    if site_dir is None or not (site_dir / "grunt.site").exists():
        console.print("[red]✗[/red] Сайт не знайдено. Вкажіть [cyan]--site <домен>[/cyan].")
        raise SystemExit(1)

    grunt_dir = bench / "apps" / "grunt"
    env_file = site_dir / ".env"
    name = bench.name
    console.print(f"[bold]⚙ Продакшн для сайту [cyan]{site_dir.name}[/cyan][/bold]\n")

    # ── Питання ─────────────────────────────────────────────────────
    domain = click.prompt("Основний домен", default=site_dir.name)
    extra = click.prompt(
        "Додаткові домени через пробіл (напр. www), Enter — немає",
        default=f"www.{domain}" if not domain.startswith("www.") else "",
        show_default=True,
    ).split()
    ssl_cert = ssl_key = ""
    console.print(
        "[dim]Cloudflare → сервер: для режиму SSL «Full (strict)» потрібен Origin Certificate\n"
        "(Cloudflare → SSL/TLS → Origin Server → Create Certificate), збережений на сервері.[/dim]"
    )
    ssl_cert = click.prompt(
        "Шлях до сертифіката (.pem), Enter — лише HTTP на порту 80", default="", show_default=False
    ).strip()
    if ssl_cert:
        ssl_key = click.prompt("Шлях до приватного ключа (.key)").strip()
        for path in (ssl_cert, ssl_key):
            if not Path(path).exists():
                console.print(f"[red]✗[/red] Файл не знайдено: {path}")
                raise SystemExit(1)

    # ── 1. .env сайту ───────────────────────────────────────────────
    console.print("\n[bold cyan]1. Налаштування сайту (.env)[/bold cyan]")
    env = _read_env(env_file)
    updates = {
        "DEBUG": "false",
        "APP_URL": f"https://{domain}",
        "ALLOWED_ORIGINS": json.dumps([f"https://{d}" for d in [domain, *extra]]),
    }
    if env.get("SECRET_KEY", "") in _PLACEHOLDER_SECRETS:
        updates["SECRET_KEY"] = secrets.token_hex(32)
    if not env.get("REDIS_URL"):
        updates["REDIS_URL"] = "redis://127.0.0.1:6379/0"
    _write_env(env_file, updates)
    for key, value in updates.items():
        shown = "***" if key == "SECRET_KEY" else value
        console.print(f"  [green]✓[/green] {key}={shown}")

    # ── 2. Фронт ────────────────────────────────────────────────────
    console.print("\n[bold cyan]2. Збірка фронту (npm run build)[/bold cyan]")
    if not run_mise(grunt_dir, "build"):
        console.print("[red]✗[/red] Збірка фронту не вдалася")
        raise SystemExit(1)

    # ── 3. Конфіги ──────────────────────────────────────────────────
    console.print("\n[bold cyan]3. Конфігурація[/bold cyan]")
    config_dir = bench / "config" / "production"
    config_dir.mkdir(parents=True, exist_ok=True)
    context = {
        "name": name,
        "key": re.sub(r"\W", "_", name),
        "site": site_dir.name,
        "server_names": " ".join([domain, *extra]),
        "port": port,
        "user": getpass.getuser(),
        "grunt_dir": grunt_dir,
        "env_file": env_file,
        "ssl_cert": ssl_cert,
        "ssl_key": ssl_key,
        "max_body_mb": int(env.get("MAX_UPLOAD_SIZE_MB") or 50) + 10,
        "cloudflare_ranges": CLOUDFLARE_RANGES,
    }
    files = {
        f"{name}.nginx.conf": "nginx.conf.j2",
        f"{name}-web.service": "web.service.j2",
        f"{name}-worker.service": "worker.service.j2",
    }
    for filename, template in files.items():
        (config_dir / filename).write_text(_templates.get_template(template).render(context))
        console.print(f"  [green]✓[/green] {config_dir / filename}")

    # ── 4. Встановлення ─────────────────────────────────────────────
    console.print("\n[bold cyan]4. Встановлення (sudo)[/bold cyan]")
    units = [f"{name}-web.service", f"{name}-worker.service"]
    console.print(
        f"  Буде: сервіси {', '.join(units)} у /etc/systemd/system,\n"
        f"  сайт nginx /etc/nginx/sites-enabled/{name}.conf, перезапуск сервісів і nginx."
    )
    if not click.confirm("  Встановити зараз?", default=True):
        console.print(f"  [dim]Пропущено. Файли — у {config_dir}[/dim]")
        return
    # nginx лежить у /usr/sbin — його немає в PATH звичайного користувача.
    if shutil.which("nginx", path="/usr/sbin:/usr/local/sbin:/sbin") is None:
        if not click.confirm("  nginx не встановлено. Встановити (apt)?", default=True):
            raise SystemExit(1)
        if subprocess.run(["sudo", "apt-get", "install", "-y", "nginx"]).returncode != 0:
            console.print("[red]✗[/red] Не вдалося встановити nginx")
            raise SystemExit(1)

    nginx_conf = f"/etc/nginx/sites-available/{name}.conf"
    steps = [
        *(
            ["sudo", "install", "-m", "644", str(config_dir / u), f"/etc/systemd/system/{u}"]
            for u in units
        ),
        ["sudo", "install", "-m", "644", str(config_dir / f"{name}.nginx.conf"), nginx_conf],
        ["sudo", "ln", "-sf", nginx_conf, f"/etc/nginx/sites-enabled/{name}.conf"],
        ["sudo", "nginx", "-t"],
        ["sudo", "systemctl", "daemon-reload"],
        ["sudo", "systemctl", "enable", *units],
        ["sudo", "systemctl", "restart", *units],
        ["sudo", "systemctl", "reload", "nginx"],
    ]
    for cmd in steps:
        if subprocess.run(cmd).returncode != 0:
            console.print(f"[red]✗[/red] Не вдалося: {' '.join(cmd)}")
            raise SystemExit(1)
    console.print("  [green]✓[/green] Встановлено")

    # ── 5. Перевірка ────────────────────────────────────────────────
    console.print("\n[bold cyan]5. Перевірка[/bold cyan]")
    if _wait_for_site(port, domain):
        console.print(f"  [green]✓[/green] Сайт відповідає на 127.0.0.1:{port} (Host: {domain})")
    else:
        console.print(
            "  [red]✗[/red] Сайт не відповідає. Журнал: "
            f"[cyan]journalctl -u {units[0]} -n 50[/cyan]"
        )
        raise SystemExit(1)

    console.print("\n[bold green]✅ Готово[/bold green]")
    console.print(
        "Cloudflare: DNS-запис A/AAAA на IP сервера з увімкненим проксі (помаранчева хмара),\n"
        "SSL/TLS → "
        + (
            "[bold]Full (strict)[/bold]."
            if ssl_cert
            else "[bold]Flexible[/bold] (без сертифіката)."
        )
    )
    console.print(f"Журнали: [cyan]journalctl -u {name}-web -u {name}-worker -f[/cyan]")


def _read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def _write_env(path: Path, updates: dict[str, str]) -> None:
    """Оновлює/додає ключі в .env, решту рядків (і коментарі) лишає як є."""
    lines = path.read_text().splitlines() if path.exists() else []
    pending = dict(updates)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in pending:
            lines[i] = f"{key}={pending.pop(key)}"
    lines += [f"{key}={value}" for key, value in pending.items()]
    path.write_text("\n".join(lines) + "\n")


def _wait_for_site(port: int, domain: str, timeout: float = 60) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"http://127.0.0.1:{port}/login", headers={"Host": domain})
            if response.status_code < 500:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return False
