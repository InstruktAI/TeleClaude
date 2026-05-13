"""Contract tests for real user-turn transcript classification."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript._user_turns import (
    extract_real_user_text_from_entry,
    find_last_real_user_turn,
    find_turn_start_idx,
    is_real_user_turn_entry,
)

pytestmark = pytest.mark.unit


def test_claude_meta_checkpoint_does_not_reset_turn_boundary() -> None:
    entries = [
        {"timestamp": "2026-05-13T10:00:00Z", "message": {"role": "user", "content": "real prompt"}},
        {"message": {"role": "assistant", "content": [{"type": "tool_use", "name": "bash", "input": {}}]}},
        {
            "timestamp": "2026-05-13T10:01:00Z",
            "type": "user",
            "isMeta": True,
            "message": {"role": "user", "content": "Stop hook feedback:\ncheckpoint"},
        },
    ]

    assert is_real_user_turn_entry(entries[-1], AgentName.CLAUDE) is False
    assert find_turn_start_idx(entries, full_session=False, agent_name=AgentName.CLAUDE) == 1


def test_claude_task_notification_origin_does_not_reset_turn_boundary() -> None:
    entry = {
        "type": "user",
        "permissionMode": "bypassPermissions",
        "origin": {"kind": "task-notification"},
        "message": {
            "role": "user",
            "content": "<task-notification>\n<status>completed</status>\n</task-notification>",
        },
    }

    assert is_real_user_turn_entry(entry, AgentName.CLAUDE) is False
    assert extract_real_user_text_from_entry(entry, AgentName.CLAUDE) is None


def test_codex_hook_prompt_wrapper_does_not_reset_turn_boundary() -> None:
    entries = [
        {
            "timestamp": "2026-05-13T10:00:00Z",
            "type": "response_item",
            "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "real"}]},
        },
        {
            "timestamp": "2026-05-13T10:01:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": '<hook_prompt hook_run_id="stop:1">[TeleClaude Checkpoint] - verify</hook_prompt>',
                    }
                ],
            },
        },
    ]

    assert is_real_user_turn_entry(entries[-1], AgentName.CODEX) is False
    assert find_turn_start_idx(entries, full_session=False, agent_name=AgentName.CODEX) == 1


def test_gemini_teleclaude_notification_does_not_reset_turn_boundary() -> None:
    entries = [
        {"timestamp": "2026-04-02T03:38:18Z", "message": {"role": "user", "content": "real prompt"}},
        {
            "timestamp": "2026-04-02T03:45:45Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "[TeleClaude Notification]\n\n"
                            "Session bd9c6a26-4be7-4b33-81bd-e7efa3124683 finished its turn. "
                            "Use telec sessions tail bd9c6a26-4be7-4b33-81bd-e7efa3124683 to inspect."
                        ),
                    }
                ],
            },
        },
    ]

    turn = find_last_real_user_turn(entries, AgentName.GEMINI)

    assert turn is not None
    assert turn.entry_index == 0
    assert turn.text == "real prompt"
    assert turn.timestamp == datetime(2026, 4, 2, 3, 38, 18, tzinfo=UTC)


def test_gemini_real_user_prompt_counts_as_turn_boundary() -> None:
    entry = {"message": {"role": "user", "content": [{"type": "input_text", "text": "continue please"}]}}

    assert is_real_user_turn_entry(entry, AgentName.GEMINI) is True
    assert extract_real_user_text_from_entry(entry, AgentName.GEMINI) == "continue please"
