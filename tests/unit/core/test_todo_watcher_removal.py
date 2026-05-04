"""Test spec (xfail) for daemon TodoWatcher removal — R5.1, R5.2.

Verifies that after migration the daemon performs no in-process filesystem
observation and that the old watcher code is removed. All tests are marked xfail.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

_REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# R5.1 — No Daemon-Owned File Observation
# ---------------------------------------------------------------------------


class TestNoDaemonFileObservation:
    """After migration, the daemon performs no filesystem observation for todos."""

    def test_daemon_does_not_create_todo_watcher_task(self) -> None:
        """The daemon startup must not create an asyncio task running TodoWatcher."""
        daemon_path = _REPO_ROOT / "teleclaude" / "daemon.py"
        source = daemon_path.read_text(encoding="utf-8")

        # The daemon must not instantiate or schedule TodoWatcher
        assert "TodoWatcher" not in source, (
            "daemon.py still references TodoWatcher — the in-process watcher must be removed"
        )

    def test_daemon_does_not_import_old_todo_watcher(self) -> None:
        """The daemon must not import from the old in-process todo_watcher module."""
        daemon_path = _REPO_ROOT / "teleclaude" / "daemon.py"
        source = daemon_path.read_text(encoding="utf-8")

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "todo_watcher" in node.module:
                    imported_names = [alias.name for alias in node.names]
                    assert "TodoWatcher" not in imported_names, (
                        "daemon.py still imports TodoWatcher from todo_watcher module"
                    )

    def test_daemon_does_not_schedule_todo_watcher_task(self) -> None:
        """The daemon must not create an asyncio task named 'todo-watcher'."""
        daemon_path = _REPO_ROOT / "teleclaude" / "daemon.py"
        source = daemon_path.read_text(encoding="utf-8")

        assert 'name="todo-watcher"' not in source, "daemon.py still schedules a task named 'todo-watcher'"


# ---------------------------------------------------------------------------
# R5.2 — Retirement of In-Process Watcher
# ---------------------------------------------------------------------------


class TestInProcessWatcherRemoval:
    """The current in-process watcher is removed entirely."""

    def test_todo_watcher_class_removed(self) -> None:
        """The TodoWatcher class that runs watchdog in-process must not exist."""
        todo_watcher_path = _REPO_ROOT / "teleclaude" / "core" / "todo_watcher.py"

        if not todo_watcher_path.exists():
            # Module entirely removed — requirement satisfied
            return

        source = todo_watcher_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        class_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        assert "TodoWatcher" not in class_names, (
            "teleclaude.core.todo_watcher still defines TodoWatcher class — the in-process watcher must be removed"
        )

    def test_todo_handler_class_removed(self) -> None:
        """The _TodoHandler FileSystemEventHandler must not exist."""
        todo_watcher_path = _REPO_ROOT / "teleclaude" / "core" / "todo_watcher.py"

        if not todo_watcher_path.exists():
            return

        source = todo_watcher_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        class_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        assert "_TodoHandler" not in class_names, (
            "teleclaude.core.todo_watcher still defines _TodoHandler — the in-process event handler must be removed"
        )

    def test_no_watchdog_import_in_todo_watcher_module(self) -> None:
        """If todo_watcher.py still exists, it must not import watchdog."""
        todo_watcher_path = _REPO_ROOT / "teleclaude" / "core" / "todo_watcher.py"

        if not todo_watcher_path.exists():
            return

        source = todo_watcher_path.read_text(encoding="utf-8")
        assert "from watchdog" not in source, "teleclaude.core.todo_watcher still imports watchdog"
        assert "import watchdog" not in source, "teleclaude.core.todo_watcher still imports watchdog"
