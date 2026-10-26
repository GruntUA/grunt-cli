"""Тести для CLI команд grunt_cli."""

from __future__ import annotations

import json
import subprocess
import sys
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

    @patch("grunt_cli.commands.install.run_mise", return_value=True)
    @patch("grunt_cli.commands.install.clone_grunt")
    def test_install_creates_structure(self, mock_clone, mock_mise, runner, tmp_path):
        mock_clone.return_value = tmp_path / "test-site" / "apps" / "grunt"
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            result = runner.invoke(cli, ["install", "test-site"])
            assert result.exit_code == 0, result.output
            bench = Path(td) / "test-site"
            site_dir = bench / "sites" / "default"
            assert (bench / "apps").is_dir()
            assert (site_dir / "grunt.site").exists()
            assert (site_dir / ".env").exists()
            assert (bench / "sites" / "currentsite.txt").read_text() == "default"

            config = json.loads((site_dir / "grunt.site").read_text())
            assert "grunt" in config["installed_apps"]
        mock_mise.assert_called_once()

    @patch("grunt_cli.commands.install.run_mise", return_value=True)
    @patch("grunt_cli.commands.install.clone_grunt")
    def test_install_git_clone_failure(self, mock_clone, mock_mise, runner, tmp_path):
        mock_clone.side_effect = SystemExit(1)
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["install", "test-site"])
            assert result.exit_code != 0
        mock_mise.assert_not_called()


# ── grunt serve ─────────────────────────────────────────────────


class TestServe:
    def test_serve_outside_bench(self, runner):
        with patch("grunt_cli.commands.serve.get_bench_dir", return_value=None):
            result = runner.invoke(cli, ["serve"])
            assert result.exit_code != 0

    def test_serve_bench_no_grunt_framework(self, runner, tmp_path):
        bench = tmp_path / "bench"
        (bench / "apps").mkdir(parents=True)
        (bench / "sites").mkdir()
        with patch("grunt_cli.commands.serve.get_bench_dir", return_value=bench):
            result = runner.invoke(cli, ["serve"])
            assert result.exit_code != 0
            assert "Grunt framework не знайдено" in result.output


# ── grunt init ──────────────────────────────────────────────────


class TestInit:
    def test_init_no_site(self, runner):
        """grunt init (без аргументу) — без bench і без site_dir — помилка."""
        with (
            patch("grunt_cli.commands.init.get_bench_dir", return_value=None),
            patch("grunt_cli.commands.init.get_current_site", return_value=None),
        ):
            result = runner.invoke(cli, ["init"])
            assert result.exit_code != 0

    @patch("grunt_cli.commands.init.run_mise", return_value=True)
    def test_init_generates_secret_key(self, mock_mise, runner, tmp_path):
        """grunt init (без аргументу) — генерує SECRET_KEY і запускає mise setup."""
        site = tmp_path / "sites" / "dev.local"
        site.mkdir(parents=True)
        (site / "grunt.site").write_text("{}")
        (site / ".env").write_text("DEBUG=true\nSECRET_KEY=change-me\n")

        with (
            patch("grunt_cli.commands.init.get_bench_dir", return_value=tmp_path),
            patch("grunt_cli.commands.init.get_current_site", return_value=site),
        ):
            result = runner.invoke(cli, ["init"], input="n\n")

        assert result.exit_code == 0, result.output
        env_content = (site / ".env").read_text()
        assert "change-me" not in env_content
        assert "SECRET_KEY=" in env_content
        mock_mise.assert_called_once_with(
            tmp_path / "apps" / "grunt", "setup", env={"DOTENV_PATH": str(site / ".env")}
        )

    @patch("grunt_cli.commands.init.run_mise", return_value=True)
    @patch("grunt_cli.commands.init.clone_grunt")
    def test_init_bench_creates_structure(self, mock_clone, mock_mise, runner, tmp_path):
        """grunt init my-bench — створює bench-структуру."""
        mock_clone.return_value = tmp_path / "my-bench" / "apps" / "grunt"
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "my-bench"])
            assert result.exit_code == 0, result.output
            bench = Path("my-bench")
            assert (bench / "apps").is_dir()
            assert (bench / "sites").is_dir()
            assert (bench / "logs" / "web").is_dir()


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


# ── grunt update ────────────────────────────────────────────────


_UPGRADABLE = """Listing...
openssl/trixie-security 3.5.1-1+deb13u1 amd64 [upgradable from: 3.5.1-1]
curl/trixie 8.14.1-2 amd64 [upgradable from: 8.14.1-1]
libssl3t64/trixie-security,trixie 3.5.1-1+deb13u1 amd64 [upgradable from: 3.5.1-1]
"""


@pytest.mark.real_os_check
class TestOsUpdates:
    def _fake_run(self, calls, *, sudo_ok=True, listing=_UPGRADABLE):
        def run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[0] == "apt":
                return subprocess.CompletedProcess(cmd, 0, listing, "")
            if cmd[:2] == ["sudo", "-v"]:  # the password was typed in
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0 if sudo_ok else 1, "", "")

        return run

    def _check(self, monkeypatch, tmp_path, *, interactive=False, **fake):
        from grunt_cli.commands import update

        calls = []
        monkeypatch.setattr(update.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(update.os, "geteuid", lambda: 1000)
        monkeypatch.setattr(update.subprocess, "run", self._fake_run(calls, **fake))
        monkeypatch.setattr(update, "_interactive", lambda: interactive)
        monkeypatch.setattr(update, "_APT_LISTS", tmp_path)
        monkeypatch.setattr(update, "_REBOOT_REQUIRED", tmp_path / "reboot-required")
        with update.console.capture() as out:
            update._check_os_updates()
        return calls, " ".join(out.get().split())  # the console wraps long lines

    def test_upgradable_security_first(self, monkeypatch, tmp_path):
        calls, out = self._check(monkeypatch, tmp_path)
        assert calls[0] == ["sudo", "-n", "apt-get", "update", "-qq"]
        assert "Списки пакетів ОС оновлено" in out
        assert "Можна оновити пакетів ОС: 3, з них безпекових: 2 — sudo apt upgrade" in out
        assert "openssl, libssl3t64, curl" in out

    def test_without_sudo_uses_existing_lists(self, monkeypatch, tmp_path):
        (tmp_path / "deb.debian.org_dists_trixie_InRelease").touch()
        calls, out = self._check(monkeypatch, tmp_path, sudo_ok=False, listing="Listing...\n")
        assert [c[:2] for c in calls] == [["sudo", "-n"], ["apt", "list"]]  # no password prompt
        assert "потребує sudo" in out and "оновлені 0 год тому" in out
        assert "Пакети ОС актуальні" in out

    def test_terminal_asks_for_the_password(self, monkeypatch, tmp_path):
        calls, _ = self._check(monkeypatch, tmp_path, interactive=True, sudo_ok=False)
        # the password is asked outside the spinner, then apt-get runs with the cached sudo
        assert calls[1][:3] == ["sudo", "-v", "-p"]
        assert calls[2] == ["sudo", "-n", "apt-get", "update", "-qq"]

    def test_apt_timeout_falls_back_to_existing_lists(self, monkeypatch, tmp_path):
        from grunt_cli.commands import update

        def run(cmd, **kwargs):
            if cmd[0] == "apt":
                return subprocess.CompletedProcess(cmd, 0, "", "")
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

        monkeypatch.setattr(update.os, "geteuid", lambda: 0)
        monkeypatch.setattr(update.subprocess, "run", run)
        assert update._apt_refresh() is False

    def test_reboot_required(self, monkeypatch, tmp_path):
        (tmp_path / "reboot-required").touch()
        _, out = self._check(monkeypatch, tmp_path, listing="")
        assert "потрібне перезавантаження" in out

    def test_no_apt(self, monkeypatch):
        from grunt_cli.commands import update

        monkeypatch.setattr(update.shutil, "which", lambda name: None)
        with update.console.capture() as out:
            update._check_os_updates()
        assert "apt не знайдено" in out.get()


class TestUpdate:
    def test_pdf_browser_installed_with_venv_python(self, tmp_path):
        from grunt_cli.commands import update

        python = tmp_path / "grunt" / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.touch()
        with (
            patch.object(update, "_find_apps_dir", return_value=tmp_path),
            patch.object(update, "run_captured", return_value=0) as run,
        ):
            assert update._install_pdf_browser()
        cmd = run.call_args.args[0]
        assert cmd == [str(python), "-m", "playwright", "install", "--only-shell", "chromium"]

    def test_pdf_browser_skipped_without_venv(self, tmp_path):
        from grunt_cli.commands import update

        with (
            patch.object(update, "_find_apps_dir", return_value=tmp_path),
            patch.object(update, "run_captured") as run,
        ):
            assert update._install_pdf_browser()
        run.assert_not_called()

    @patch("grunt_cli.commands.update._restart_production", return_value=True)
    @patch("grunt_cli.commands.update._run_migrations", return_value=True)
    @patch("grunt_cli.commands.update._run_npm_install")
    @patch("grunt_cli.commands.update._update_python_packages")
    @patch("grunt_cli.commands.update._update_runtimes")
    @patch("grunt_cli.commands.update._get_cli_dir", return_value=None)
    @patch("grunt_cli.commands.update._find_apps_dir", return_value=None)
    def test_update_nothing_found(
        self, _apps, _cli, _runtimes, _packages, _npm, _migrate, _restart, runner
    ):
        # Кроки пакетів/міграцій замокані: інакше тест справді запускав би
        # `uv sync --upgrade` у поточній теці.
        result = runner.invoke(cli, ["update"])
        assert result.exit_code == 0, result.output
        assert "grunt-cli не встановлений" in result.output
        assert "Grunt framework не знайдено" in result.output
        assert "Директорію додатків не знайдено" in result.output

    @patch("grunt_cli.commands.update._restart_production", return_value=True)
    @patch("grunt_cli.commands.update._run_migrations", return_value=True)
    @patch("grunt_cli.commands.update._run_npm_install")
    @patch("grunt_cli.commands.update._update_python_packages")
    @patch("grunt_cli.commands.update._update_repo")
    @patch("grunt_cli.commands.update._get_cli_dir", return_value=None)
    def test_runtimes_before_framework_deps(
        self, _cli, _repo, _packages, _npm, _migrate, _restart, runner, tmp_path, monkeypatch
    ):
        # Інакше `mise run deps` перестворює venv ще старим uv, який не знає
        # новішого Python (3.15.0rc2 замість 3.15.0).
        from grunt_cli.commands import update

        (tmp_path / "apps" / "grunt").mkdir(parents=True)
        monkeypatch.setattr(update, "_find_apps_dir", lambda: tmp_path / "apps")
        order = []
        monkeypatch.setattr(update, "_update_runtimes", lambda: order.append("runtimes"))
        monkeypatch.setattr(
            update, "_install_deps", lambda path, label: order.append(f"deps {label}") or True
        )

        result = runner.invoke(cli, ["update"])
        assert result.exit_code == 0, result.output
        assert order == ["runtimes", "deps grunt"]

    @patch("grunt_cli.commands.update._restart_production", return_value=True)
    @patch("grunt_cli.commands.update._run_migrations", return_value=True)
    @patch("grunt_cli.commands.update._run_npm_install")
    @patch("grunt_cli.commands.update._update_python_packages")
    @patch("grunt_cli.commands.update._update_runtimes")
    @patch("grunt_cli.commands.update._update_repo")
    @patch("grunt_cli.commands.update._get_cli_dir", return_value=None)
    def test_unchanged_deps_are_not_reinstalled(
        self, _cli, _repo, _runtimes, mock_packages, _npm, _migrate, _restart, runner, tmp_path
    ):
        from grunt_cli.commands import update

        framework = tmp_path / "apps" / "grunt"
        framework.mkdir(parents=True)
        (framework / "uv.lock").write_text("v1")
        installs = []
        with (
            patch.object(update, "_find_apps_dir", return_value=tmp_path / "apps"),
            patch.object(update, "_install_deps", lambda p, label: installs.append(label) or True),
        ):
            assert runner.invoke(cli, ["update", "--framework"]).exit_code == 0
            result = runner.invoke(cli, ["update", "--framework"])
            assert result.exit_code == 0, result.output
            assert "Пакети grunt: без змін" in result.output
            assert installs == ["grunt"]

            (framework / "uv.lock").write_text("v2")
            assert runner.invoke(cli, ["update", "--framework"]).exit_code == 0
            assert installs == ["grunt", "grunt"]

        # `mise run deps` фреймворку вже зробила uv sync і grunt app deps.
        mock_packages.assert_not_called()

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
        assert (cli_dir, "run", "install") in [c.args for c in mock_mise.call_args_list]
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
        assert (bench / "apps" / "grunt", "build") in [c.args for c in mock_mise.call_args_list]
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

    @patch("grunt_cli.commands.update.restart_units", return_value=True)
    @patch("grunt_cli.commands.update.run_mise", return_value=True)
    @patch("grunt_cli.commands.update._run_migrations", return_value=True)
    def test_unchanged_code_skips_migrate_and_restart(
        self, mock_migrate, _mise, mock_restart, runner, tmp_path, monkeypatch
    ):
        bench = self._bench(tmp_path, monkeypatch, ("mlt_prod-web.service",))
        framework = bench / "apps" / "grunt"
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(framework)]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "a"], check=True)

        assert self._run(runner).exit_code == 0
        result = self._run(runner)
        assert result.exit_code == 0, result.output
        assert "Код не змінився" in result.output
        assert "перезапуск не потрібні" in result.output
        assert (mock_migrate.call_count, mock_restart.call_count) == (1, 1)

        # Новий файл у коді — знову мігруємо й перезапускаємо.
        (framework / "new_doctype.json").write_text("{}")
        assert self._run(runner).exit_code == 0
        assert (mock_migrate.call_count, mock_restart.call_count) == (2, 2)

        assert self._run(runner, "--full").exit_code == 0
        assert (mock_migrate.call_count, mock_restart.call_count) == (3, 3)

    @patch("grunt_cli.commands.update.venv_delegate", return_value=0)
    def test_migrations_run_full_framework_migrate(self, mock_delegate, tmp_path, monkeypatch):
        from grunt_cli.commands.update import _run_migrations

        site = tmp_path / "site"
        site.mkdir()
        monkeypatch.setattr("grunt_cli.commands.update.get_current_site", lambda: site)
        assert _run_migrations(None) is True
        mock_delegate.assert_called_once()
        assert mock_delegate.call_args.args == ("migrate",)
        assert mock_delegate.call_args.kwargs["site"] is None


# ── grunt master ───────────────────────────────────────────────


class TestMaster:
    @patch("grunt_cli.commands.master.run_mise", return_value=True)
    @patch("grunt_cli.commands.master.clone_grunt")
    def test_master_creates_bench_sqlite(
        self,
        mock_clone,
        mock_mise,
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

    @patch("grunt_cli.commands.master.run_mise", return_value=True)
    @patch("grunt_cli.commands.master.clone_grunt")
    def test_master_creates_bench_postgres(
        self,
        mock_clone,
        mock_mise,
        runner,
        tmp_path,
    ):
        mock_clone.return_value = tmp_path / "proj" / "apps" / "grunt"

        with runner.isolated_filesystem(temp_dir=tmp_path):
            # input: project, site, db=2 (postgres), host, port, user, password, db name,
            # backend port, no admin, no serve
            result = runner.invoke(
                cli,
                ["master"],
                input="proj\nprod.example.com\n2\nlocalhost\n5432\npostgres\nsecret\nmydb\n9000\nn\nn\n",
            )
            assert result.exit_code == 0
            env = (Path("proj") / "sites" / "prod.example.com" / ".env").read_text()
            assert "postgresql+asyncpg://postgres:secret@localhost:5432/mydb" in env

    @patch("grunt_cli.commands.master.run_mise", return_value=True)
    @patch("grunt_cli.commands.master.clone_grunt")
    def test_master_creates_bench_mysql(
        self,
        mock_clone,
        mock_mise,
        runner,
        tmp_path,
    ):
        mock_clone.return_value = tmp_path / "proj" / "apps" / "grunt"

        with runner.isolated_filesystem(temp_dir=tmp_path):
            # input: project, site, db=3 (mysql), host, port, user, empty password, db name,
            # backend port, no admin, no serve
            result = runner.invoke(
                cli,
                ["master"],
                input="proj\ndev.local\n3\nlocalhost\n3306\nroot\n\ngrunt\n8000\nn\nn\n",
            )
            assert result.exit_code == 0
            env = (Path("proj") / "sites" / "dev.local" / ".env").read_text()
            assert "mysql+aiomysql://root@localhost:3306/grunt" in env

    @patch("grunt_cli.commands.master.run_mise", return_value=True)
    @patch("grunt_cli.commands.master.clone_grunt")
    def test_master_existing_dir_fails(
        self,
        mock_clone,
        mock_mise,
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
    @patch(
        "grunt_cli.helpers.get_venv_grunt",
        return_value=["/bench/apps/grunt/.venv/bin/python", "-m", "grunt.cli.main"],
    )
    @patch("subprocess.run")
    def test_unknown_command_goes_to_framework_cli(self, mock_run, _venv, _dotenv, runner):
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(cli, ["data", "import", "/tmp/b.tar", "--yes"])
        assert result.exit_code == 0, result.output
        cmd = mock_run.call_args.args[0]
        assert cmd == [
            "/bench/apps/grunt/.venv/bin/python",
            "-m",
            "grunt.cli.main",
            "data",
            "import",
            "/tmp/b.tar",
            "--yes",
        ]
        assert mock_run.call_args.kwargs["env"]["DOTENV_PATH"] == "/bench/sites/s/.env"

    @patch(
        "grunt_cli.helpers.get_venv_grunt",
        return_value=["/bench/apps/grunt/.venv/bin/python", "-m", "grunt.cli.main"],
    )
    @patch("subprocess.run")
    def test_app_create_goes_to_framework_cli(self, mock_run, _venv, runner):
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(cli, ["app", "create", "my_app", "--no-git"])
        assert result.exit_code == 0, result.output
        assert mock_run.call_args.args[0][-4:] == ["app", "create", "my_app", "--no-git"]

    @pytest.mark.parametrize(
        "args",
        [
            # колись мали власні (дубльовані) реалізації в grunt-cli
            ["migrate", "--site", "s1", "--no-alembic"],
            ["db", "backup", "--site", "s1"],
            ["db", "rollback", "2"],
            ["doctype", "sync-types", "--all", "--app", "crm"],
            ["fixtures", "dump", "Invoice", "--limit", "5"],
            ["site", "create", "s2"],
            ["sites", "new", "s2"],
            ["users", "list"],
            ["shell"],
            ["test", "crm", "-k", "smoke"],
            ["lint", "--format", "json", "-j", "2"],
            ["app", "uninstall", "crm", "--keep-data"],
        ],
    )
    @patch(
        "grunt_cli.helpers.get_venv_grunt",
        return_value=["/bench/apps/grunt/.venv/bin/python", "-m", "grunt.cli.main"],
    )
    @patch("subprocess.run")
    def test_framework_commands_are_forwarded_verbatim(self, mock_run, _venv, runner, args):
        mock_run.return_value = MagicMock(returncode=3)
        result = runner.invoke(cli, args)
        assert result.exit_code == 3, result.output
        assert mock_run.call_args.args[0][3:] == args

    @patch("grunt_cli.helpers.get_venv_grunt", return_value=None)
    def test_unknown_command_outside_project(self, _venv, runner):
        result = runner.invoke(cli, ["migrate"])
        assert result.exit_code != 0
        assert "No such command" in result.output
        assert "bench-проєкту" in result.output


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

    def test_prefetched_repo_is_not_fetched_again(self, tmp_path):
        from grunt_cli.commands import update

        upstream, wc = self._repo(tmp_path)
        update._prefetched.clear()
        update._prefetch([(wc, ())])
        with patch.object(update, "_git_fetch") as mock_fetch:
            assert update._git_pull(wc, "wc") is True
        mock_fetch.assert_not_called()
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


class TestUpdateToRelease:
    """_update_repo: прод і репо на тезі — на реліз-теги, розробка — голова гілки."""

    GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]

    def _commit(self, repo, msg, tag=None):
        subprocess.run(
            [*self.GIT, "-C", str(repo), "commit", "-q", "--allow-empty", "-m", msg], check=True
        )
        if tag:
            subprocess.run([*self.GIT, "-C", str(repo), "tag", "-a", tag, "-m", tag], check=True)

    def _repo(self, tmp_path, tags=("v0.1.0", "v0.2.0")):
        upstream = tmp_path / "up"
        subprocess.run(["git", "init", "-q", "-b", "master", str(upstream)], check=True)
        self._commit(upstream, "a", tags[0] if tags else None)
        wc = tmp_path / "wc"
        subprocess.run(["git", "clone", "-q", str(upstream), str(wc)], check=True)
        for i, tag in enumerate(tags[1:]):
            self._commit(upstream, f"r{i}", tag)
        self._commit(upstream, "unreleased")
        return upstream, wc

    @staticmethod
    def _head(repo, *rev):
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", *(rev or ("HEAD",))],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def _at(self, wc, ref):
        return self._head(wc) == self._head(wc, f"{ref}^{{commit}}")

    def test_production_goes_to_latest_release(self, tmp_path):
        from grunt_cli.commands.update import _update_repo

        _, wc = self._repo(tmp_path)
        assert _update_repo(wc, "wc", tag=None, branch=False, production=True)
        assert self._at(wc, "v0.2.0")

    def test_development_follows_branch(self, tmp_path):
        from grunt_cli.commands.update import _update_repo

        up, wc = self._repo(tmp_path)
        assert _update_repo(wc, "wc", tag=None, branch=False, production=False)
        assert self._head(wc) == self._head(up)

    def test_production_without_tags_follows_branch(self, tmp_path):
        from grunt_cli.commands.update import _update_repo

        up, wc = self._repo(tmp_path, tags=())
        assert _update_repo(wc, "wc", tag=None, branch=False, production=True)
        assert self._head(wc) == self._head(up)

    def test_repo_on_a_tag_moves_to_newer_release(self, tmp_path):
        from grunt_cli.commands.update import _update_repo

        up, wc = self._repo(tmp_path)
        assert _update_repo(wc, "wc", tag="v0.1.0", branch=False, production=False)
        self._commit(up, "next", "v0.3.0")
        assert _update_repo(wc, "wc", tag=None, branch=False, production=False)
        assert self._at(wc, "v0.3.0")

    def test_pin_older_release_without_migrations(self, tmp_path):
        from grunt_cli.commands.update import _update_repo

        _, wc = self._repo(tmp_path)
        assert _update_repo(wc, "wc", tag=None, branch=False, production=True)
        assert _update_repo(wc, "wc", tag="v0.1.0", branch=False, production=True)
        assert self._at(wc, "v0.1.0")

    def test_rollback_past_a_migration_needs_force(self, tmp_path, capsys):
        from grunt_cli.commands.update import _update_repo

        up, wc = self._repo(tmp_path)
        migration = up / "grunt" / "db" / "migrations" / "versions" / "0011_x.py"
        migration.parent.mkdir(parents=True)
        migration.write_text("")
        subprocess.run(["git", "-C", str(up), "add", "."], check=True)
        self._commit(up, "migration", "v0.3.0")

        assert _update_repo(wc, "wc", tag=None, branch=False, production=True)
        assert self._at(wc, "v0.3.0")
        assert not _update_repo(wc, "wc", tag="v0.2.0", branch=False, production=True)
        assert self._at(wc, "v0.3.0")
        assert "0011_x" in capsys.readouterr().out

        assert _update_repo(wc, "wc", tag="v0.2.0", branch=False, production=True, force=True)
        assert self._at(wc, "v0.2.0")

    def test_unknown_release_fails(self, tmp_path):
        from grunt_cli.commands.update import _update_repo

        _, wc = self._repo(tmp_path)
        assert not _update_repo(wc, "wc", tag="v9.9.9", branch=False, production=True)

    def test_branch_flag_leaves_the_tag(self, tmp_path):
        from grunt_cli.commands.update import _update_repo

        up, wc = self._repo(tmp_path)
        assert _update_repo(wc, "wc", tag=None, branch=False, production=True)
        assert _update_repo(wc, "wc", tag=None, branch=True, production=True)
        assert self._head(wc) == self._head(up)
        assert self._head(wc, "--abbrev-ref", "HEAD") == "master"

    def test_local_changes_block_the_release(self, tmp_path):
        from grunt_cli.commands.update import _update_repo

        _, wc = self._repo(tmp_path)
        (wc / "f.txt").write_text("1")
        subprocess.run([*self.GIT, "-C", str(wc), "add", "f.txt"], check=True)
        before = self._head(wc)
        assert not _update_repo(wc, "wc", tag=None, branch=False, production=True)
        assert self._head(wc) == before

    def test_tag_and_branch_are_exclusive(self, runner):
        result = runner.invoke(cli, ["update", "--tag", "--branch"])
        assert result.exit_code != 0
        assert "взаємовиключні" in result.output


class TestPythonPackages:
    """uv.lock під git: grunt update ставить закомічені версії і не переписує lock."""

    @pytest.mark.parametrize(("has_lock", "mode"), [(True, "--locked"), (False, "--upgrade")])
    @patch("grunt_cli.commands.update.find_uv", return_value="/usr/bin/uv")
    @patch("grunt_cli.commands.update.subprocess.run", return_value=MagicMock(returncode=0))
    def test_sync_mode_follows_lockfile(self, mock_run, _uv, tmp_path, monkeypatch, has_lock, mode):
        from grunt_cli.commands.update import _update_python_packages

        (tmp_path / "apps" / "grunt").mkdir(parents=True)
        if has_lock:
            (tmp_path / "apps" / "grunt" / "uv.lock").write_text("")
        monkeypatch.setattr("grunt_cli.commands.update._find_apps_dir", lambda: tmp_path / "apps")

        _update_python_packages()

        sync = mock_run.call_args_list[0].args[0]
        assert sync[:3] == ["/usr/bin/uv", "sync", mode]


class TestRuntimes:
    """grunt update оновлює mise, рантайми з mise.toml, Python і rclone фреймворку."""

    @patch("grunt_cli.commands.update.run_mise", return_value=True)
    @patch("grunt_cli.commands.update.find_uv", return_value="/usr/bin/uv")
    @patch("grunt_cli.commands.update.get_mise_bin", return_value="/usr/bin/mise")
    @patch("grunt_cli.commands.update.subprocess.run", return_value=MagicMock(returncode=0))
    def test_upgrades_everything(self, mock_run, _mise, _uv, mock_run_mise, tmp_path, monkeypatch):
        from grunt_cli.commands import update

        grunt_dir = tmp_path / "apps" / "grunt"
        grunt_dir.mkdir(parents=True)
        (grunt_dir / "mise.toml").write_text("[tools]\n")
        rclone = tmp_path / "rclone"
        rclone.write_text("")
        rclone.chmod(0o755)
        monkeypatch.setattr(update, "get_bench_dir", lambda: tmp_path)
        monkeypatch.setattr(update, "_MANAGED_RCLONE", rclone)
        # `mise which uv` нічого не дав — запасний find_uv()
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        update._update_runtimes()

        commands = [c.args[0] for c in mock_run.call_args_list]
        assert ["/usr/bin/mise", "self-update", "--yes"] in commands
        assert ["/usr/bin/uv", "python", "upgrade"] in commands
        assert [str(rclone), "selfupdate"] in commands
        assert (grunt_dir, "install") in [c.args for c in mock_run_mise.call_args_list]
        assert (grunt_dir, "upgrade") in [c.args for c in mock_run_mise.call_args_list]

    @patch("grunt_cli.commands.update.find_uv", return_value=None)
    @patch("grunt_cli.commands.update.get_mise_bin", return_value=None)
    @patch("grunt_cli.commands.update.subprocess.run")
    def test_no_rclone_of_our_own(self, mock_run, _mise, _uv, tmp_path, monkeypatch):
        from grunt_cli.commands import update

        monkeypatch.setattr(update, "_MANAGED_RCLONE", tmp_path / "missing")
        update._update_runtimes()
        mock_run.assert_not_called()


class TestProjectUv:
    """uv для проєкту — з mise.toml фреймворку, навіть коли grunt update
    запущено з кореня бенча, де mise-шим uv не знає версії."""

    def test_mise_which_in_runtime_dir(self, tmp_path, monkeypatch):
        from grunt_cli.commands import update

        uv = "/home/u/.local/share/mise/installs/uv/0.13.0/uv"
        monkeypatch.setattr(update, "get_mise_bin", lambda: "/bin/mise")
        monkeypatch.setattr(update, "_runtime_dir", lambda: tmp_path)
        monkeypatch.setattr(update, "find_uv", lambda: "/shims/uv")
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs.get("cwd")))
            return MagicMock(returncode=0, stdout=f"{uv}\n")

        monkeypatch.setattr(update.subprocess, "run", fake_run)
        assert update._project_uv() == uv
        assert calls == [(["/bin/mise", "which", "uv"], str(tmp_path))]

    @pytest.mark.parametrize(
        ("mise", "runtime", "result"),
        [
            ("/bin/mise", True, MagicMock(returncode=1, stdout="")),
            ("/bin/mise", False, None),
            (None, True, None),
        ],
    )
    def test_falls_back_to_find_uv(self, tmp_path, monkeypatch, mise, runtime, result):
        from grunt_cli.commands import update

        monkeypatch.setattr(update, "get_mise_bin", lambda: mise)
        monkeypatch.setattr(update, "_runtime_dir", lambda: tmp_path if runtime else None)
        monkeypatch.setattr(update, "find_uv", lambda: "/shims/uv")
        monkeypatch.setattr(update.subprocess, "run", lambda cmd, **kw: result)
        assert update._project_uv() == "/shims/uv"


class TestUpgradePackages:
    @patch("grunt_cli.commands.update.find_uv", return_value="/usr/bin/uv")
    @patch("grunt_cli.commands.update.subprocess.run", return_value=MagicMock(returncode=0))
    def test_relocks_before_sync(self, mock_run, _uv, tmp_path, monkeypatch):
        from grunt_cli.commands.update import _update_python_packages

        (tmp_path / "apps" / "grunt").mkdir(parents=True)
        (tmp_path / "apps" / "grunt" / "uv.lock").write_text("")
        monkeypatch.setattr("grunt_cli.commands.update._find_apps_dir", lambda: tmp_path / "apps")

        _update_python_packages(upgrade=True)

        commands = [c.args[0][:3] for c in mock_run.call_args_list]
        assert commands[:2] == [
            ["/usr/bin/uv", "lock", "--upgrade"],
            ["/usr/bin/uv", "sync", "--locked"],
        ]

    def test_refused_in_production(self, runner, tmp_path, monkeypatch):
        bench = tmp_path / "prod"
        (bench / "apps" / "grunt").mkdir(parents=True)
        (bench / "sites").mkdir()
        systemd = tmp_path / "systemd"
        systemd.mkdir()
        (systemd / "prod-web.service").write_text("")
        monkeypatch.setattr("grunt_cli.commands.restart.SYSTEMD_DIR", systemd)
        monkeypatch.chdir(bench)

        result = runner.invoke(cli, ["update", "--upgrade-packages"])

        assert result.exit_code != 0
        assert "лише в розробці" in result.output


class TestAskUpgradePackages:
    """Розробка: grunt update сам показує новіші пакети й питає про lock-файли."""

    @staticmethod
    def _run(
        runner,
        tmp_path,
        monkeypatch,
        *args,
        outdated=None,
        answer="y",
    ):
        if outdated is None:
            outdated = {"python": ["aiohttp 3.14.4 → 3.14.5"]}
        bench = tmp_path / "dev"
        (bench / "apps" / "grunt").mkdir(parents=True)
        (bench / "sites").mkdir()
        systemd = tmp_path / "systemd"
        systemd.mkdir()
        monkeypatch.setattr("grunt_cli.commands.restart.SYSTEMD_DIR", systemd)
        monkeypatch.chdir(bench)
        monkeypatch.setattr("grunt_cli.commands.update._interactive", lambda: True)
        with (
            patch(
                "grunt_cli.commands.update._outdated_packages",
                return_value=(outdated, ["vitest 4.1.11 → 5.0.4"]),
            ),
            patch("grunt_cli.commands.update._update_python_packages") as packages,
            patch("grunt_cli.commands.update._run_npm_install") as npm,
            patch("grunt_cli.commands.update._run_migrations", return_value=True),
            patch("grunt_cli.commands.update._get_cli_dir", return_value=None),
            patch("grunt_cli.commands.update._git_pull", return_value=True),
        ):
            result = runner.invoke(
                cli, ["update", "--framework", "--no-deps", *args], input=f"{answer}\n"
            )
        result.npm = npm
        return result, packages

    def test_asks_and_upgrades(self, runner, tmp_path, monkeypatch):
        result, packages = self._run(runner, tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        assert "aiohttp 3.14.4 → 3.14.5" in result.output
        assert "vitest 4.1.11 → 5.0.4" in result.output  # мажорна — лише для довідки
        assert "Python — фреймворк (uv.lock)" in result.output
        assert "Оновити uv.lock (потім" in result.output
        packages.assert_called_once_with(upgrade=True)
        # у npm новіших немає — його не оновлюємо
        assert all(not c.kwargs.get("upgrade") for c in result.npm.call_args_list)

    def test_only_npm_outdated(self, runner, tmp_path, monkeypatch):
        result, packages = self._run(
            runner, tmp_path, monkeypatch, outdated={"npm": ["vue 3.5.1 → 3.5.4"]}
        )
        assert result.exit_code == 0, result.output
        assert "Node.js — npm (package-lock.json)" in result.output
        assert "Оновити package-lock.json" in result.output
        packages.assert_called_once_with(upgrade=False)
        result.npm.assert_called_once()
        assert result.npm.call_args.kwargs == {"upgrade": True}

    def test_declined(self, runner, tmp_path, monkeypatch):
        result, packages = self._run(runner, tmp_path, monkeypatch, answer="n")
        assert result.exit_code == 0, result.output
        packages.assert_called_once_with(upgrade=False)

    def test_nothing_outdated_no_question(self, runner, tmp_path, monkeypatch):
        result, packages = self._run(runner, tmp_path, monkeypatch, outdated={})
        assert "найновіших версій" in result.output
        assert "Оновити uv.lock" not in result.output
        packages.assert_called_once_with(upgrade=False)

    def test_opt_out(self, runner, tmp_path, monkeypatch):
        with patch("grunt_cli.commands.update._ask_upgrade_packages") as ask:
            result, packages = self._run(runner, tmp_path, monkeypatch, "--no-upgrade-packages")
        assert result.exit_code == 0, result.output
        ask.assert_not_called()
        packages.assert_called_once_with(upgrade=False)


class TestDepsFingerprint:
    """Пакети перевстановлюються, лише коли змінилось те, від чого вони залежать."""

    @staticmethod
    def _fp(d):
        from grunt_cli.commands.update import _deps_fingerprint

        return _deps_fingerprint(d)

    def test_metadata_does_not_count(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "app"\ndependencies = ["httpx>=1"]\n\n'
            '[tool.grunt]\ntitle = "App"\ndepends_on = []\n'
        )
        (tmp_path / "package.json").write_text('{"name": "app", "dependencies": {"vue": "^3"}}')
        (tmp_path / "mise.toml").write_text('[tools]\nnode = "26"\n[tasks.lint]\nrun = "ruff"\n')
        before = self._fp(tmp_path)
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "app"\ndescription = "x"\n'
            'dependencies = ["httpx>=1"]  # comment\n\n'
            '[tool.grunt]\ntitle = "Інша назва"\ndepends_on = []\n'
        )
        (tmp_path / "package.json").write_text(
            '{"name": "app", "version": "2.0.0", "dependencies": {"vue": "^3"}}'
        )
        (tmp_path / "mise.toml").write_text('[tools]\nnode = "26"\n[tasks.lint]\nrun = "x"\n')
        assert self._fp(tmp_path) == before

    @pytest.mark.parametrize(
        ("name", "text"),
        [
            ("pyproject.toml", '[project]\ndependencies = ["httpx>=2"]\n'),
            (
                "pyproject.toml",
                '[project]\ndependencies = ["httpx>=1"]\n[tool.grunt]\ndepends_on = ["hrm"]\n',
            ),
            ("package.json", '{"dependencies": {"vue": "^4"}}'),
            ("mise.toml", '[tools]\nnode = "27"\n'),
            ("uv.lock", "version = 1\n"),
        ],
    )
    def test_dependencies_count(self, tmp_path, name, text):
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["httpx>=1"]\n')
        (tmp_path / "package.json").write_text('{"dependencies": {"vue": "^3"}}')
        (tmp_path / "mise.toml").write_text('[tools]\nnode = "26"\n')
        before = self._fp(tmp_path)
        (tmp_path / name).write_text(text)
        assert self._fp(tmp_path) != before


@pytest.mark.real_cleanup
class TestCleanup:
    """Після оновлення прибираються лише старі рантайми, на які ніщо не спирається."""

    @staticmethod
    def _home(tmp_path, monkeypatch):
        home = tmp_path / "home"
        managed = home / ".local/share/uv/python"
        for name in (
            "cpython-3.14.4-linux-x86_64-gnu",
            "cpython-3.14.8-linux-x86_64-gnu",
            "cpython-3.15.0-linux-x86_64-gnu",
        ):
            (managed / name / "bin").mkdir(parents=True)
            (managed / name / "bin" / "python3").write_text("")
        # minor-посилання, як робить uv: 3.15 → 3.15.0
        (managed / "cpython-3.15-linux-x86_64-gnu").symlink_to(
            managed / "cpython-3.15.0-linux-x86_64-gnu"
        )
        grunt_dir = home / "my-site/apps/grunt"
        (grunt_dir / ".venv").mkdir(parents=True)
        (grunt_dir / ".venv" / "pyvenv.cfg").write_text(
            f"home = {managed}/cpython-3.15-linux-x86_64-gnu/bin\nversion_info = 3.15\n"
        )
        # venv у node_modules не рахується (туди не заходимо)
        nm = grunt_dir / "node_modules/x/.venv"
        nm.mkdir(parents=True)
        (nm / "pyvenv.cfg").write_text(f"home = {managed}/cpython-3.14.4-linux-x86_64-gnu/bin\n")
        monkeypatch.setattr("grunt_cli.commands.update.Path.home", lambda: home)
        monkeypatch.setattr("grunt_cli.commands.update._find_apps_dir", lambda: grunt_dir.parent)
        monkeypatch.setattr("shutil.which", lambda name: None)
        return home, managed, grunt_dir

    def test_python_removed_or_kept_with_reason(self, tmp_path, monkeypatch):
        import json

        from grunt_cli.commands import update

        home, managed, _grunt = self._home(tmp_path, monkeypatch)
        listed = [
            {
                "key": f"cpython-{v}-linux-x86_64-gnu",
                "version": v,
                "path": f"{managed}/cpython-{v}-linux-x86_64-gnu/bin/python3",
            }
            for v in ("3.14.4", "3.14.8", "3.15.0")
        ] + [{"key": "cpython-3.13.5-linux-x86_64-gnu", "version": "3.13.5", "path": "/usr/bin/x"}]
        real_in_use = update._in_use
        # 3.14.8 тримає запущений процес (сервер ще не перезапущено)
        held = {f"{managed}/cpython-3.14.8-linux-x86_64-gnu/bin/python3": ["процес 42 (uvicorn)"]}
        monkeypatch.setattr(update, "_in_use", lambda: {**real_in_use(), **held})
        monkeypatch.setattr(update, "find_uv", lambda: "/bin/uv")
        monkeypatch.setattr(update, "get_mise_bin", lambda: None)
        monkeypatch.setattr(update, "_uv_cache_holders", lambda: "")
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return MagicMock(returncode=0, stdout=json.dumps(listed) if "list" in cmd else "")

        monkeypatch.setattr(update.subprocess, "run", fake_run)
        removed, kept, _notes = update._cleanup_runtimes()

        uninstalled = [c[-1] for c in calls if c[1:3] == ["python", "uninstall"]]
        assert uninstalled == ["cpython-3.14.4-linux-x86_64-gnu"]
        assert removed == ["Python 3.14.4 (uv)"]
        # 3.15 — поточний (venv фреймворку), у звіті не згадується
        assert kept == ["Python 3.14.8 (uv) — процес 42 (uvicorn)"]
        assert ["/bin/uv", "cache", "prune"] in calls

    def test_mise_removes_free_versions_only(self, tmp_path, monkeypatch):
        from grunt_cli.commands import update

        home, _managed, grunt_dir = self._home(tmp_path, monkeypatch)
        (grunt_dir / "mise.toml").write_text('[tools]\nnode = "26"\nuv = "latest"\n')
        cli_dir = home / "grunt-cli"
        cli_dir.mkdir()
        (cli_dir / "mise.toml").write_text('[tools]\npython = "3.15"\n')
        node = home / ".local/share/mise/installs/node/26.8.1/bin/node"
        plan = (
            "mise node@26.8.1 is prunable: node is required at 26.11.1\n"
            "mise uv@0.11.7 is prunable: uv is required at 0.13.0\n"
        )
        monkeypatch.setattr(update, "_in_use", lambda: {str(node): ["процес 7 (node)"]})
        monkeypatch.setattr(update, "find_uv", lambda: None)
        monkeypatch.setattr(update, "get_mise_bin", lambda: "/bin/mise")
        monkeypatch.setattr(update, "_runtime_dir", lambda: grunt_dir)
        monkeypatch.setattr(update, "_get_cli_dir", lambda: cli_dir)
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return MagicMock(returncode=0, stdout="", stderr=plan if "--dry-run" in cmd else "")

        monkeypatch.setattr(update.subprocess, "run", fake_run)
        removed, kept, _notes = update._cleanup_runtimes()

        # лише інструменти з mise.toml — rclone та інше не згадується
        assert ["/bin/mise", "prune", "--dry-run", "node", "python", "uv"] in calls
        assert ["/bin/mise", "uninstall", "uv@0.11.7"] in calls
        assert ["/bin/mise", "uninstall", "node@26.8.1"] not in calls
        assert removed == ["uv 0.11.7 (mise)"]
        assert kept == ["node 26.8.1 (mise) — процес 7 (node)"]

    def test_uv_cache_left_alone_while_uv_run_holds_it(self, tmp_path, monkeypatch):
        from grunt_cli.commands import update

        self._home(tmp_path, monkeypatch)
        monkeypatch.setattr(update, "_in_use", dict)
        monkeypatch.setattr(update, "find_uv", lambda: "/bin/uv")
        monkeypatch.setattr(update, "get_mise_bin", lambda: None)
        monkeypatch.setattr(update, "_uv_cache_holders", lambda: "процес 5 (uv run uvicorn)")
        calls = []
        monkeypatch.setattr(
            update.subprocess,
            "run",
            lambda cmd, **kw: calls.append(cmd) or MagicMock(returncode=0, stdout="[]"),
        )
        _removed, kept, notes = update._cleanup_runtimes()
        assert ["/bin/uv", "cache", "prune"] not in calls
        assert notes == ["Кеш uv не чищено — його тримає процес 5 (uv run uvicorn)"]
        assert kept == []

    def test_failed_python_list_is_reported(self, tmp_path, monkeypatch):
        from grunt_cli.commands import update

        self._home(tmp_path, monkeypatch)
        monkeypatch.setattr(update, "_in_use", dict)
        monkeypatch.setattr(update, "find_uv", lambda: "/shims/uv")
        monkeypatch.setattr(update, "get_mise_bin", lambda: None)
        monkeypatch.setattr(update, "_uv_cache_holders", lambda: "")
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if "list" in cmd:
                return MagicMock(
                    returncode=1, stdout="", stderr="mise ERROR No version is set for shim: uv\n"
                )
            return MagicMock(returncode=0, stdout="")

        monkeypatch.setattr(update.subprocess, "run", fake_run)
        removed, kept, notes = update._cleanup_runtimes()
        assert not [c for c in calls if c[1:3] == ["python", "uninstall"]]
        assert (removed, kept) == ([], [])
        assert notes == [
            "Python (uv) не чищено — uv python list: mise ERROR No version is set for shim: uv"
        ]

    def test_slow_cache_cleanup_is_skipped(self, monkeypatch):
        import subprocess as sp

        from grunt_cli.commands import update

        def slow(cmd, **kwargs):
            assert kwargs["timeout"] == update._CACHE_TIMEOUT
            raise sp.TimeoutExpired(cmd, kwargs["timeout"])

        monkeypatch.setattr(update.subprocess, "run", slow)
        update._quick(["/bin/npm", "cache", "verify"])  # не падає і не висить

    @patch("grunt_cli.commands.update._update_python_packages")
    @patch("grunt_cli.commands.update._run_npm_install")
    @patch("grunt_cli.commands.update._update_runtimes")
    @patch("grunt_cli.commands.update._run_migrations", return_value=True)
    @patch("grunt_cli.commands.update._get_cli_dir", return_value=None)
    @patch("grunt_cli.commands.update._find_apps_dir", return_value=None)
    @patch(
        "grunt_cli.commands.update._cleanup_runtimes",
        return_value=(
            ["uv 0.11.7 (mise)"],
            [
                "Python 3.14.4 (uv) — процес 42 (grunt serve, 6 дн) → kill 42",
                "Python 3.14.4 (uv) — uv tool deptry → uv tool install --reinstall deptry",
            ],
            [],
        ),
    )
    def test_summary_and_keep_old(
        self, cleanup, _apps, _cli, _migrate, _runtimes, _npm, _packages, runner
    ):
        result = runner.invoke(cli, ["update", "--no-upgrade-packages"])
        assert result.exit_code == 0, result.output
        cleanup.assert_called_once()
        tail = result.output.split("Оновлення завершено", 1)[1]
        assert "Видалено старі рантайми: uv 0.11.7 (mise)" in tail
        # назва рантайму — один раз, під нею кожен, хто його тримає
        assert tail.count("Python 3.14.4 (uv)") == 1
        assert "— процес 42 (grunt serve, 6 дн)" in tail and "звільнити: kill 42" in tail
        assert "— uv tool deptry" in tail
        assert "звільнити: uv tool install --reinstall deptry" in tail

        cleanup.reset_mock()
        assert runner.invoke(cli, ["update", "--keep-old", "--no-upgrade-packages"]).exit_code == 0
        cleanup.assert_not_called()


class TestQuietOutput:
    """`grunt update` hides subprocess chatter, keeping warnings and failure tails."""

    def test_success_shows_only_warnings(self, capsys):
        from grunt_cli import helpers

        script = (
            "print('Resolved 129 packages'); "
            "print('2026-10-13T12:48:08Z [info     ] registry.core_injected [x] name=User'); "
            "print('2026-10-13T12:48:08Z [warning  ] tasks.broker_initialized [x] reason=r'); "
            "print('2026-10-13T12:48:08Z [warning  ] registry.core_permissions_drifted "
            "[grunt.metadata.registry] name=Comment')"
        )
        assert helpers.run_captured([sys.executable, "-c", script]) == 0
        out = capsys.readouterr().out
        assert "Resolved" not in out
        assert "core_injected" not in out
        assert "broker_initialized" not in out
        assert "registry.core_permissions_drifted" in out and "name=Comment" in out

    def test_failure_shows_output_tail(self, capsys):
        from grunt_cli import helpers

        script = "import sys; print('boom: lock is stale'); sys.exit(3)"
        assert helpers.run_captured([sys.executable, "-c", script]) == 3
        assert "boom: lock is stale" in capsys.readouterr().out

    def test_verbose_passes_output_through(self, monkeypatch, capfd):
        from grunt_cli import helpers

        monkeypatch.setattr(helpers, "VERBOSE", True)
        assert helpers.run_captured([sys.executable, "-c", "print('Resolved 129')"]) == 0
        assert "Resolved 129" in capfd.readouterr().out


class TestUpgrade:
    def test_upgrade_help(self, runner):
        from grunt_cli.main import cli

        result = runner.invoke(cli, ["upgrade", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.output
        assert "--skip-runtimes" in result.output
        assert "--skip-packages" in result.output

    def test_update_upgrade_flag_help(self, runner):
        from grunt_cli.main import cli

        result = runner.invoke(cli, ["update", "--help"])
        assert result.exit_code == 0
        assert "--upgrade" in result.output

    def test_update_pyproject_deps(self, tmp_path):
        from grunt_cli.commands.upgrade import _update_pyproject_deps

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[project]\n"
            "dependencies = [\n"
            '    "fastapi>=0.111.0",\n'
            '    "uvicorn[standard]>=0.29.0",  # server\n'
            '    "click>=8.1.0",\n'
            "]\n"
        )

        locked = {
            "fastapi": "0.143.1",
            "uvicorn": "0.54.0",
            "click": "8.1.0",  # unchanged
        }

        changes = _update_pyproject_deps(pyproject, locked, dry_run=False)
        assert len(changes) == 2
        assert "fastapi: 0.111.0 → 0.143.1" in changes
        assert "uvicorn: 0.29.0 → 0.54.0" in changes

        new_text = pyproject.read_text()
        assert '"fastapi>=0.143.1",' in new_text
        assert '"uvicorn[standard]>=0.54.0",  # server' in new_text
        assert '"click>=8.1.0",' in new_text

    def test_update_mise_toml(self, tmp_path):
        from grunt_cli.commands.upgrade import _update_mise_toml

        mise_file = tmp_path / "mise.toml"
        mise_file.write_text('[tools]\nnode = "24"\npython = "3.14"\nuv = "latest"\n')

        changes = _update_mise_toml(mise_file, node_ver="26", python_ver="3.15", dry_run=False)
        assert len(changes) == 2
        assert "node: 24 → 26" in changes
        assert "python: 3.14 → 3.15" in changes

        new_text = mise_file.read_text()
        assert 'node = "26"' in new_text
        assert 'python = "3.15"' in new_text
        assert 'uv = "latest"' in new_text

    @patch("grunt_cli.commands.upgrade._cleanup_runtimes", return_value=([], [], []))
    @patch("grunt_cli.commands.upgrade._run_migrations", return_value=True)
    @patch("grunt_cli.commands.upgrade._upgrade_cli_itself")
    @patch("grunt_cli.commands.upgrade._upgrade_python_packages")
    @patch("grunt_cli.commands.upgrade._upgrade_node_packages")
    @patch("grunt_cli.commands.upgrade._upgrade_runtimes")
    def test_upgrade_dry_run_invokes_steps(
        self, mock_runtimes, mock_node, mock_py, mock_cli, _migrate, _cleanup, runner
    ):
        from grunt_cli.main import cli

        result = runner.invoke(cli, ["upgrade", "--dry-run"])
        assert result.exit_code == 0
        assert "Grunt Upgrade" in result.output
        mock_runtimes.assert_called_once_with(dry_run=True)
        mock_node.assert_called_once_with(dry_run=True)
        mock_py.assert_called_once_with(dry_run=True)
        mock_cli.assert_called_once_with(dry_run=True)
