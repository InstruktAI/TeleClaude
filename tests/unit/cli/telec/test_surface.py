"""CLI surface metadata tests."""

from __future__ import annotations

import importlib

surface = importlib.import_module("teleclaude.cli.telec.surface")


def test_cli_surface_exposes_expected_top_level_commands() -> None:
    for command in ("sessions", "todo", "docs", "roadmap", "auth", "signals"):
        assert command in surface.CLI_SURFACE


def test_sessions_revive_metadata_includes_attach_flag() -> None:
    revive = surface.CLI_SURFACE["sessions"].subcommands["revive"]

    assert revive.args == "<session_id>"
    assert [flag.long for flag in revive.flags] == ["--help", "--agent", "--attach"]


def test_todo_surface_does_not_expose_demo_subcommand() -> None:
    assert "demo" not in surface.CLI_SURFACE["todo"].subcommands


def test_hidden_commands_are_marked_hidden_in_surface() -> None:
    assert "watch" not in surface.CLI_SURFACE
