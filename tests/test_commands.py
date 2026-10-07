"""Тести для CLI команд grunt_cli."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from grunt_cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


# ── grunt --version ─────────────────────────────────────────────


class TestCli:
    def test_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Ґрунт CLI" in result.output


# ── grunt install ───────────────────────────────────────────────


class TestInstall:
    def test_install_existing_dir_fails(self, runner, tmp_path):
        project = tmp_path / "my-project"
        project.mkdir()
        (project / "some-file").write_text("x")
        with runner.isolated_filesystem(temp_dir=tmp_path):
            import os

            os.chdir(tmp_path)
            result = runner.invoke(cli, ["install", str(project)])
            assert result.exit_code != 0

    @patch("grunt_cli.commands.install.install_npm_deps")
    @patch("grunt_cli.commands.install.ensure_venv")
    @patch("grunt_cli.commands.install.clone_grunt")
    def test_install_creates_structure(self, mock_clone, mock_venv, mock_npm, runner, tmp_path):
        mock_clone.return_value = tmp_path / "test-site" / "apps" / "grunt"
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            result = runner.invoke(cli, ["install", "test-site"])
            site_dir = Path(td) / "test-site"
            assert site_dir.exists()
            assert (site_dir / "apps").is_dir()
            assert (site_dir / "grunt.site").exists()
            assert (site_dir / ".env").exists()

            config = json.loads((site_dir / "grunt.site").read_text())
            assert "grunt" in config["installed_apps"]

    @patch("grunt_cli.commands.install.install_npm_deps")
    @patch("grunt_cli.commands.install.ensure_venv")
    @patch("grunt_cli.commands.install.clone_grunt")
    def test_install_git_clone_failure(self, mock_clone, mock_venv, mock_npm, runner, tmp_path):
        mock_clone.side_effect = SystemExit(1)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["install", "test-site"])
            assert result.exit_code != 0


# ── grunt serve ─────────────────────────────────────────────────


class TestServe:
    def test_serve_no_site_dir(self, runner):
        with (
            patch("grunt_cli.commands.serve.get_site_dir", return_value=None),
            patch("grunt_cli.commands.serve.get_bench_dir", return_value=None),
        ):
            result = runner.invoke(cli, ["serve"])
            assert result.exit_code != 0

    def test_serve_bench_no_grunt_framework(self, runner, tmp_path):
        bench = tmp_path / "bench"
        bench.mkdir()
        (bench / "apps").mkdir()
        (bench / "sites").mkdir()
        with (
            patch("grunt_cli.commands.serve.get_site_dir", return_value=None),
            patch("grunt_cli.commands.serve.get_bench_dir", return_value=bench),
        ):
            result = runner.invoke(cli, ["serve"])
            assert result.exit_code != 0

    def test_serve_flat_no_grunt_framework(self, runner, tmp_path):
        with (
            patch("grunt_cli.commands.serve.get_site_dir", return_value=tmp_path),
            patch("grunt_cli.commands.serve.get_bench_dir", return_value=None),
        ):
            result = runner.invoke(cli, ["serve"])
            assert result.exit_code != 0


# ── grunt init ──────────────────────────────────────────────────


class TestInit:
    def test_init_no_site(self, runner):
        """grunt init (без аргументу) — без bench і без site_dir — помилка."""
        with (
            patch("grunt_cli.commands.init.get_bench_dir", return_value=None),
            patch("grunt_cli.commands.init.get_site_dir", return_value=None),
        ):
            result = runner.invoke(cli, ["init"])
            assert result.exit_code != 0

    @patch("grunt_cli.commands.init.run_alembic", return_value=True)
    def test_init_generates_secret_key(self, mock_alembic, runner, tmp_path):
        """grunt init (без аргументу) — flat site, генерує SECRET_KEY."""
        (tmp_path / "grunt.site").write_text("{}")
        (tmp_path / ".env").write_text("DEBUG=true\nSECRET_KEY=change-me\n")
        grunt_dir = tmp_path / "apps" / "grunt" / "backend"
        grunt_dir.mkdir(parents=True)

        with (
            patch("grunt_cli.commands.init.get_bench_dir", return_value=None),
            patch("grunt_cli.commands.init.get_site_dir", return_value=tmp_path),
        ):
            result = runner.invoke(cli, ["init"], input="n\n")

        env_content = (tmp_path / ".env").read_text()
        assert "change-me" not in env_content
        assert "SECRET_KEY=" in env_content

    @patch("grunt_cli.commands.init.install_npm_deps")
    @patch("grunt_cli.commands.init.ensure_venv")
    @patch("grunt_cli.commands.init.clone_grunt")
    def test_init_bench_creates_structure(self, mock_clone, mock_venv, mock_npm, runner, tmp_path):
        """grunt init my-bench — створює bench-структуру."""
        mock_clone.return_value = tmp_path / "my-bench" / "apps" / "grunt"
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "my-bench"])
            assert result.exit_code == 0
            bench = Path("my-bench")
            assert (bench / "apps").is_dir()
            assert (bench / "sites").is_dir()


# ── grunt db ────────────────────────────────────────────────────


class TestDb:
    def test_db_migrate_no_site(self, runner):
        with patch("grunt_cli.commands.db.get_site_dir", return_value=None):
            result = runner.invoke(cli, ["db", "migrate"])
            assert result.exit_code != 0

    @patch("grunt_cli.commands.db.subprocess.run")
    def test_db_migrate_success(self, mock_run, runner, tmp_path):
        site_dir = tmp_path / "site"
        site_dir.mkdir()
        (site_dir / "grunt.site").write_text("{}")
        backend = site_dir / "apps" / "grunt" / "backend"
        backend.mkdir(parents=True)
        mock_run.return_value = MagicMock(returncode=0)

        with patch("grunt_cli.commands.db.get_site_dir", return_value=site_dir):
            result = runner.invoke(cli, ["db", "migrate"])
            assert result.exit_code == 0

    @patch("grunt_cli.commands.db.subprocess.run")
    def test_db_rollback(self, mock_run, runner, tmp_path):
        site_dir = tmp_path / "site"
        site_dir.mkdir()
        (site_dir / "grunt.site").write_text("{}")
        backend = site_dir / "apps" / "grunt" / "backend"
        backend.mkdir(parents=True)
        mock_run.return_value = MagicMock(returncode=0)

        with patch("grunt_cli.commands.db.get_site_dir", return_value=site_dir):
            result = runner.invoke(cli, ["db", "rollback", "2"])
            assert result.exit_code == 0
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert "-2" in cmd


# ── grunt migrate ───────────────────────────────────────────────


class TestMigrate:
    """`grunt migrate` runs alembic (core tables) then delegates DocType/fixture
    sync to `grunt migrate` in the project venv — no duplicate implementation."""

    def _make_bench(self, tmp_path: Path) -> Path:
        bench = tmp_path / "bench"
        app_dir = bench / "apps" / "grunt"
        venv_bin = app_dir / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        (app_dir / "alembic.ini").write_text("[alembic]\n")
        (venv_bin / "alembic").touch()
        (venv_bin / "grunt").touch()

        site_a = bench / "sites" / "a.local"
        site_a.mkdir(parents=True)
        (site_a / "grunt.site").write_text("{}")

        return bench

    @patch("grunt_cli.commands.migrate.subprocess.run")
    def test_migrate_without_site_delegates_to_venv_grunt(
        self, mock_run, runner, tmp_path, monkeypatch
    ):
        bench = self._make_bench(tmp_path)
        mock_run.return_value = MagicMock(returncode=0)

        monkeypatch.chdir(bench)
        result = runner.invoke(cli, ["migrate"])

        assert result.exit_code == 0
        assert mock_run.call_count == 2

        alembic_cmd = mock_run.call_args_list[0][0][0]
        assert alembic_cmd[0].endswith("/apps/grunt/.venv/bin/alembic")
        assert alembic_cmd[1:] == [
            "-c",
            str(bench / "apps" / "grunt" / "alembic.ini"),
            "upgrade",
            "head",
        ]

        delegated_cmd = mock_run.call_args_list[1][0][0]
        assert delegated_cmd[0].endswith("/apps/grunt/.venv/bin/grunt")
        assert delegated_cmd[1:] == ["migrate"]

    @patch("grunt_cli.commands.migrate.subprocess.run")
    def test_migrate_with_site_passes_through(self, mock_run, runner, tmp_path, monkeypatch):
        bench = self._make_bench(tmp_path)
        mock_run.return_value = MagicMock(returncode=0)

        monkeypatch.chdir(bench)
        result = runner.invoke(cli, ["migrate", "--site", "a.local", "--dry-run"])

        assert result.exit_code == 0
        delegated_cmd = mock_run.call_args_list[1][0][0]
        assert delegated_cmd[1:] == ["migrate", "--site", "a.local", "--dry-run"]

    @patch("grunt_cli.commands.migrate.subprocess.run")
    def test_migrate_alembic_failure_stops_before_delegating(
        self, mock_run, runner, tmp_path, monkeypatch
    ):
        bench = self._make_bench(tmp_path)
        mock_run.return_value = MagicMock(returncode=1)

        monkeypatch.chdir(bench)
        result = runner.invoke(cli, ["migrate"])

        assert result.exit_code == 1
        assert mock_run.call_count == 1  # never reaches the delegated call


# ── grunt auth ──────────────────────────────────────────────────


class TestAuth:
    @patch("grunt_cli.commands.auth.httpx.post")
    def test_login_success(self, mock_post, runner, tmp_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "tok123"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        fake_token = tmp_path / ".grunt_token"
        with patch("grunt_cli.helpers.token_file", return_value=fake_token):
            result = runner.invoke(
                cli,
                ["auth", "login"],
                input="admin@test.com\npassword123\n",
            )
            assert result.exit_code == 0
            assert "Авторизовано" in result.output
            assert fake_token.read_text() == "tok123"

    @patch("grunt_cli.commands.auth.httpx.post")
    def test_login_wrong_credentials(self, mock_post, runner):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_post.return_value = mock_resp

        result = runner.invoke(
            cli,
            ["auth", "login"],
            input="wrong@test.com\nwrongpass\n",
        )
        assert "Невірний" in result.output

    @patch("grunt_cli.commands.auth.httpx.post")
    def test_login_server_unavailable(self, mock_post, runner):
        import httpx

        mock_post.side_effect = httpx.ConnectError("Connection refused")

        result = runner.invoke(
            cli,
            ["auth", "login"],
            input="admin@test.com\npassword123\n",
        )
        assert "недоступний" in result.output

    def test_logout_with_token(self, runner, tmp_path):
        fake_token = tmp_path / ".grunt_token"
        fake_token.write_text("some-token")
        with patch("grunt_cli.commands.auth.token_file", return_value=fake_token):
            result = runner.invoke(cli, ["auth", "logout"])
            assert result.exit_code == 0
            assert not fake_token.exists()

    def test_logout_without_token(self, runner, tmp_path):
        fake_token = tmp_path / ".grunt_token"
        with patch("grunt_cli.commands.auth.token_file", return_value=fake_token):
            result = runner.invoke(cli, ["auth", "logout"])
            assert result.exit_code == 0
            assert "не знайдено" in result.output


# ── grunt app ───────────────────────────────────────────────────


class TestApp:
    def test_app_create(self, runner, tmp_path):
        with patch("grunt_cli.commands.app.get_apps_dir", return_value=tmp_path):
            result = runner.invoke(cli, ["app", "create", "my_app", "--title", "My App"])
            assert result.exit_code == 0
            app_dir = tmp_path / "my_app"
            assert app_dir.exists()
            assert (app_dir / "app.json").exists()
            assert (app_dir / "doctypes").is_dir()
            assert (app_dir / "fixtures").is_dir()

            meta = json.loads((app_dir / "app.json").read_text())
            assert meta["name"] == "my_app"
            assert meta["title"] == "My App"

    def test_app_create_already_exists(self, runner, tmp_path):
        (tmp_path / "my_app").mkdir()
        with patch("grunt_cli.commands.app.get_apps_dir", return_value=tmp_path):
            result = runner.invoke(cli, ["app", "create", "my_app"])
            assert result.exit_code != 0

    def test_app_install_local(self, runner, tmp_path):
        bench = tmp_path / "bench"
        (bench / "apps" / "my_app").mkdir(parents=True)
        (bench / "apps" / "my_app" / "app.json").write_text(
            json.dumps({"name": "my_app", "title": "My App", "version": "0.1.0", "modules": []})
        )
        site = bench / "sites" / "test-site"
        site.mkdir(parents=True)
        (site / "grunt.site").write_text(json.dumps({"installed_apps": ["grunt"]}))

        with (
            patch("grunt_cli.commands.app.get_apps_dir", return_value=bench / "apps"),
            patch("grunt_cli.commands.app.get_site_dir", return_value=None),
            patch("grunt_cli.helpers.get_bench_dir", return_value=bench),
        ):
            result = runner.invoke(cli, ["app", "install", "my_app", "--site", "test-site"])
            assert result.exit_code == 0

            config = json.loads((site / "grunt.site").read_text())
            assert "my_app" in config["installed_apps"]

    @patch("grunt_cli.helpers.subprocess.run")
    def test_app_get(self, mock_run, runner, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        with patch("grunt_cli.commands.app.get_apps_dir", return_value=tmp_path):
            result = runner.invoke(cli, ["app", "get", "https://github.com/test/repo.git"])
            assert result.exit_code == 0
            mock_run.assert_called_once()

    @patch("grunt_cli.helpers.subprocess.run")
    def test_app_get_failure(self, mock_run, runner, tmp_path):
        mock_run.return_value = MagicMock(returncode=1, stderr="fatal: something broke")
        with patch("grunt_cli.commands.app.get_apps_dir", return_value=tmp_path):
            result = runner.invoke(cli, ["app", "get", "https://github.com/test/repo.git"])
            assert result.exit_code != 0

    @patch("grunt_cli.helpers.ask_github_token")
    @patch("grunt_cli.helpers.subprocess.run")
    def test_app_get_private_repo_without_tty_does_not_ask_token(
        self, mock_run, mock_ask, runner, tmp_path
    ):
        mock_run.return_value = MagicMock(returncode=128, stderr="remote: Repository not found.")
        with patch("grunt_cli.commands.app.get_apps_dir", return_value=tmp_path):
            result = runner.invoke(cli, ["app", "get", "https://github.com/test/repo"])
        assert result.exit_code != 0
        assert "приватний" in result.output
        mock_ask.assert_not_called()
        mock_run.assert_called_once()

    @patch("grunt_cli.helpers.sys.stdin")
    @patch("grunt_cli.helpers.ask_github_token", return_value=True)
    @patch("grunt_cli.helpers.subprocess.run")
    def test_git_clone_retries_after_token(self, mock_run, mock_ask, mock_stdin, tmp_path):
        from grunt_cli.helpers import git_clone

        mock_stdin.isatty.return_value = True
        mock_run.side_effect = [
            MagicMock(returncode=128, stderr="fatal: could not read Username"),
            MagicMock(returncode=0, stderr=""),
        ]
        assert git_clone("https://github.com/owner/repo", tmp_path) is True
        mock_ask.assert_called_once_with("owner/repo")
        assert mock_run.call_count == 2

    def test_github_repo_path(self):
        from grunt_cli.helpers import github_repo_path

        assert github_repo_path("https://github.com/owner/repo.git") == "owner/repo.git"
        assert github_repo_path("https://github.com/owner/repo/") == "owner/repo"
        assert github_repo_path("git@github.com:owner/repo.git") is None
        assert github_repo_path("https://gitlab.com/owner/repo") is None


# ── grunt doctype ───────────────────────────────────────────────


class TestDoctype:
    @patch("grunt_cli.commands.doctype.httpx.get")
    @patch("grunt_cli.commands.doctype.auth_headers")
    def test_doctype_list(self, mock_auth, mock_get, runner):
        mock_auth.return_value = {"Authorization": "Bearer tok"}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {
                    "name": "User",
                    "label": "Користувач",
                    "module": "Core",
                    "fields": [{"fieldname": "email"}],
                    "is_child": False,
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = runner.invoke(cli, ["doctype", "list"])
        assert result.exit_code == 0
        assert "User" in result.output

    @patch("grunt_cli.commands.doctype.httpx.get")
    @patch("grunt_cli.commands.doctype.auth_headers")
    def test_doctype_show_not_found(self, mock_auth, mock_get, runner):
        mock_auth.return_value = {"Authorization": "Bearer tok"}
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        result = runner.invoke(cli, ["doctype", "show", "NonExistent"])
        assert "не знайдено" in result.output

    @patch("grunt_cli.commands.doctype.httpx.get")
    @patch("grunt_cli.commands.doctype.auth_headers")
    def test_doctype_list_server_unavailable(self, mock_auth, mock_get, runner):
        import httpx

        mock_auth.return_value = {"Authorization": "Bearer tok"}
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        result = runner.invoke(cli, ["doctype", "list"])
        assert "підключитись" in result.output


# ── grunt sites ──────────────────────────────────────────────────


class TestSites:
    def test_sites_list_no_bench_no_site(self, runner):
        with (
            patch("grunt_cli.commands.sites.get_bench_dir", return_value=None),
            patch("grunt_cli.commands.sites.get_site_dir", return_value=None),
        ):
            result = runner.invoke(cli, ["sites", "list"])
            assert result.exit_code == 0
            assert "не знайдено" in result.output

    def test_sites_list_with_sites(self, runner, tmp_path):
        bench = tmp_path / "bench"
        (bench / "apps").mkdir(parents=True)
        sites_dir = bench / "sites"
        site = sites_dir / "my-site"
        site.mkdir(parents=True)
        (site / "grunt.site").write_text(json.dumps({"installed_apps": ["grunt"]}))

        with patch("grunt_cli.commands.sites.get_bench_dir", return_value=bench):
            result = runner.invoke(cli, ["sites", "list"])
            assert result.exit_code == 0
            assert "my-site" in result.output

    def test_sites_list_empty(self, runner, tmp_path):
        bench = tmp_path / "bench"
        (bench / "apps").mkdir(parents=True)
        (bench / "sites").mkdir(parents=True)

        with patch("grunt_cli.commands.sites.get_bench_dir", return_value=bench):
            result = runner.invoke(cli, ["sites", "list"])
            assert result.exit_code == 0
            assert "не знайдено" in result.output

    @patch("grunt_cli.commands.sites.run_alembic", return_value=True)
    def test_sites_new(self, mock_alembic, runner, tmp_path):
        bench = tmp_path / "bench"
        (bench / "apps" / "grunt").mkdir(parents=True)
        (bench / "sites").mkdir(parents=True)

        with patch("grunt_cli.commands.sites.get_bench_dir", return_value=bench):
            result = runner.invoke(cli, ["sites", "new", "test-site"])
            assert result.exit_code == 0
            site_dir = bench / "sites" / "test-site"
            assert (site_dir / "grunt.site").exists()
            assert (site_dir / ".env").exists()
            assert (bench / "sites" / "currentsite.txt").read_text() == "test-site"

    def test_sites_new_already_exists(self, runner, tmp_path):
        bench = tmp_path / "bench"
        (bench / "apps").mkdir(parents=True)
        site = bench / "sites" / "existing"
        site.mkdir(parents=True)

        with patch("grunt_cli.commands.sites.get_bench_dir", return_value=bench):
            result = runner.invoke(cli, ["sites", "new", "existing"])
            assert result.exit_code != 0

    def test_sites_use(self, runner, tmp_path):
        bench = tmp_path / "bench"
        (bench / "apps").mkdir(parents=True)
        site = bench / "sites" / "my-site"
        site.mkdir(parents=True)
        (site / "grunt.site").write_text("{}")

        with patch("grunt_cli.commands.sites.get_bench_dir", return_value=bench):
            result = runner.invoke(cli, ["sites", "use", "my-site"])
            assert result.exit_code == 0
            assert (bench / "sites" / "currentsite.txt").read_text() == "my-site"

    def test_sites_drop(self, runner, tmp_path):
        bench = tmp_path / "bench"
        (bench / "apps").mkdir(parents=True)
        site = bench / "sites" / "doomed"
        site.mkdir(parents=True)
        (site / "grunt.site").write_text("{}")

        with patch("grunt_cli.commands.sites.get_bench_dir", return_value=bench):
            result = runner.invoke(cli, ["sites", "drop", "doomed", "--force"])
            assert result.exit_code == 0
            assert not site.exists()


# ── grunt update ────────────────────────────────────────────────


class TestUpdate:
    @patch("grunt_cli.commands.update._get_cli_dir", return_value=None)
    @patch("grunt_cli.commands.update._find_apps_dir", return_value=None)
    def test_update_nothing_found(self, mock_apps, mock_cli, runner):
        result = runner.invoke(cli, ["update"])
        assert result.exit_code == 0
        assert "Нічого не оновлено" in result.output

    @patch("grunt_cli.commands.update.subprocess.run")
    @patch("grunt_cli.commands.update._get_cli_dir")
    @patch("grunt_cli.commands.update._find_apps_dir", return_value=None)
    def test_update_cli_only(self, mock_apps, mock_cli_dir, mock_run, runner, tmp_path):
        cli_dir = tmp_path / "grunt-cli"
        cli_dir.mkdir()
        (cli_dir / ".git").mkdir()
        (cli_dir / "pyproject.toml").write_text("[project]")
        mock_cli_dir.return_value = cli_dir

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="abc1234",
            stderr="",
        )

        result = runner.invoke(cli, ["update", "--cli", "--no-deps"])
        assert result.exit_code == 0

    @patch("grunt_cli.commands.update._run_migrations")
    @patch("grunt_cli.commands.update._run_npm_install")
    @patch("grunt_cli.commands.update._update_python_packages")
    @patch("grunt_cli.commands.update.run_mise", return_value=True)
    @patch("grunt_cli.commands.update.subprocess.run")
    @patch("grunt_cli.commands.update._get_cli_dir")
    def test_update_cli_argument_reinstalls_cli_only(
        self,
        mock_cli_dir,
        mock_run,
        mock_mise,
        mock_packages,
        mock_npm,
        mock_migrate,
        runner,
        tmp_path,
    ):
        cli_dir = tmp_path / "grunt-cli"
        (cli_dir / ".git").mkdir(parents=True)
        mock_cli_dir.return_value = cli_dir
        mock_run.return_value = MagicMock(returncode=0, stdout="abc1234", stderr="")

        result = runner.invoke(cli, ["update", "cli"])

        assert result.exit_code == 0, result.output
        assert "grunt-cli оновлено" in result.output
        mock_mise.assert_any_call(cli_dir, "run", "install")
        mock_packages.assert_not_called()
        mock_npm.assert_not_called()
        mock_migrate.assert_not_called()


class TestUpdateRestart:
    """Після міграції: на проді — збірка фронтенду й перезапуск сервісів."""

    @staticmethod
    def _bench(tmp_path, monkeypatch, units: tuple[str, ...]):
        bench = tmp_path / "mlt_prod"
        (bench / "apps" / "grunt").mkdir(parents=True)
        (bench / "sites").mkdir()
        systemd = tmp_path / "systemd"
        systemd.mkdir()
        for unit in units:
            (systemd / unit).write_text("")
        monkeypatch.setattr("grunt_cli.commands.restart.SYSTEMD_DIR", systemd)
        monkeypatch.chdir(bench)
        return bench

    @staticmethod
    def _run(runner, *args):
        with (
            patch("grunt_cli.commands.update._update_python_packages"),
            patch("grunt_cli.commands.update._run_npm_install"),
            patch("grunt_cli.commands.update._update_runtimes"),
            patch("grunt_cli.commands.update._get_cli_dir", return_value=None),
            patch("grunt_cli.commands.update._git_pull", return_value=True),
        ):
            return runner.invoke(cli, ["update", "--framework", "--no-deps", *args])

    @patch("grunt_cli.commands.update.restart_units", return_value=True)
    @patch("grunt_cli.commands.update.run_mise", return_value=True)
    @patch("grunt_cli.commands.update._run_migrations", return_value=True)
    def test_production_builds_and_restarts(
        self, _migrate, mock_mise, mock_restart, runner, tmp_path, monkeypatch
    ):
        bench = self._bench(
            tmp_path, monkeypatch, ("mlt_prod-web.service", "mlt_prod-worker.service")
        )
        result = self._run(runner)
        assert result.exit_code == 0, result.output
        mock_mise.assert_any_call(bench / "apps" / "grunt", "build")
        mock_restart.assert_called_once_with(["mlt_prod-web.service", "mlt_prod-worker.service"])

    @patch("grunt_cli.commands.update.restart_units")
    @patch("grunt_cli.commands.update.run_mise", return_value=True)
    @patch("grunt_cli.commands.update._run_migrations", return_value=False)
    def test_failed_migration_skips_restart(
        self, _migrate, _mise, mock_restart, runner, tmp_path, monkeypatch
    ):
        self._bench(tmp_path, monkeypatch, ("mlt_prod-web.service",))
        result = self._run(runner)
        assert result.exit_code != 0
        assert "НЕ перезапущено" in result.output
        mock_restart.assert_not_called()

    @patch("grunt_cli.commands.update.restart_units")
    @patch("grunt_cli.commands.update._run_migrations", return_value=True)
    def test_development_does_not_restart(
        self, _migrate, mock_restart, runner, tmp_path, monkeypatch
    ):
        self._bench(tmp_path, monkeypatch, ())
        result = self._run(runner)
        assert result.exit_code == 0, result.output
        assert "grunt serve" in result.output
        mock_restart.assert_not_called()

    @patch("grunt_cli.commands.update.restart_units")
    @patch("grunt_cli.commands.update._run_migrations", return_value=True)
    def test_no_restart_flag(self, _migrate, mock_restart, runner, tmp_path, monkeypatch):
        self._bench(tmp_path, monkeypatch, ("mlt_prod-web.service",))
        result = self._run(runner, "--no-restart")
        assert result.exit_code == 0, result.output
        mock_restart.assert_not_called()

    @patch("grunt_cli.commands.update.venv_delegate", return_value=0)
    def test_migrations_run_full_framework_migrate(self, mock_delegate, tmp_path, monkeypatch):
        from grunt_cli.commands.update import _run_migrations

        site = tmp_path / "site"
        site.mkdir()
        monkeypatch.setattr("grunt_cli.commands.update.get_current_site", lambda: site)
        assert _run_migrations(None) is True
        mock_delegate.assert_called_once_with("migrate", site=None)


# ── grunt master ───────────────────────────────────────────────


class TestMaster:
    @patch("grunt_cli.commands.master.install_npm_deps", return_value=True)
    @patch("grunt_cli.commands.master.ensure_venv")
    @patch("grunt_cli.commands.master.clone_grunt")
    @patch("grunt_cli.commands.master.run_alembic", return_value=True)
    def test_master_creates_bench_sqlite(
        self,
        mock_alembic,
        mock_clone,
        mock_venv,
        mock_npm,
        runner,
        tmp_path,
    ):
        mock_clone.return_value = tmp_path / "my-bench" / "apps" / "grunt"

        with runner.isolated_filesystem(temp_dir=tmp_path):
            # input: project, site, db_choice=1(sqlite), db_file, port, no admin, no serve
            result = runner.invoke(
                cli,
                ["master"],
                input="my-bench\ndev.local\n1\ngrunt.db\n8000\nn\nn\n",
            )
            assert result.exit_code == 0
            bench = Path("my-bench")
            assert (bench / "apps").is_dir()
            assert (bench / "sites").is_dir()
            assert (bench / "sites" / "dev.local" / "grunt.site").exists()
            assert (bench / "sites" / "dev.local" / ".env").exists()
            assert (bench / "sites" / "currentsite.txt").read_text() == "dev.local"
            env = (bench / "sites" / "dev.local" / ".env").read_text()
            assert "sqlite+aiosqlite:///./grunt.db" in env
            assert "SECRET_KEY=" in env

    @patch("grunt_cli.commands.master.install_npm_deps", return_value=True)
    @patch("grunt_cli.commands.master.ensure_venv")
    @patch("grunt_cli.commands.master.clone_grunt")
    @patch("grunt_cli.commands.master.run_alembic", return_value=True)
    def test_master_creates_bench_postgres(
        self,
        mock_alembic,
        mock_clone,
        mock_venv,
        mock_npm,
        runner,
        tmp_path,
    ):
        mock_clone.return_value = tmp_path / "proj" / "apps" / "grunt"

        with runner.isolated_filesystem(temp_dir=tmp_path):
            # input: project, site, db_choice=2(postgres), host, port, user, password, db_name, port, no admin, no serve
            result = runner.invoke(
                cli,
                ["master"],
                input="proj\nprod.example.com\n2\nlocalhost\n5432\npostgres\nsecret\nmydb\n9000\nn\nn\n",
            )
            assert result.exit_code == 0
            env = (Path("proj") / "sites" / "prod.example.com" / ".env").read_text()
            assert "postgresql+asyncpg://postgres:secret@localhost:5432/mydb" in env

    @patch("grunt_cli.commands.master.install_npm_deps", return_value=True)
    @patch("grunt_cli.commands.master.ensure_venv")
    @patch("grunt_cli.commands.master.clone_grunt")
    @patch("grunt_cli.commands.master.run_alembic", return_value=True)
    def test_master_creates_bench_mysql(
        self,
        mock_alembic,
        mock_clone,
        mock_venv,
        mock_npm,
        runner,
        tmp_path,
    ):
        mock_clone.return_value = tmp_path / "proj" / "apps" / "grunt"

        with runner.isolated_filesystem(temp_dir=tmp_path):
            # input: project, site, db_choice=3(mysql), host, port, user, password(empty), db_name, port, no admin, no serve
            result = runner.invoke(
                cli,
                ["master"],
                input="proj\ndev.local\n3\nlocalhost\n3306\nroot\n\ngrunt\n8000\nn\nn\n",
            )
            assert result.exit_code == 0
            env = (Path("proj") / "sites" / "dev.local" / ".env").read_text()
            assert "mysql+aiomysql://root@localhost:3306/grunt" in env

    @patch("grunt_cli.commands.master.install_npm_deps", return_value=True)
    @patch("grunt_cli.commands.master.ensure_venv")
    @patch("grunt_cli.commands.master.clone_grunt")
    def test_master_existing_dir_fails(
        self,
        mock_clone,
        mock_venv,
        mock_npm,
        runner,
        tmp_path,
    ):
        (tmp_path / "existing").mkdir()
        (tmp_path / "existing" / "file").write_text("x")

        with runner.isolated_filesystem(temp_dir=tmp_path):
            import os

            os.chdir(tmp_path)
            result = runner.invoke(
                cli,
                ["master"],
                input=f"{tmp_path / 'existing'}\ndev.local\n",
            )
            assert result.exit_code != 0


class TestFrameworkDelegation:
    @patch("grunt_cli.helpers.get_dotenv_path", return_value="/bench/sites/s/.env")
    @patch("grunt_cli.helpers.get_venv_grunt", return_value="/bench/apps/grunt/.venv/bin/grunt")
    @patch("subprocess.run")
    def test_unknown_command_goes_to_framework_cli(self, mock_run, _venv, _dotenv, runner):
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(cli, ["data", "import", "/tmp/b.tar", "--yes"])
        assert result.exit_code == 0, result.output
        cmd = mock_run.call_args.args[0]
        assert cmd == ["/bench/apps/grunt/.venv/bin/grunt", "data", "import", "/tmp/b.tar", "--yes"]
        assert mock_run.call_args.kwargs["env"]["DOTENV_PATH"] == "/bench/sites/s/.env"

    @patch("grunt_cli.helpers.get_venv_grunt", return_value=None)
    def test_unknown_command_outside_project(self, _venv, runner):
        result = runner.invoke(cli, ["data"])
        assert result.exit_code != 0
        assert "No such command" in result.output


class TestRestart:
    @patch("grunt_cli.commands.restart.time.sleep")
    @patch("grunt_cli.commands.restart.subprocess.run")
    def test_restarts_bench_services(self, mock_run, _sleep, runner, tmp_path, monkeypatch):
        bench = tmp_path / "mlt_prod"
        (bench / "apps").mkdir(parents=True)
        (bench / "sites").mkdir()
        units = tmp_path / "systemd"
        units.mkdir()
        for unit in ("mlt_prod-web.service", "mlt_prod-worker.service"):
            (units / unit).write_text("")
        monkeypatch.setattr("grunt_cli.commands.restart.SYSTEMD_DIR", units)
        monkeypatch.chdir(bench)
        mock_run.return_value = MagicMock(returncode=0, stdout="active\n")

        result = runner.invoke(cli, ["restart"])

        assert result.exit_code == 0, result.output
        assert mock_run.call_args_list[0].args[0] == [
            "sudo",
            "systemctl",
            "restart",
            "mlt_prod-web.service",
            "mlt_prod-worker.service",
        ]

    @patch("grunt_cli.commands.restart.time.sleep")
    @patch("grunt_cli.commands.restart.subprocess.run")
    def test_reports_service_that_did_not_start(
        self, mock_run, _sleep, runner, tmp_path, monkeypatch
    ):
        bench = tmp_path / "mlt_prod"
        (bench / "apps").mkdir(parents=True)
        (bench / "sites").mkdir()
        units = tmp_path / "systemd"
        units.mkdir()
        (units / "mlt_prod-web.service").write_text("")
        monkeypatch.setattr("grunt_cli.commands.restart.SYSTEMD_DIR", units)
        monkeypatch.chdir(bench)
        mock_run.side_effect = [MagicMock(returncode=0), MagicMock(returncode=3, stdout="failed\n")]

        result = runner.invoke(cli, ["restart", "--web"])

        assert result.exit_code != 0
        assert "не запустився" in result.output
        assert "journalctl -u mlt_prod-web.service" in result.output

    def test_not_installed_points_to_setup(self, runner, tmp_path, monkeypatch):
        bench = tmp_path / "dev"
        (bench / "apps").mkdir(parents=True)
        (bench / "sites").mkdir()
        monkeypatch.setattr("grunt_cli.commands.restart.SYSTEMD_DIR", tmp_path / "none")
        monkeypatch.chdir(bench)

        result = runner.invoke(cli, ["restart"])

        assert result.exit_code != 0
        assert "grunt setup production" in result.output


class TestGitPull:
    """_git_pull: fetch + rebase на @{upstream}, без залежності від FETCH_HEAD."""

    def _repo(self, tmp_path):
        upstream = tmp_path / "up"
        subprocess.run(["git", "init", "-q", "-b", "master", str(upstream)], check=True)
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(
            [*git, "-C", str(upstream), "commit", "-q", "--allow-empty", "-m", "a"], check=True
        )
        wc = tmp_path / "wc"
        subprocess.run(["git", "clone", "-q", str(upstream), str(wc)], check=True)
        subprocess.run(
            [*git, "-C", str(upstream), "commit", "-q", "--allow-empty", "-m", "b"], check=True
        )
        return upstream, wc

    def test_survives_duplicated_fetch_head(self, tmp_path):
        from grunt_cli.commands.update import _git_pull

        upstream, wc = self._repo(tmp_path)
        # Паралельний fetch (autofetch IDE) лишає дубльований рядок у FETCH_HEAD.
        subprocess.run(["git", "-C", str(wc), "fetch", "-q"], check=True)
        fetch_head = wc / ".git" / "FETCH_HEAD"
        fetch_head.write_text(fetch_head.read_text() * 2)

        assert _git_pull(wc, "wc") is True
        head = subprocess.run(
            ["git", "-C", str(wc), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout
        up_head = subprocess.run(
            ["git", "-C", str(upstream), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout
        assert head == up_head


class TestNpmInstall:
    """_run_npm_install: застарілий package-lock не повинен лишати прод без node_modules."""

    @patch("shutil.which", return_value="/usr/bin/npm")
    @patch("grunt_cli.commands.update.subprocess.run")
    def test_falls_back_to_no_package_lock(self, mock_run, mock_which, tmp_path):
        from grunt_cli.commands.update import _run_npm_install

        (tmp_path / "node_modules" / "vue-tsc").mkdir(parents=True)
        mock_run.side_effect = [MagicMock(returncode=1), MagicMock(returncode=0)]

        _run_npm_install(tmp_path)

        assert mock_run.call_args_list[1].args[0][-1] == "--no-package-lock"
        assert (tmp_path / "node_modules" / "vue-tsc").exists()

    @patch("shutil.which", return_value="/usr/bin/npm")
    @patch("grunt_cli.commands.update.subprocess.run", return_value=MagicMock(returncode=1))
    def test_restores_node_modules_when_all_attempts_fail(self, mock_run, mock_which, tmp_path):
        from grunt_cli.commands.update import _run_npm_install

        (tmp_path / "node_modules" / "vue-tsc").mkdir(parents=True)

        _run_npm_install(tmp_path)

        assert mock_run.call_count == 3
        assert (tmp_path / "node_modules" / "vue-tsc").exists()
        assert not (tmp_path / "node_modules.bak").exists()

    @patch("shutil.which", return_value="/usr/bin/npm")
    @patch("grunt_cli.commands.update.subprocess.run", return_value=MagicMock(returncode=0))
    def test_stale_lock_skips_plain_install(self, mock_run, mock_which, tmp_path):
        from grunt_cli.commands.update import _run_npm_install

        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"a": "^2.0.0"}}))
        (tmp_path / "package-lock.json").write_text(
            json.dumps({"packages": {"": {"dependencies": {"a": "^1.0.0"}}}})
        )

        _run_npm_install(tmp_path)

        assert mock_run.call_count == 1
        assert mock_run.call_args.args[0][-1] == "--no-package-lock"

    def test_package_lock_stale_detection(self, tmp_path):
        from grunt_cli.commands.update import _package_lock_stale

        pkg = {"dependencies": {"a": "^2.0.0"}, "devDependencies": {"b": "1"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        (tmp_path / "package-lock.json").write_text(json.dumps({"packages": {"": pkg}}))
        assert _package_lock_stale(tmp_path) is False

        (tmp_path / "package-lock.json").write_text(
            json.dumps({"packages": {"": {**pkg, "dependencies": {"a": "^1.0.0"}}}})
        )
        assert _package_lock_stale(tmp_path) is True

        (tmp_path / "package-lock.json").unlink()
        assert _package_lock_stale(tmp_path) is False
