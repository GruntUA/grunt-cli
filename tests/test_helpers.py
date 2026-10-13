"""Тести для grunt_cli.helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from grunt_cli.helpers import (
    auth_headers,
    get_bench_dir,
    get_site_dir,
    get_token,
    resolve_site_api,
    save_token,
    token_file,
)

# ── resolve_site_api ────────────────────────────────────────────


class TestResolveSiteApi:
    def test_full_url_http(self):
        assert resolve_site_api("http://myhost:8080") == "http://myhost:8080"

    def test_full_url_https(self):
        assert resolve_site_api("https://example.com") == "https://example.com"

    def test_full_url_strips_trailing_slash(self):
        assert resolve_site_api("http://myhost:8080/") == "http://myhost:8080"

    def test_localhost_default_port(self):
        assert resolve_site_api("localhost") == "http://localhost:8000"

    def test_localhost_custom_port(self):
        assert resolve_site_api("localhost:9000") == "http://localhost:9000"

    def test_127_0_0_1_default_port(self):
        assert resolve_site_api("127.0.0.1") == "http://localhost:8000"

    def test_127_0_0_1_custom_port(self):
        assert resolve_site_api("127.0.0.1:3000") == "http://localhost:3000"

    def test_remote_host(self):
        assert resolve_site_api("dev.itmlt.win") == "https://dev.itmlt.win"

    def test_remote_host_strips_trailing_slash(self):
        assert resolve_site_api("dev.itmlt.win/") == "https://dev.itmlt.win"


# ── token management ────────────────────────────────────────────


class TestTokenManagement:
    def test_token_file_path(self):
        tf = token_file()
        assert tf == Path.home() / ".grunt_token"

    def test_save_and_get_token(self, tmp_path):
        fake_token_file = tmp_path / ".grunt_token"
        with patch("grunt_cli.helpers.token_file", return_value=fake_token_file):
            save_token("test-token-123")
            assert fake_token_file.read_text() == "test-token-123"
            assert get_token() == "test-token-123"

    def test_get_token_missing(self, tmp_path):
        fake_token_file = tmp_path / ".grunt_token"
        with patch("grunt_cli.helpers.token_file", return_value=fake_token_file):
            assert get_token() is None

    def test_get_token_strips_whitespace(self, tmp_path):
        fake_token_file = tmp_path / ".grunt_token"
        fake_token_file.write_text("  my-token  \n")
        with patch("grunt_cli.helpers.token_file", return_value=fake_token_file):
            assert get_token() == "my-token"

    def test_auth_headers_returns_bearer(self, tmp_path):
        fake_token_file = tmp_path / ".grunt_token"
        fake_token_file.write_text("abc123")
        with patch("grunt_cli.helpers.token_file", return_value=fake_token_file):
            headers = auth_headers()
            assert headers == {"Authorization": "Bearer abc123"}

    def test_auth_headers_no_token_exits(self, tmp_path):
        fake_token_file = tmp_path / ".grunt_token"
        with (
            patch("grunt_cli.helpers.token_file", return_value=fake_token_file),
            pytest.raises(SystemExit),
        ):
            auth_headers()


# ── get_site_dir ────────────────────────────────────────────────


class TestGetSiteDir:
    def test_finds_grunt_site_in_cwd(self, tmp_path):
        (tmp_path / "grunt.site").write_text("{}")
        with patch("grunt_cli.helpers.Path.cwd", return_value=tmp_path):
            assert get_site_dir() == tmp_path

    def test_finds_grunt_site_in_parent(self, tmp_path):
        (tmp_path / "grunt.site").write_text("{}")
        child = tmp_path / "subdir"
        child.mkdir()
        with patch("grunt_cli.helpers.Path.cwd", return_value=child):
            assert get_site_dir() == tmp_path

    def test_bench_root_uses_current_site(self, tmp_path):
        # get_site_dir шукає лише вгору; з кореня bench активний сайт — з currentsite.txt.
        from grunt_cli.helpers import get_current_site

        (tmp_path / "apps").mkdir()
        site = tmp_path / "sites" / "my-site"
        site.mkdir(parents=True)
        (site / "grunt.site").write_text("{}")
        (tmp_path / "sites" / "currentsite.txt").write_text("my-site")
        with patch("grunt_cli.helpers.Path.cwd", return_value=tmp_path):
            assert get_site_dir() is None
            assert get_current_site() == site

    def test_returns_none_when_not_found(self, tmp_path):
        with patch("grunt_cli.helpers.Path.cwd", return_value=tmp_path):
            assert get_site_dir() is None


# ── get_bench_dir ───────────────────────────────────────────────


class TestGetBenchDir:
    def test_finds_bench_with_apps_and_sites(self, tmp_path):
        (tmp_path / "apps").mkdir()
        (tmp_path / "sites").mkdir()
        with patch("grunt_cli.helpers.Path.cwd", return_value=tmp_path):
            assert get_bench_dir() == tmp_path

    def test_finds_bench_from_subdir(self, tmp_path):
        (tmp_path / "apps").mkdir()
        (tmp_path / "sites").mkdir()
        child = tmp_path / "apps" / "grunt"
        child.mkdir(parents=True)
        with patch("grunt_cli.helpers.Path.cwd", return_value=child):
            assert get_bench_dir() == tmp_path

    def test_returns_none_when_no_bench(self, tmp_path):
        with patch("grunt_cli.helpers.Path.cwd", return_value=tmp_path):
            assert get_bench_dir() is None


def test_mise_tasks_run_in_their_directory(tmp_path, monkeypatch):
    """MISE_CONFIG_FILE змушує mise 2026.10+ запускати задачі в $HOME — не ставимо його."""
    from unittest.mock import MagicMock, patch

    from grunt_cli import helpers

    monkeypatch.setenv("MISE_CONFIG_FILE", "/elsewhere/mise.toml")
    monkeypatch.setattr(helpers, "get_mise_bin", lambda: "/bin/mise")
    with (
        patch.object(helpers.subprocess, "run", return_value=MagicMock(returncode=0)) as run,
        patch.object(helpers.subprocess, "Popen") as popen,
    ):
        helpers.run_mise(tmp_path, "build", config_file=tmp_path / "mise.toml")
        helpers.run_mise_popen(tmp_path, "frontend", config_file=tmp_path / "mise.toml")

    [build] = [c for c in run.call_args_list if "build" in c.args[0]]
    for call in (build, popen.call_args):
        assert call.kwargs["cwd"] == str(tmp_path)
        assert "MISE_CONFIG_FILE" not in call.kwargs["env"]
