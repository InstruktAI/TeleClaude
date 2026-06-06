"""Functional tests for todo management CLI request scoping."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from teleclaude.cli.telec.handlers import _todo_show
from teleclaude.cli.telec.handlers import todo as todo_handlers

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/todo-management"


@pytest.mark.spec(_SPEC, "UC-WM1")
def test_todo_show_sends_invocation_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    tool_api_request = MagicMock(return_value={"slug": "feature-x"})

    monkeypatch.setattr(_todo_show, "resolve_invocation_cwd", lambda: project_root, raising=False)
    monkeypatch.setattr(_todo_show, "tool_api_request", tool_api_request)

    _todo_show._handle_todo_show(["feature-x"])

    params = tool_api_request.call_args.kwargs["params"]
    assert Path(params["cwd"]) == project_root


@pytest.mark.spec(_SPEC, "UC-WM2")
def test_artifacts_list_sends_invocation_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    tool_api_request = MagicMock(return_value={"artifacts": ["prd"]})

    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: project_root)
    monkeypatch.setattr(todo_handlers, "tool_api_request", tool_api_request)

    todo_handlers._handle_artifacts_list(["feature-x"])

    params = tool_api_request.call_args.kwargs["params"]
    assert Path(params["cwd"]) == project_root


@pytest.mark.spec(_SPEC, "UC-WM3")
def test_artifacts_read_sends_invocation_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    tool_api_request = MagicMock(return_value={"content": "body"})

    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: project_root)
    monkeypatch.setattr(todo_handlers, "tool_api_request", tool_api_request)

    todo_handlers._handle_artifacts_read(["feature-x", "prd"])

    params = tool_api_request.call_args.kwargs["params"]
    assert Path(params["cwd"]) == project_root


@pytest.mark.spec(_SPEC, "UC-WM4")
def test_todo_reactivate_sends_invocation_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    tool_api_request = MagicMock(return_value={"slug": "feature-x"})

    monkeypatch.setattr(todo_handlers, "resolve_invocation_cwd", lambda: project_root)
    monkeypatch.setattr(todo_handlers, "tool_api_request", tool_api_request)

    todo_handlers._handle_todo_reactivate(["feature-x"])

    json_body = tool_api_request.call_args.kwargs["json_body"]
    assert Path(json_body["cwd"]) == project_root
