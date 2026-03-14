"""Characterization tests for teleclaude.core.todo_watcher."""

from __future__ import annotations

import pytest

# Public API (TodoWatcher) requires a live watchdog Observer; testing pure
# helper functions _classify_event and _is_relevant pins the filtering logic
# without infrastructure.
from teleclaude.core.todo_watcher import _classify_event, _is_relevant


class _FakeEvent:
    def __init__(self, event_type: str, is_dir: bool = False):
        self.event_type = event_type
        self.is_directory = is_dir


class TestIsRelevant:
    @pytest.mark.unit
    def test_swp_file_not_relevant(self):
        assert _is_relevant("/project/todos/my-slug/state.yaml.swp") is False

    @pytest.mark.unit
    def test_tmp_file_not_relevant(self):
        assert _is_relevant("/project/todos/my-slug/file.tmp") is False

    @pytest.mark.unit
    def test_bak_file_not_relevant(self):
        assert _is_relevant("/project/todos/my-slug/file.bak") is False

    @pytest.mark.unit
    def test_hidden_path_not_relevant(self):
        assert _is_relevant("/project/.git/todos/state.yaml") is False

    @pytest.mark.unit
    def test_regular_yaml_is_relevant(self):
        assert _is_relevant("/project/todos/my-slug/state.yaml") is True

    @pytest.mark.unit
    def test_requirements_md_is_relevant(self):
        assert _is_relevant("/project/todos/my-slug/requirements.md") is True


class TestClassifyEvent:
    @pytest.mark.unit
    def test_created_returns_todo_created(self):
        event = _FakeEvent("created")
        assert _classify_event(event) == "todo_created"

    @pytest.mark.unit
    def test_deleted_returns_todo_removed(self):
        event = _FakeEvent("deleted")
        assert _classify_event(event) == "todo_removed"

    @pytest.mark.unit
    def test_modified_returns_todo_updated(self):
        event = _FakeEvent("modified")
        assert _classify_event(event) == "todo_updated"

    @pytest.mark.unit
    def test_moved_returns_todo_updated(self):
        event = _FakeEvent("moved")
        assert _classify_event(event) == "todo_updated"
