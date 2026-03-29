# guard: no-companion
"""Tests for telec todo read/write/stamp/artifacts CLI handlers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

_MODULE = "teleclaude.cli.telec.handlers.todo"


class TestHandleTodoRead:
    """telec todo read <slug> --artifact <name>."""

    def test_missing_slug_exits_with_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_read

        with pytest.raises(SystemExit, match="1"):
            _handle_todo_read([])
        assert "Usage" in capsys.readouterr().out

    def test_missing_artifact_flag_exits_with_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_read

        with pytest.raises(SystemExit, match="1"):
            _handle_todo_read(["my-slug"])
        assert "--artifact" in capsys.readouterr().out

    def test_calls_api_and_prints_content(self, capsys: pytest.CaptureFixture[str]) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_read

        with patch(f"{_MODULE}.tool_api_request", return_value={"content": "# Requirements\n\nHello."}) as mock_api:
            _handle_todo_read(["my-slug", "--artifact", "requirements"])

        mock_api.assert_called_once()
        call_args = mock_api.call_args
        assert call_args[0][0] == "GET"
        assert "/artifacts/my-slug/requirements" in call_args[0][1]
        assert "# Requirements" in capsys.readouterr().out


class TestHandleTodoWrite:
    """telec todo write <slug> --artifact <name> [--file <path>]."""

    def test_missing_slug_exits_with_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_write

        with pytest.raises(SystemExit, match="1"):
            _handle_todo_write([])

    def test_missing_artifact_flag_exits_with_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_write

        with pytest.raises(SystemExit, match="1"):
            _handle_todo_write(["my-slug"])

    def test_reads_file_and_posts_to_api(self, tmp_path: Path) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_write

        content_file = tmp_path / "req.md"
        content_file.write_text("new requirements content")

        with patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api:
            _handle_todo_write(["my-slug", "--artifact", "requirements", "--file", str(content_file)])

        mock_api.assert_called_once()
        call_args = mock_api.call_args
        assert call_args[0][0] == "POST"
        assert "new requirements content" in str(call_args[1].get("json_body") or call_args[0])


class TestHandleTodoStamp:
    """telec todo stamp <slug> --verdict approve."""

    def test_missing_slug_exits_with_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_stamp

        with pytest.raises(SystemExit, match="1"):
            _handle_todo_stamp([])

    def test_verdict_stamp_calls_api(self) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_stamp

        with patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api:
            _handle_todo_stamp(["my-slug", "--verdict", "approve"])

        mock_api.assert_called_once()
        body = mock_api.call_args[1].get("json_body") or mock_api.call_args[0][2]
        assert body["stamp_type"] == "verdict"
        assert body["value"] == "approve"


class TestHandleTodoArtifacts:
    """telec todo artifacts <slug>."""

    def test_missing_slug_exits_with_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_artifacts

        with pytest.raises(SystemExit, match="1"):
            _handle_todo_artifacts([])

    def test_lists_artifact_names(self, capsys: pytest.CaptureFixture[str]) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_artifacts

        with patch(f"{_MODULE}.tool_api_request", return_value={"artifacts": ["input", "requirements"]}) as mock_api:
            _handle_todo_artifacts(["my-slug"])

        output = capsys.readouterr().out
        assert "input" in output
        assert "requirements" in output
