from __future__ import annotations

# guard: no-companion
import importlib
import sys
from types import SimpleNamespace

import pytest

surface = importlib.import_module("teleclaude.cli.telec.surface")
todo_handler = importlib.import_module("teleclaude.cli.telec.handlers.todo")

pytestmark = [
    pytest.mark.unit,
]


def test_todo_surface_exposes_state_subcommand_with_rewind_flag() -> None:
    state_command = surface.CLI_SURFACE["todo"].subcommands["state"]

    assert state_command.args == "<slug> [<transition>]"
    assert "--rewind" in [flag.long for flag in state_command.flags]


def test_handle_todo_routes_state_subcommand_to_tool_command_handler() -> None:
    received: list[list[str]] = []

    def _noop(_args: list[str]) -> None:
        return None

    def _capture(args: list[str]) -> None:
        received.append(args)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setitem(
            sys.modules,
            "teleclaude.cli.tool_commands",
            SimpleNamespace(
                handle_todo_create=_noop,
                handle_todo_integrate=_noop,
                handle_todo_mark_finalize_ready=_noop,
                handle_todo_mark_phase=_noop,
                handle_todo_prepare=_noop,
                handle_todo_set_deps=_noop,
                handle_todo_state=_capture,
                handle_todo_work=_noop,
            ),
        )

        todo_handler._handle_todo(["state", "sample-slug", "approve_requirements"])

    assert received == [["sample-slug", "approve_requirements"]]
