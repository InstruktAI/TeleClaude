"""Tests for telec todo dump/remove/split CLI handlers (DB-backed)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from teleclaude.cli.telec.handlers.todo import (
    _handle_todo_dump,
    _handle_todo_remove,
    _handle_todo_split,
)

_MODULE = "teleclaude.cli.telec.handlers.todo"


class TestHandleTodoDump:
    """telec todo dump <slug> <content>."""

    def test_success_prints_confirmation(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}),
            patch(f"{_MODULE}.EventEnvelope"),
        ):
            _handle_todo_dump(["my-slug", "my content"])

        assert "Dumped todo: my-slug" in capsys.readouterr().out

    def test_missing_args_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_dump(["only-slug"])

    def test_passes_after_deps(self) -> None:
        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api,
            patch(f"{_MODULE}.EventEnvelope"),
        ):
            _handle_todo_dump(["my-slug", "content", "--after", "dep-a,dep-b"])

        dump_call = mock_api.call_args_list[0]
        body = dump_call[1].get("json_body") or dump_call[0][2]
        assert body["after"] == ["dep-a", "dep-b"]

    def test_draft_skips_event_emission(self) -> None:
        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api,
        ):
            _handle_todo_dump(["my-slug", "content", "--draft"])

        # Only the POST /todos/dump call, no /events/emit call
        assert mock_api.call_count == 1
        assert mock_api.call_args_list[0][0][1] == "/todos/dump"

    def test_prepped_sends_kind_prepped(self) -> None:
        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api,
            patch(f"{_MODULE}.EventEnvelope"),
        ):
            _handle_todo_dump(["my-slug", "plan content", "--prepped"])

        dump_call = mock_api.call_args_list[0]
        body = dump_call[1].get("json_body") or dump_call[0][2]
        assert body["kind"] == "prepped"

    def test_prepped_still_emits_dumped_event(self) -> None:
        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api,
            patch(f"{_MODULE}.EventEnvelope"),
        ):
            _handle_todo_dump(["my-slug", "plan content", "--prepped"])

        # The dumped event must fire regardless of kind — subscribers (notifications,
        # dashboards, other cartridges) decide whether to act on it.
        paths = [call[0][1] for call in mock_api.call_args_list]
        assert "/todos/dump" in paths
        assert "/events/emit" in paths

    def test_prepped_defaults_kind_to_null_when_flag_absent(self) -> None:
        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}) as mock_api,
            patch(f"{_MODULE}.EventEnvelope"),
        ):
            _handle_todo_dump(["my-slug", "content"])

        dump_call = mock_api.call_args_list[0]
        body = dump_call[1].get("json_body") or dump_call[0][2]
        assert body["kind"] is None

    def test_prepped_confirmation_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}),
            patch(f"{_MODULE}.EventEnvelope"),
        ):
            _handle_todo_dump(["my-slug", "plan content", "--prepped"])

        out = capsys.readouterr().out
        assert "Dumped todo: my-slug" in out
        assert "prepped" in out


class TestHandleTodoRemove:
    """telec todo remove <slug>."""

    def test_success_prints_confirmation(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}):
            _handle_todo_remove(["my-slug"])

        assert "Removed todo: my-slug" in capsys.readouterr().out

    def test_missing_slug_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_remove([])


class TestHandleTodoSplit:
    """telec todo split <slug> --into <child>."""

    def test_success_prints_confirmation(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}):
            _handle_todo_split(["parent", "--into", "child-a", "--into", "child-b"])

        output = capsys.readouterr().out
        assert "child-a" in output
        assert "child-b" in output

    def test_missing_children_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_split(["parent"])
