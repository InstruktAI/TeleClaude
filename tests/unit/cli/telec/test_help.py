from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

help_mod = importlib.import_module("teleclaude.cli.telec.help")
surface_mod = importlib.import_module("teleclaude.cli.telec.surface")
surface_types = importlib.import_module("teleclaude.cli.telec.surface_types")


def _run_completion(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    comp_line: str,
) -> list[str]:
    """Invoke _handle_completion with COMP_LINE and return non-empty stdout rows."""
    monkeypatch.setenv("COMP_LINE", comp_line)
    monkeypatch.setenv("COMP_POINT", str(len(comp_line)))
    help_mod._handle_completion()
    return [line for line in capsys.readouterr().out.splitlines() if line]


def _completion_values(rows: list[str]) -> list[str]:
    """Return the insertable value column (text before the first tab) of each row."""
    return [row.split("\t", 1)[0] for row in rows]


_SMOKE_COMMANDS = sorted(
    name
    for name, cmd_def in surface_mod.CLI_SURFACE.items()
    if not cmd_def.hidden and (cmd_def.subcommands or cmd_def.flags)
)


def test_sample_positional_value_uses_domain_specific_examples() -> None:
    assert help_mod._sample_positional_value("<email>") == "person@example.com"
    assert help_mod._sample_positional_value("<session_id>") == "sess-123"
    assert help_mod._sample_positional_value("<slug>") == "my-slug"


def test_example_commands_include_positional_and_flag_values() -> None:
    examples = help_mod._example_commands(
        ["sessions", "start"],
        "--project <path>",
        [surface_types.Flag("--agent", desc="Agent: claude, gemini, codex")],
    )

    assert examples[0] == "telec sessions start /tmp/example.txt"
    assert examples[1] == "telec sessions start /tmp/example.txt --agent claude"


def test_maybe_show_help_prints_leaf_usage_when_help_follows_subcommand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shown = help_mod._maybe_show_help("docs", ["get", "--help"])

    assert shown is True
    out = capsys.readouterr().out
    assert "telec docs get" in out
    assert "Fetch full snippet content by ID" in out


def test_maybe_show_help_resolves_nested_subcommands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shown = help_mod._maybe_show_help("config", ["people", "add", "-h"])

    assert shown is True
    out = capsys.readouterr().out
    assert "telec config people add" in out
    assert "Add a person" in out


def test_maybe_show_help_resolves_intermediate_node(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shown = help_mod._maybe_show_help("config", ["people", "-h"])

    assert shown is True
    out = capsys.readouterr().out
    assert "telec config people list" in out
    assert "telec config people add" in out


def test_complete_flags_only_prints_matching_unused_options(monkeypatch: pytest.MonkeyPatch) -> None:
    printed = MagicMock()

    monkeypatch.setattr(help_mod, "_print_flag", printed)

    help_mod._complete_flags(
        [("-a", "--agent", "Agent"), ("-m", "--mode", "Mode")],
        ["--agent"],
        "--m",
        True,
    )

    printed.assert_called_once_with(("-m", "--mode", "Mode"))


@pytest.mark.parametrize("command", _SMOKE_COMMANDS)
def test_handle_completion_emits_rows_for_every_surface_command(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Smoke guard: every non-hidden command with content must produce completions."""
    rows = _run_completion(monkeypatch, capsys, f"telec {command} ")

    assert rows, f"telec {command} <TAB> emitted no completion rows"


def test_handle_completion_emits_history_subcommands(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    values = _completion_values(_run_completion(monkeypatch, capsys, "telec history "))

    assert {"list", "search", "show"} <= set(values)


def test_handle_completion_walks_nested_container_todo_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    values = _completion_values(_run_completion(monkeypatch, capsys, "telec todo artifacts "))

    assert {"list", "read", "write"} <= set(values)


def test_handle_completion_walks_nested_container_config_people(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    values = _completion_values(_run_completion(monkeypatch, capsys, "telec config people "))

    assert {"list", "add", "edit", "remove"} <= set(values)


def test_handle_completion_walks_nested_container_config_env(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    values = _completion_values(_run_completion(monkeypatch, capsys, "telec config env "))

    assert {"list", "set"} <= set(values)


def test_handle_completion_ignores_flag_like_text_inside_quoted_positional(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Flag-like substrings inside a quoted positional must not be marked as used."""
    values = _completion_values(_run_completion(monkeypatch, capsys, 'telec content dump "text --author val" '))

    assert any("--author" in v for v in values), (
        "--author was inside quoted positional and must still be offered as a flag"
    )
