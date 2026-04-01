# guard: no-companion
"""Tests for telec todo artifacts {list|read|write} and telec todo stamp."""

# pylint: disable=missing-function-docstring,import-outside-toplevel
from __future__ import annotations

from unittest.mock import patch

import pytest

_MODULE = "teleclaude.cli.telec.handlers.todo"


class TestHandleTodoArtifactsList:
    """telec todo artifacts list <slug>."""

    def test_missing_slug_exits(self) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_artifacts

        with pytest.raises(SystemExit):
            _handle_todo_artifacts(["list"])

    def test_lists_names(self, capsys: pytest.CaptureFixture[str]) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_artifacts

        with patch(f"{_MODULE}.tool_api_request", return_value={"artifacts": ["input", "requirements"]}):
            _handle_todo_artifacts(["list", "my-slug"])

        output = capsys.readouterr().out
        assert "input" in output
        assert "requirements" in output


class TestHandleTodoArtifactsRead:
    """telec todo artifacts read <slug> <name>."""

    def test_missing_args_exits(self) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_artifacts

        with pytest.raises(SystemExit):
            _handle_todo_artifacts(["read", "my-slug"])

    def test_prints_content(self, capsys: pytest.CaptureFixture[str]) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_artifacts

        with patch(f"{_MODULE}.tool_api_request", return_value={"content": "artifact-content"}):
            _handle_todo_artifacts(["read", "my-slug", "requirements"])

        assert "artifact-content" in capsys.readouterr().out


class TestHandleTodoArtifactsWrite:
    """telec todo artifacts write <slug> <name> <content>."""

    def test_missing_args_exits(self) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_artifacts

        with pytest.raises(SystemExit):
            _handle_todo_artifacts(["write", "my-slug"])

    def test_writes_inline_content(self) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_artifacts

        with patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api:
            _handle_todo_artifacts(["write", "my-slug", "requirements", "inline-content"])

        mock_api.assert_called_once()
        body = mock_api.call_args[1].get("json_body") or mock_api.call_args[0][2]
        assert body["content"] == "inline-content"


class TestHandleTodoStamp:
    """telec todo stamp <slug> --verdict approve."""

    def test_missing_slug_exits(self) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_stamp

        with pytest.raises(SystemExit):
            _handle_todo_stamp([])

    def test_verdict_stamp(self) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_stamp

        with patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api:
            _handle_todo_stamp(["my-slug", "--verdict", "approve"])

        body = mock_api.call_args[1].get("json_body") or mock_api.call_args[0][2]
        assert body["stamp_type"] == "verdict"
        assert body["value"] == "approve"
