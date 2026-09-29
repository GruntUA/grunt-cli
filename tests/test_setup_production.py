"""grunt setup production — .env, конфіги systemd/nginx (без sudo-кроку)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from grunt_cli.main import cli


@pytest.fixture
def bench(tmp_path, monkeypatch):
    root = tmp_path / "mlt_prod"
    site = root / "sites" / "mlt.gov.ua"
    (root / "apps" / "grunt").mkdir(parents=True)
    site.mkdir(parents=True)
    (site / "grunt.site").write_text(json.dumps({"installed_apps": ["grunt"]}))
    (root / "sites" / "currentsite.txt").write_text("mlt.gov.ua")
    (site / ".env").write_text(
        "# коментар\nDEBUG=true\nSECRET_KEY=change-me\nMAX_UPLOAD_SIZE_MB=20\n"
    )
    monkeypatch.chdir(root)
    return root


def _run(answers: str):
    with patch("grunt_cli.commands.setup.run_mise", return_value=True):
        return CliRunner().invoke(cli, ["setup", "production"], input=answers)


def test_writes_env_and_configs_without_installing(bench):
    result = _run("\n\n\nn\n")  # домен, www, без сертифіката, не встановлювати

    assert result.exit_code == 0, result.output
    env = (bench / "sites" / "mlt.gov.ua" / ".env").read_text()
    assert "# коментар" in env
    assert "DEBUG=false" in env
    assert "APP_URL=https://mlt.gov.ua" in env
    assert 'ALLOWED_ORIGINS=["https://mlt.gov.ua", "https://www.mlt.gov.ua"]' in env
    assert "SECRET_KEY=change-me" not in env
    assert "REDIS_URL=redis://127.0.0.1:6379/0" in env

    config = bench / "config" / "production"
    nginx = (config / "mlt_prod.nginx.conf").read_text()
    assert "server_name mlt.gov.ua www.mlt.gov.ua;" in nginx
    assert "listen 80;" in nginx and "ssl_certificate" not in nginx
    assert "client_max_body_size 30m;" in nginx
    assert "set_real_ip_from 173.245.48.0/20;" in nginx
    # proxy_set_header не успадковується в location зі своїми — мусить бути в кожному
    assert nginx.count("proxy_set_header CF-Connecting-IP  $remote_addr;") == 2

    web = (config / "mlt_prod-web.service").read_text()
    assert f"DOTENV_PATH={bench / 'sites' / 'mlt.gov.ua' / '.env'}" in web
    assert "--port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1" in web
    assert "--workers" not in web
    assert "taskiq worker" in (config / "mlt_prod-worker.service").read_text()


def test_origin_certificate_enables_https(bench, tmp_path):
    cert, key = tmp_path / "origin.pem", tmp_path / "origin.key"
    cert.write_text("x")
    key.write_text("x")

    result = _run(f"\n\n{cert}\n{key}\nn\n")

    assert result.exit_code == 0, result.output
    nginx = (bench / "config" / "production" / "mlt_prod.nginx.conf").read_text()
    assert "listen 443 ssl;" in nginx
    assert f"ssl_certificate     {cert};" in nginx
    assert "return 301 https://$host$request_uri;" in nginx


def test_keeps_real_secret_key(bench):
    env_file = bench / "sites" / "mlt.gov.ua" / ".env"
    env_file.write_text("SECRET_KEY=abc123realkey\n")

    assert _run("\n\n\nn\n").exit_code == 0
    assert "SECRET_KEY=abc123realkey" in env_file.read_text()
