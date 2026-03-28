# guard: no-companion
# pyright: reportMissingImports=false, reportAttributeAccessIssue=false
"""Test spec (xfail) for todo watcher process behavior - R1.1, R1.6, R1.7.

Covers observation scope, batching/debounce, and the constraint that the
watcher performs no semantic processing. All tests are marked xfail.

Target module: the OS-managed watcher process entrypoint and its
batching/notification logic.
"""
# pylint: disable=import-outside-toplevel,missing-function-docstring

from __future__ import annotations

import asyncio

import pytest

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# R1.1 — Observation Scope
# ---------------------------------------------------------------------------


class TestObservationScope:
    """The watcher observes exactly one project root recursively."""

    def test_watcher_accepts_single_project_root(self) -> None:
        from teleclaude.services.todo_watcher import TodoWatcherProcess

        watcher = TodoWatcherProcess(project_root="/home/user/project")
        assert watcher.project_root == "/home/user/project"

    def test_watcher_observes_recursively(self) -> None:
        """The watcher must detect changes in subdirectories, not just top-level."""
        from teleclaude.services.todo_watcher import TodoWatcherProcess

        watcher = TodoWatcherProcess(project_root="/home/user/project")
        # The watcher's internal observer must be configured for recursive watching.
        # This is a structural assertion — the builder determines the mechanism.
        assert watcher.recursive is True


# ---------------------------------------------------------------------------
# R1.6 — Batching and Debounce
# ---------------------------------------------------------------------------


class TestBatchingAndDebounce:
    """Matching paths are accumulated over a debounce window and delivered as one notification."""

    async def test_multiple_events_coalesced_into_single_notification(self) -> None:
        """Two events within the debounce window produce exactly one notification."""
        from teleclaude.services.todo_watcher import TodoWatcherProcess

        notifications: list[object] = []
        watcher = TodoWatcherProcess(project_root="/project", debounce_seconds=0.05)

        async def capture_notification(payload: object) -> None:
            notifications.append(payload)

        watcher.on_notification = capture_notification

        # Simulate two rapid events
        watcher.handle_fs_event("todos/slug-a/state.yaml", event_type="modified")
        watcher.handle_fs_event("todos/slug-b/state.yaml", event_type="modified")

        # Wait for debounce window to flush
        await asyncio.sleep(0.15)

        assert len(notifications) == 1, "Expected exactly one coalesced notification"

    async def test_batch_contains_all_changed_paths(self) -> None:
        """The single notification includes all paths from the debounce window."""
        from teleclaude.services.todo_watcher import TodoWatcherProcess

        captured_paths: list[list[str]] = []
        watcher = TodoWatcherProcess(project_root="/project", debounce_seconds=0.05)

        async def capture(payload: object) -> None:
            captured_paths.append(payload.changed_paths)

        watcher.on_notification = capture

        watcher.handle_fs_event("todos/slug-a/state.yaml", event_type="modified")
        watcher.handle_fs_event("todos/slug-b/requirements.md", event_type="created")

        await asyncio.sleep(0.15)

        assert len(captured_paths) == 1
        batch = captured_paths[0]
        assert "todos/slug-a/state.yaml" in batch
        assert "todos/slug-b/requirements.md" in batch

    async def test_events_after_debounce_window_create_new_batch(self) -> None:
        """Events arriving after the debounce window fires get their own batch."""
        from teleclaude.services.todo_watcher import TodoWatcherProcess

        notifications: list[object] = []
        watcher = TodoWatcherProcess(project_root="/project", debounce_seconds=0.05)

        async def capture(payload: object) -> None:
            notifications.append(payload)

        watcher.on_notification = capture

        watcher.handle_fs_event("todos/slug-a/state.yaml", event_type="modified")
        await asyncio.sleep(0.15)  # First batch fires

        watcher.handle_fs_event("todos/slug-b/state.yaml", event_type="modified")
        await asyncio.sleep(0.15)  # Second batch fires

        assert len(notifications) == 2

    async def test_duplicate_paths_within_window_deduplicated(self) -> None:
        """The same path modified twice within a window appears once in the batch."""
        from teleclaude.services.todo_watcher import TodoWatcherProcess

        captured_paths: list[list[str]] = []
        watcher = TodoWatcherProcess(project_root="/project", debounce_seconds=0.05)

        async def capture(payload: object) -> None:
            captured_paths.append(payload.changed_paths)

        watcher.on_notification = capture

        watcher.handle_fs_event("todos/my-slug/state.yaml", event_type="modified")
        watcher.handle_fs_event("todos/my-slug/state.yaml", event_type="modified")

        await asyncio.sleep(0.15)

        assert len(captured_paths) == 1
        assert captured_paths[0].count("todos/my-slug/state.yaml") == 1


# ---------------------------------------------------------------------------
# R1.7 — No Semantic Processing
# ---------------------------------------------------------------------------


class TestNoSemanticProcessing:
    """The watcher never performs todo recomputation, snapshots, digests, or TUI work."""

    def test_notification_payload_contains_only_paths(self) -> None:
        """The notification sent to the daemon contains changed_paths and project_root only."""
        from teleclaude.services.todo_watcher import build_notification_payload

        payload = build_notification_payload(
            project_root="/home/user/project",
            changed_paths=["todos/my-slug/state.yaml"],
        )
        # Must contain project_root and changed_paths
        assert payload["project_root"] == "/home/user/project"
        assert payload["changed_paths"] == ["todos/my-slug/state.yaml"]
        # Must NOT contain semantic fields
        assert "snapshot" not in payload
        assert "digest" not in payload
        assert "todos" not in payload

    def test_watcher_does_not_import_cache_or_snapshot_modules(self) -> None:
        """The watcher process module must not depend on DaemonCache or snapshot assembly."""
        import importlib
        import sys

        before_import = set(sys.modules)

        # Import the watcher module to load its dependency tree
        importlib.import_module("teleclaude.services.todo_watcher")

        watcher_deps = {
            name for name in sys.modules if name.startswith("teleclaude.core.cache") and name not in before_import
        }

        assert "teleclaude.core.cache" not in watcher_deps, "Watcher process must not depend on DaemonCache"
