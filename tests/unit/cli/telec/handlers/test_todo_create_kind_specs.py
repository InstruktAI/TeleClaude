"""Test specs for telec todo create --kind flag.

Pins the requirement that:
- ``--kind`` is accepted by the CLI handler for all canonical kind values.
- ``--kind`` without a value or without the flag entirely exits with usage.
- Every accepted kind routes the correct ``kind`` field to the API.
"""

from __future__ import annotations

import pytest

from teleclaude.cli.telec.handlers.todo import _handle_todo_create
from teleclaude.types.todo_kind import (
    TODO_KIND_BUG,
    TODO_KIND_DRAFT,
    TODO_KIND_FEATURE,
    TODO_KIND_MIGRATION,
    TODO_KIND_PREPPED,
    TODO_KIND_REFACTOR,
    TODO_KIND_TODO,
)

pytestmark = [pytest.mark.unit]

_MODULE = "teleclaude.cli.telec.handlers.todo"
_SLUG = "my-slug"
_CONTENT = "Implement the feature"
_KIND_FLAG = "--kind"


def _capture_kind(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> str | None:
    captured: list[dict] = []
    monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
    monkeypatch.setattr(
        f"{_MODULE}.tool_api_request",
        lambda method, path, **kw: captured.append(kw.get("json_body", {})) or {"status": "ok"},
    )
    _handle_todo_create(args)
    assert captured, "No API request was made"
    return captured[0].get("kind")


class TestTodoCreateKindFlag:
    def test_kind_feature_routes_feature_to_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        kind = _capture_kind(monkeypatch, [_SLUG, _CONTENT, _KIND_FLAG, TODO_KIND_FEATURE])
        assert kind == TODO_KIND_FEATURE

    def test_kind_refactor_routes_refactor_to_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        kind = _capture_kind(monkeypatch, [_SLUG, _CONTENT, _KIND_FLAG, TODO_KIND_REFACTOR])
        assert kind == TODO_KIND_REFACTOR

    def test_kind_migration_routes_migration_to_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        kind = _capture_kind(monkeypatch, [_SLUG, _CONTENT, _KIND_FLAG, TODO_KIND_MIGRATION])
        assert kind == TODO_KIND_MIGRATION

    def test_kind_bug_routes_bug_to_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        kind = _capture_kind(monkeypatch, [_SLUG, _CONTENT, _KIND_FLAG, TODO_KIND_BUG])
        assert kind == TODO_KIND_BUG

    def test_kind_todo_routes_todo_to_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        kind = _capture_kind(monkeypatch, [_SLUG, _CONTENT, _KIND_FLAG, TODO_KIND_TODO])
        assert kind == TODO_KIND_TODO

    def test_kind_draft_routes_draft_to_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        kind = _capture_kind(monkeypatch, [_SLUG, _CONTENT, _KIND_FLAG, TODO_KIND_DRAFT])
        assert kind == TODO_KIND_DRAFT

    def test_kind_prepped_routes_prepped_to_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        kind = _capture_kind(monkeypatch, [_SLUG, _CONTENT, _KIND_FLAG, TODO_KIND_PREPPED])
        assert kind == TODO_KIND_PREPPED

    def test_invalid_kind_exits_with_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api_calls: list = []
        monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
        monkeypatch.setattr(
            f"{_MODULE}.tool_api_request",
            lambda *a, **kw: api_calls.append(a),
        )
        with pytest.raises(SystemExit):
            _handle_todo_create([_SLUG, _CONTENT, _KIND_FLAG, "invalid-kind"])
        assert not api_calls

    def test_omitted_kind_exits_without_api_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api_calls: list = []
        monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
        monkeypatch.setattr(
            f"{_MODULE}.tool_api_request",
            lambda *a, **kw: api_calls.append(a),
        )
        with pytest.raises(SystemExit):
            _handle_todo_create([_SLUG, _CONTENT])
        assert not api_calls

    def test_kind_flag_without_value_exits_with_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api_calls: list = []
        monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
        monkeypatch.setattr(
            f"{_MODULE}.tool_api_request",
            lambda *a, **kw: api_calls.append(a),
        )
        with pytest.raises(SystemExit):
            _handle_todo_create([_SLUG, _CONTENT, _KIND_FLAG])
        assert not api_calls
