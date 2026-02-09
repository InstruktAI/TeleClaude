"""Unit tests for teleclaude.cli.watch."""

from types import SimpleNamespace
from unittest.mock import patch

from teleclaude.cli.watch import SmartWatcher


def _event(src_path: str, *, event_type: str = "modified", dest_path: str | None = None) -> SimpleNamespace:
    payload = {"is_directory": False, "src_path": src_path, "event_type": event_type}
    if dest_path is not None:
        payload["dest_path"] = dest_path
    return SimpleNamespace(**payload)


def test_non_sync_path_does_not_trigger_sync(tmp_path):
    """Changes outside docs/artifact inputs should be ignored."""
    changed_file = tmp_path / "teleclaude" / "core" / "db.py"
    changed_file.parent.mkdir(parents=True)
    changed_file.write_text("x", encoding="utf-8")

    with (
        patch.object(SmartWatcher, "_load_gitignore", return_value=None),
        patch.object(SmartWatcher, "_sync") as mock_sync,
    ):
        watcher = SmartWatcher(project_root=tmp_path, debounce_seconds=0)
        assert mock_sync.call_count == 1  # initial sync

        watcher.on_any_event(_event(str(changed_file)))

        assert mock_sync.call_count == 1


def test_docs_path_triggers_sync(tmp_path):
    """Docs changes should trigger a sync run."""
    changed_file = tmp_path / "docs" / "global" / "policy.md"
    changed_file.parent.mkdir(parents=True)
    changed_file.write_text("x", encoding="utf-8")

    with (
        patch.object(SmartWatcher, "_load_gitignore", return_value=None),
        patch.object(SmartWatcher, "_sync") as mock_sync,
    ):
        watcher = SmartWatcher(project_root=tmp_path, debounce_seconds=0)
        assert mock_sync.call_count == 1  # initial sync

        watcher.on_any_event(_event(str(changed_file)))

        assert mock_sync.call_count == 2


def test_temp_file_under_docs_is_ignored(tmp_path):
    """Editor temp files should not trigger sync loops."""
    temp_file = tmp_path / "docs" / "global" / "policy.md.tmp.123"
    temp_file.parent.mkdir(parents=True)
    temp_file.write_text("x", encoding="utf-8")

    with (
        patch.object(SmartWatcher, "_load_gitignore", return_value=None),
        patch.object(SmartWatcher, "_sync") as mock_sync,
    ):
        watcher = SmartWatcher(project_root=tmp_path, debounce_seconds=0)
        assert mock_sync.call_count == 1  # initial sync

        watcher.on_any_event(_event(str(temp_file)))

        assert mock_sync.call_count == 1


def test_moved_event_uses_destination_path(tmp_path):
    """Moved files should be evaluated using destination path."""
    dest_file = tmp_path / "docs" / "global" / "policy.md"
    dest_file.parent.mkdir(parents=True)
    dest_file.write_text("x", encoding="utf-8")

    with (
        patch.object(SmartWatcher, "_load_gitignore", return_value=None),
        patch.object(SmartWatcher, "_sync") as mock_sync,
    ):
        watcher = SmartWatcher(project_root=tmp_path, debounce_seconds=0)
        assert mock_sync.call_count == 1  # initial sync

        watcher.on_any_event(_event(str(tmp_path / "tmpfile"), event_type="moved", dest_path=str(dest_file)))

        assert mock_sync.call_count == 2
