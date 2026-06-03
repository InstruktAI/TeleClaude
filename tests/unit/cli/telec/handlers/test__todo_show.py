"""Tests for the ``telec todo show`` handler."""

from __future__ import annotations

from typing import TypedDict

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.cli.telec.handlers._todo_show import _handle_todo_show

_SHOW_MODULE = "teleclaude.cli.telec.handlers._todo_show"
_TODO_SLUG = "my-slug"


class _ShowResponse(TypedDict, total=False):
    slug: str
    artifacts: list[str]
    artifact_content: dict[str, str]


def test_include_artifact_content_forwards_query_param(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    snapshot: SnapshotAssertion,
) -> None:
    captured: list[tuple[str, str, dict[str, str] | None]] = []

    def _request(method: str, path: str, **kwargs: object) -> _ShowResponse:
        params = kwargs.get("params")
        assert params is None or isinstance(params, dict)
        captured.append((method, path, params))
        return {"slug": _TODO_SLUG, "artifacts": [], "artifact_content": {}}

    monkeypatch.setattr(f"{_SHOW_MODULE}.tool_api_request", _request)

    _handle_todo_show([_TODO_SLUG, "--include-artifact-content"])

    assert captured == snapshot
    assert capsys.readouterr().out == snapshot


def test_default_show_omits_query_params(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    snapshot: SnapshotAssertion,
) -> None:
    captured: list[tuple[str, str, dict[str, str] | None]] = []

    def _request(method: str, path: str, **kwargs: object) -> _ShowResponse:
        params = kwargs.get("params")
        assert params is None or isinstance(params, dict)
        captured.append((method, path, params))
        return {"slug": _TODO_SLUG, "artifacts": []}

    monkeypatch.setattr(f"{_SHOW_MODULE}.tool_api_request", _request)

    _handle_todo_show([_TODO_SLUG])

    assert captured == snapshot
    assert capsys.readouterr().out == snapshot


def test_unknown_flag_exits_without_api_call(monkeypatch: pytest.MonkeyPatch) -> None:
    api_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(f"{_SHOW_MODULE}.tool_api_request", lambda method, path, **_: api_calls.append((method, path)))

    with pytest.raises(SystemExit):
        _handle_todo_show([_TODO_SLUG, "--bogus-flag"])

    assert not api_calls
