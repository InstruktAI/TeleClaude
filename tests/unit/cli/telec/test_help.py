from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

help_mod = importlib.import_module("teleclaude.cli.telec.help")
surface_types = importlib.import_module("teleclaude.cli.telec.surface_types")


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
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(help_mod, "_usage", lambda command, subcommand=None: f"{command}:{subcommand}")

    shown = help_mod._maybe_show_help("docs", ["get", "--help"])

    assert shown is True
    assert capsys.readouterr().out == "docs:get\n"


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
