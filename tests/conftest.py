"""Shared test setup for grunt-cli."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_real_cleanup(request, monkeypatch):
    """`grunt update` ends by uninstalling unused Pythons and pruning mise —
    never against the real machine from a test (TestCleanup opts in)."""
    if request.node.get_closest_marker("real_cleanup"):
        return
    monkeypatch.setattr("grunt_cli.commands.update._cleanup_runtimes", lambda *_: ([], [], []))


@pytest.fixture(autouse=True)
def _no_real_os_check(request, monkeypatch):
    """`grunt update` asks apt (and sudo) about OS updates — never from a test
    (TestOsUpdates opts in and fakes the commands)."""
    if request.node.get_closest_marker("real_os_check"):
        return
    monkeypatch.setattr("grunt_cli.commands.update._check_os_updates", lambda: None)


@pytest.fixture(autouse=True)
def _update_state(tmp_path, monkeypatch):
    """Відбитки пропущених кроків `grunt update` — у тимчасовій теці тесту,
    не в ~/.cache користувача."""
    monkeypatch.setattr(
        "grunt_cli.commands.update._STATE_FILE", tmp_path / "update-state" / "state.json"
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "real_cleanup: run _cleanup_runtimes unpatched")
    config.addinivalue_line("markers", "real_os_check: run _check_os_updates unpatched")
