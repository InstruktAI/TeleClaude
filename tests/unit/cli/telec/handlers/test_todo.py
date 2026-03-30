"""Tests for telec todo dump/remove/split CLI handlers (DB-backed)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

_MODULE = "teleclaude.cli.telec.handlers.todo"


class TestHandleTodoDump:
    """telec todo dump <slug> <content>."""

    def test_success_prints_confirmation(self, capsys: pytest.CaptureFixture[str]) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_dump

        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}),
            patch(f"{_MODULE}.EventEnvelope"),
        ):
            _handle_todo_dump(["my-slug", "my content"])

        assert "Dumped todo: my-slug" in capsys.readouterr().out

    def test_missing_args_exits(self) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_dump

        with pytest.raises(SystemExit):
            _handle_todo_dump(["only-slug"])

    def test_passes_after_deps(self) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_dump

        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api,
            patch(f"{_MODULE}.EventEnvelope"),
        ):
            _handle_todo_dump(["my-slug", "content", "--after", "dep-a,dep-b"])

        body = mock_api.call_args[1].get("json_body") or mock_api.call_args[0][2]
        assert body["after"] == ["dep-a", "dep-b"]


class TestHandleTodoRemove:
    """telec todo remove <slug>."""

    def test_success_prints_confirmation(self, capsys: pytest.CaptureFixture[str]) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_remove

        with patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}):
            _handle_todo_remove(["my-slug"])

        assert "Removed todo: my-slug" in capsys.readouterr().out

    def test_missing_slug_exits(self) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_remove

        with pytest.raises(SystemExit):
            _handle_todo_remove([])


class TestHandleTodoSplit:
    """telec todo split <slug> --into <child>."""

    def test_success_prints_confirmation(self, capsys: pytest.CaptureFixture[str]) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_split

        with patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}):
            _handle_todo_split(["parent", "--into", "child-a", "--into", "child-b"])

        output = capsys.readouterr().out
        assert "child-a" in output
        assert "child-b" in output

    def test_missing_children_exits(self) -> None:
        from teleclaude.cli.telec.handlers.todo import _handle_todo_split

        with pytest.raises(SystemExit):
            _handle_todo_split(["parent"])
