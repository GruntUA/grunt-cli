"""grunt upgrade, npm step: after ncu the package-lock.json must match package.json.

A stale lock often blocks upgrading packages one at a time (ERESOLVE: tiptap
extensions pin an exact peer on core) - the second attempt drops the upgraded
packages' lock entries; if that fails too, both files are restored.
"""

import json
from pathlib import Path
from unittest.mock import patch

from grunt_cli.commands import upgrade

OLD_PACKAGE = json.dumps({"dependencies": {"@tiptap/core": "^3.32.2", "lodash": "^4.17.0"}})
NEW_PACKAGE = json.dumps({"dependencies": {"@tiptap/core": "^3.33.0", "lodash": "^4.18.0"}})
UPGRADES = {"@tiptap/core": "^3.33.0", "lodash": "^4.18.0"}


def _lock() -> dict:
    return {
        "name": "app",
        "lockfileVersion": 3,
        "packages": {
            "": {"dependencies": {"@tiptap/core": "^3.32.2", "lodash": "^4.17.0"}},
            "node_modules/@tiptap/core": {"version": "3.32.2"},
            "node_modules/@tiptap/extension-bold": {"version": "3.32.2"},
            "node_modules/lodash": {"version": "4.17.0"},
            "node_modules/lodash-es": {"version": "4.17.0"},
            "node_modules/vue": {"version": "3.5.0"},
            "node_modules/vue/node_modules/@tiptap/pm": {"version": "3.32.2"},
        },
    }


def _project(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    (tmp_path / "package.json").write_text(OLD_PACKAGE)
    (tmp_path / "package-lock.json").write_text(json.dumps(_lock()))
    originals = upgrade._read_npm_manifests(tmp_path)
    (tmp_path / "package.json").write_text(NEW_PACKAGE)  # what ncu -u leaves
    return tmp_path, originals


def test_lock_groups_take_whole_scope():
    assert upgrade._lock_groups(UPGRADES) == {"@tiptap/", "lodash"}


def test_drop_lock_entries_removes_scope_and_exact_names(tmp_path):
    target, _ = _project(tmp_path)

    assert upgrade._drop_lock_entries(target, UPGRADES) == 4

    kept = json.loads((target / "package-lock.json").read_text())["packages"]
    assert sorted(kept) == ["", "node_modules/lodash-es", "node_modules/vue"]


def test_drop_lock_entries_without_lock(tmp_path):
    assert upgrade._drop_lock_entries(tmp_path, UPGRADES) == 0


def test_install_succeeds_first_time(tmp_path):
    target, originals = _project(tmp_path)

    with patch.object(upgrade, "run_captured", return_value=0) as run:
        assert upgrade._install_upgraded(target, UPGRADES, originals, [], "app") is True

    assert run.call_count == 1
    assert json.loads((target / "package-lock.json").read_text()) == _lock()


def test_install_retries_without_stale_lock_entries(tmp_path):
    target, originals = _project(tmp_path)
    locks_seen: list[dict] = []

    def npm(cmd, *, cwd, status):
        locks_seen.append(json.loads((Path(cwd) / "package-lock.json").read_text()))
        return 1 if len(locks_seen) == 1 else 0

    with patch.object(upgrade, "run_captured", side_effect=npm):
        assert upgrade._install_upgraded(target, UPGRADES, originals, [], "app") is True

    assert "node_modules/@tiptap/core" in locks_seen[0]["packages"]
    assert "node_modules/@tiptap/core" not in locks_seen[1]["packages"]
    assert (target / "package.json").read_text() == NEW_PACKAGE


def test_install_failure_restores_both_files(tmp_path):
    target, originals = _project(tmp_path)

    with patch.object(upgrade, "run_captured", return_value=1) as run:
        assert upgrade._install_upgraded(target, UPGRADES, originals, [], "app") is False

    assert run.call_count == 2
    assert (target / "package.json").read_text() == OLD_PACKAGE
    assert json.loads((target / "package-lock.json").read_text()) == _lock()
