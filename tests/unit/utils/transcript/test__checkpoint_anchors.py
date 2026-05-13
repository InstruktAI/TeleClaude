"""Contract tests for checkpoint-compliance transcript anchors."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import teleclaude.utils.transcript._tool_calls as transcript_tool_calls
from teleclaude.core.agents import AgentName
from teleclaude.core.models import JsonDict
from teleclaude.utils.transcript._checkpoint_anchors import (
    find_checkpoint_scope_start_idx,
    is_checkpoint_anchor_entry,
)

pytestmark = pytest.mark.unit


def _codex_user_text(text: str, timestamp: str = "2026-05-13T10:00:00Z") -> JsonDict:
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": text}],
        },
    }


def _codex_call(command: str, call_id: str, timestamp: str) -> JsonDict:
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "exec_command",
            "call_id": call_id,
            "arguments": {"cmd": command},
        },
    }


def _codex_output(call_id: str) -> JsonDict:
    return {
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": "Process exited with code 0\nOutput:\nok",
        },
    }


def _stop_checkpoint(timestamp: str = "2026-05-13T10:01:00Z") -> JsonDict:
    return _codex_user_text(
        '<hook_prompt hook_run_id="stop:3:/Users/Morriz/.codex/hooks.json">'
        "[TeleClaude Checkpoint] - Context-aware checkpoint\n\n"
        "Required actions:\n1. Run tests"
        "</hook_prompt>",
        timestamp,
    )


def _claude_user_text(text: str, timestamp: str = "2026-05-13T10:01:00Z") -> JsonDict:
    return {
        "timestamp": timestamp,
        "type": "user",
        "message": {"role": "user", "content": text},
    }


def _gemini_user_text(text: str, timestamp: str = "2026-05-13T10:01:00Z") -> JsonDict:
    return {
        "timestamp": timestamp,
        "message": {"role": "user", "content": [{"type": "input_text", "text": text}]},
    }


def test_codex_stop_checkpoint_prompt_is_checkpoint_anchor() -> None:
    entry = _stop_checkpoint()

    assert is_checkpoint_anchor_entry(entry, AgentName.CODEX) is True


def test_claude_stop_hook_feedback_is_checkpoint_anchor() -> None:
    entry = _claude_user_text("Stop hook feedback:\n[TeleClaude Checkpoint] - Context-aware checkpoint")

    assert is_checkpoint_anchor_entry(entry, AgentName.CLAUDE) is True


def test_claude_pretool_feedback_is_not_checkpoint_anchor() -> None:
    entry = _claude_user_text("PreToolUse hook feedback:\n[TeleClaude Checkpoint] - Context-aware checkpoint")

    assert is_checkpoint_anchor_entry(entry, AgentName.CLAUDE) is False


def test_gemini_plain_checkpoint_prompt_is_checkpoint_anchor() -> None:
    entry = _gemini_user_text("[TeleClaude Checkpoint] - Context-aware checkpoint")

    assert is_checkpoint_anchor_entry(entry, AgentName.GEMINI) is True


def test_codex_non_stop_hook_prompt_is_not_checkpoint_anchor() -> None:
    entry = _codex_user_text(
        '<hook_prompt hook_run_id="pre_tool_use:3:/Users/Morriz/.codex/hooks.json">'
        "[TeleClaude Checkpoint] - Context-aware checkpoint"
        "</hook_prompt>"
    )

    assert is_checkpoint_anchor_entry(entry, AgentName.CODEX) is False


def test_codex_non_teleclaude_stop_hook_prompt_is_not_checkpoint_anchor() -> None:
    entry = _codex_user_text(
        '<hook_prompt hook_run_id="stop:3:/Users/Morriz/.codex/hooks.json">foreign hook output</hook_prompt>'
    )

    assert is_checkpoint_anchor_entry(entry, AgentName.CODEX) is False


def test_checkpoint_scope_start_uses_latest_stop_checkpoint_occurrence() -> None:
    entries = [
        _codex_user_text("real prompt", "2026-05-13T10:00:00Z"),
        _stop_checkpoint("2026-05-13T10:01:00Z"),
        _codex_call("instrukt-ai-logs teleclaude --since 2m", "call-old", "2026-05-13T10:01:20Z"),
        _codex_output("call-old"),
        _stop_checkpoint("2026-05-13T10:02:00Z"),
        _codex_call("pytest tests/unit/demo.py", "call-new", "2026-05-13T10:02:20Z"),
        _codex_output("call-new"),
    ]

    assert find_checkpoint_scope_start_idx(entries, full_session=False, agent_name=AgentName.CODEX) == 5


def test_checkpoint_scope_start_uses_newer_real_user_turn_after_checkpoint() -> None:
    entries = [
        _codex_user_text("first prompt", "2026-05-13T10:00:00Z"),
        _stop_checkpoint("2026-05-13T10:01:00Z"),
        _codex_call("pytest tests/unit/old.py", "call-old", "2026-05-13T10:01:20Z"),
        _codex_output("call-old"),
        _codex_user_text("new prompt", "2026-05-13T10:02:00Z"),
        _codex_call("pytest tests/unit/new.py", "call-new", "2026-05-13T10:02:20Z"),
        _codex_output("call-new"),
    ]

    assert find_checkpoint_scope_start_idx(entries, full_session=False, agent_name=AgentName.CODEX) == 5


def test_checkpoint_scope_extracts_evidence_after_latest_stop_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = [
        _codex_user_text("real prompt", "2026-05-13T10:00:00Z"),
        _codex_call("instrukt-ai-logs teleclaude --since 2m", "call-old", "2026-05-13T10:00:20Z"),
        _codex_output("call-old"),
        _stop_checkpoint("2026-05-13T10:01:00Z"),
        _codex_call("pytest tests/unit/demo.py", "call-new", "2026-05-13T10:01:20Z"),
        _codex_output("call-new"),
    ]
    monkeypatch.setattr(
        transcript_tool_calls,
        "_get_entries_for_agent",
        lambda transcript_path, agent_name, tail_entries=None: entries,
    )
    monkeypatch.setattr(transcript_tool_calls, "discover_codex_transcript_family_meta", lambda **kwargs: [])

    timeline = transcript_tool_calls.extract_effective_tool_calls(
        "/tmp/demo.jsonl",
        AgentName.CODEX,
        scope="checkpoint",
    )

    assert [record.input_data["cmd"] for record in timeline.tool_calls] == ["pytest tests/unit/demo.py"]
    assert timeline.turn_start_at == datetime(2026, 5, 13, 10, 1, tzinfo=UTC)


def test_checkpoint_scope_falls_back_to_real_user_when_no_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = [
        _codex_user_text("real prompt", "2026-05-13T10:00:00Z"),
        _codex_call("instrukt-ai-logs teleclaude --since 2m", "call-old", "2026-05-13T10:00:20Z"),
        _codex_output("call-old"),
    ]
    monkeypatch.setattr(
        transcript_tool_calls,
        "_get_entries_for_agent",
        lambda transcript_path, agent_name, tail_entries=None: entries,
    )
    monkeypatch.setattr(transcript_tool_calls, "discover_codex_transcript_family_meta", lambda **kwargs: [])

    timeline = transcript_tool_calls.extract_effective_tool_calls(
        "/tmp/demo.jsonl",
        AgentName.CODEX,
        scope="checkpoint",
    )

    assert [record.input_data["cmd"] for record in timeline.tool_calls] == ["instrukt-ai-logs teleclaude --since 2m"]
