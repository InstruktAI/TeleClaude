from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

history = importlib.import_module("teleclaude.cli.telec.handlers.history")


def test_handle_history_without_args_prints_usage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(history, "_usage", lambda *args: f"usage:{'/'.join(args)}")

    history._handle_history([])

    assert capsys.readouterr().out == "usage:history\n"


def test_handle_history_unknown_subcommand_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(history, "_usage", lambda *args: f"usage:{'/'.join(args)}")

    with pytest.raises(SystemExit) as exc_info:
        history._handle_history(["bad-subcommand"])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "Unknown history subcommand: bad-subcommand" in output
    assert "usage:history" in output


def test_handle_history_search_parses_flags_and_delegates() -> None:
    calls: list[tuple[list[str], str, int, list[str] | None]] = []

    fake_search = SimpleNamespace(
        parse_agents=lambda agent_arg: ["parsed", agent_arg],
        display_combined_history=lambda agents, *, search_term, limit, computers: calls.append(
            (agents, search_term, limit, computers)
        ),
    )

    with patch.dict(sys.modules, {"teleclaude.history.search": fake_search}):
        history._handle_history_search(
            ["error", "budget", "--agent", "claude,codex", "--limit", "15", "--computer", "work", "home"]
        )

    assert calls == [(["parsed", "claude,codex"], "error budget", 15, ["work", "home"])]


def test_handle_history_search_requires_terms(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(history, "_usage", lambda *args: f"usage:{'/'.join(args)}")

    with pytest.raises(SystemExit) as exc_info:
        history._handle_history_search(["--agent", "claude"])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "usage:history/search" in output


def test_handle_history_search_rejects_invalid_limit(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        history._handle_history_search(["--limit", "not-a-number", "needle"])

    assert exc_info.value.code == 1
    assert "Invalid value for --limit: not-a-number" in capsys.readouterr().out


def test_handle_history_show_parses_flags_and_delegates() -> None:
    calls: list[tuple[list[str], str, int, bool, bool, list[str]]] = []

    fake_search = SimpleNamespace(
        parse_agents=lambda agent_arg: ["parsed", agent_arg],
        show_transcript=lambda agents, session_id, *, tail_chars, include_thinking, raw, computers: calls.append(
            (agents, session_id, tail_chars, include_thinking, raw, computers)
        ),
    )

    with patch.dict(sys.modules, {"teleclaude.history.search": fake_search}):
        history._handle_history_show(
            ["session-123", "--agent", "codex", "--thinking", "--raw", "--tail", "120", "--computer", "workstation"]
        )

    assert calls == [(["parsed", "codex"], "session-123", 120, True, True, ["workstation"])]


def test_handle_history_show_rejects_extra_positional(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(history, "_usage", lambda *args: f"usage:{'/'.join(args)}")

    with patch.dict(
        sys.modules,
        {
            "teleclaude.history.search": SimpleNamespace(
                parse_agents=lambda _agent_arg: ["all"], show_transcript=lambda *a, **k: None
            )
        },
    ):
        with pytest.raises(SystemExit) as exc_info:
            history._handle_history_show(["session-123", "extra"])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "Unexpected positional argument: extra" in output
    assert "usage:history/show" in output


def test_handle_history_show_requires_session_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(history, "_usage", lambda *args: f"usage:{'/'.join(args)}")

    with patch.dict(
        sys.modules,
        {
            "teleclaude.history.search": SimpleNamespace(
                parse_agents=lambda _agent_arg: ["all"], show_transcript=lambda *a, **k: None
            )
        },
    ):
        with pytest.raises(SystemExit) as exc_info:
            history._handle_history_show(["--thinking"])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "usage:history/show" in output


def test_handle_history_show_rejects_invalid_tail(capsys: pytest.CaptureFixture[str]) -> None:
    with patch.dict(
        sys.modules,
        {
            "teleclaude.history.search": SimpleNamespace(
                parse_agents=lambda _agent_arg: ["all"], show_transcript=lambda *a, **k: None
            )
        },
    ):
        with pytest.raises(SystemExit) as exc_info:
            history._handle_history_show(["--tail", "oops", "session-123"])

    assert exc_info.value.code == 1
    assert "Invalid value for --tail: oops" in capsys.readouterr().out
