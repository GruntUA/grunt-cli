"""Shared test setup for grunt-cli."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_real_cleanup(request, monkeypatch):
    """`grunt update` ends by uninstalling unused Pythons and pruning mise —
    never against the real machine from a test (TestCleanup opts in)."""
    if request.node.get_closest_marker("real_cleanup"):
        return
    monkeypatch.setattr("grunt_cli.commands.update._cleanup_runtimes", lambda: ([], []))


def pytest_configure(config):
    config.addinivalue_line("markers", "real_cleanup: run _cleanup_runtimes unpatched")
