"""Tests for the canonical output projection route.

Covers:
- Task 2.5: allowlisted and suppressed tool visibility
- Task 3.1: web parity (history API vs. live SSE), tool leak regression
"""

from __future__ import annotations

import json
from typing import TypedDict, cast

from teleclaude.api.transcript_converter import convert_projected_block
from teleclaude.core.models import JsonValue
from teleclaude.output_projection.conversation_projector import project_entries
from teleclaude.output_projection.models import (
    PERMISSIVE_POLICY,
    THREADED_CLEAN_POLICY,
    WEB_POLICY,
    ProjectedBlock,
    VisibilityPolicy,
)
from teleclaude.output_projection.serializers import to_structured_message
from teleclaude.output_projection.terminal_live_projector import project_terminal_live


# ---------------------------------------------------------------------------
# Test entry builders
# ---------------------------------------------------------------------------


class TranscriptBlock(TypedDict, total=False):
    type: str
    text: str
    thinking: str
    id: str
    name: str
    input: dict[str, JsonValue]
    tool_use_id: str
    content: str


class TranscriptMessage(TypedDict):
    role: str
    content: list[TranscriptBlock]


class TranscriptEntry(TypedDict):
    type: str
    timestamp: str
    message: TranscriptMessage


class SseEvent(TypedDict, total=False):
    type: str
    delta: str
    toolName: str


def _text_entry(text: str = "Hello world", timestamp: str = "2025-01-01T12:00:00Z") -> TranscriptEntry:
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def _tool_use_entry(
    name: str = "Read",
    timestamp: str = "2025-01-01T12:00:00Z",
    tool_id: str = "call_123",
) -> TranscriptEntry:
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": name,
                    "input": {"file_path": "/tmp/test.py"},
                }
            ],
        },
    }


def _thinking_entry(thinking: str = "Let me think...", timestamp: str = "2025-01-01T12:00:00Z") -> TranscriptEntry:
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "message": {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": thinking}],
        },
    }


def _mixed_entry(timestamp: str = "2025-01-01T12:00:00Z") -> TranscriptEntry:
    """Entry with text, tool_use, and thinking blocks."""
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Here is my response"},
                {"type": "tool_use", "id": "call_abc", "name": "Read", "input": {}},
                {"type": "thinking", "thinking": "Internal reasoning"},
            ],
        },
    }


def _parse_sse_events(events: list[str]) -> list[SseEvent]:
    """Parse SSE event strings into event dicts for assertion."""
    result: list[SseEvent] = []
    for line in "".join(events).split("\n"):
        line = line.strip()
        if line.startswith("data: ") and line != "data: [DONE]":
            result.append(cast(SseEvent, json.loads(line[6:])))
    return result


# ---------------------------------------------------------------------------
# Visibility policy: WEB_POLICY filtering
# ---------------------------------------------------------------------------


def test_web_policy_suppresses_tool_use():
    blocks = list(project_entries([_tool_use_entry()], WEB_POLICY))
    assert blocks == []


def test_web_policy_suppresses_thinking():
    blocks = list(project_entries([_thinking_entry()], WEB_POLICY))
    assert blocks == []


def test_web_policy_passes_text():
    blocks = list(project_entries([_text_entry("Hi!")], WEB_POLICY))
    assert len(blocks) == 1
    assert blocks[0].block_type == "text"
    assert blocks[0].block["text"] == "Hi!"


def test_web_policy_filters_mixed_entry_to_text_only():
    blocks = list(project_entries([_mixed_entry()], WEB_POLICY))
    assert len(blocks) == 1
    assert blocks[0].block_type == "text"
    assert blocks[0].block["text"] == "Here is my response"


def test_permissive_policy_passes_all_block_types():
    blocks = list(project_entries([_mixed_entry()], PERMISSIVE_POLICY))
    block_types = {b.block_type for b in blocks}
    assert "text" in block_types
    assert "tool_use" in block_types
    assert "thinking" in block_types


# ---------------------------------------------------------------------------
# Task 2.5: Allowlist — explicitly visible tools
# ---------------------------------------------------------------------------


def test_allowlist_makes_named_tool_visible_when_include_tools_false():
    """Tool in visible_tool_names is emitted even with include_tools=False."""
    policy = VisibilityPolicy(
        include_tools=False,
        visible_tool_names=frozenset(["TodoWrite"]),
    )
    blocks = list(project_entries([_tool_use_entry(name="TodoWrite")], policy))
    assert len(blocks) == 1
    assert blocks[0].block_type == "tool_use"
    assert blocks[0].block["name"] == "TodoWrite"


def test_allowlist_suppresses_unlisted_tool_when_include_tools_false():
    """Tool NOT in visible_tool_names is suppressed when include_tools=False."""
    policy = VisibilityPolicy(
        include_tools=False,
        visible_tool_names=frozenset(["TodoWrite"]),
    )
    blocks = list(project_entries([_tool_use_entry(name="Read")], policy))
    assert blocks == []


def test_allowlist_web_policy_with_widget_tool_visible():
    """WEB_POLICY can be extended with visible_tool_names to surface specific widgets."""
    policy = VisibilityPolicy(
        include_tools=False,
        include_tool_results=False,
        include_thinking=False,
        visible_tool_names=frozenset(["send_result"]),
    )
    widget_entry = _tool_use_entry(name="send_result")
    internal_entry = _tool_use_entry(name="Read")
    blocks = list(project_entries([widget_entry, internal_entry], policy))
    assert len(blocks) == 1
    assert blocks[0].block["name"] == "send_result"


def test_allowlist_does_not_restrict_when_include_tools_true():
    """include_tools=True makes all tools visible regardless of allowlist."""
    policy = VisibilityPolicy(include_tools=True)
    blocks = list(project_entries([_tool_use_entry(name="AnyTool")], policy))
    assert len(blocks) == 1


# ---------------------------------------------------------------------------
# Task 3.1: Tool leak regression — internal tools must not surface in web chat
# ---------------------------------------------------------------------------


def test_tool_leak_regression_tool_use_suppressed_in_web_sse():
    """Regression: internal tool_use must not produce SSE tool events in web chat."""
    entries = [_tool_use_entry(name="Read")]
    sse_events: list[str] = []
    for pb in project_entries(entries, WEB_POLICY):
        sse_events.extend(list(convert_projected_block(pb)))

    parsed = _parse_sse_events(sse_events)
    tool_event_types = {e["type"] for e in parsed if "tool" in str(e.get("type", ""))}
    assert tool_event_types == set(), f"Internal tool events leaked into web SSE: {tool_event_types}"


def test_tool_leak_regression_thinking_suppressed_in_web_sse():
    """Regression: thinking blocks must not produce SSE reasoning events in web chat."""
    entries = [_thinking_entry("Private reasoning")]
    sse_events: list[str] = []
    for pb in project_entries(entries, WEB_POLICY):
        sse_events.extend(list(convert_projected_block(pb)))

    parsed = _parse_sse_events(sse_events)
    reasoning_types = {e["type"] for e in parsed if "reasoning" in str(e.get("type", ""))}
    assert reasoning_types == set(), f"Thinking blocks leaked into web SSE: {reasoning_types}"


# ---------------------------------------------------------------------------
# Task 3.1: Web parity — history API and live SSE see the same visible content
# ---------------------------------------------------------------------------


def test_web_parity_text_visible_in_both_history_and_sse_paths():
    """Same transcript entries yield the same visible text for both web output paths."""
    entries = [
        _text_entry("First response"),
        _tool_use_entry("Read"),      # suppressed by WEB_POLICY
        _thinking_entry("Reasoning"),  # suppressed by WEB_POLICY
        _text_entry("Second response"),
    ]

    # History API path: project_entries → to_structured_message
    history_texts = [
        to_structured_message(pb).text
        for pb in project_entries(entries, WEB_POLICY)
        if pb.block_type == "text"
    ]

    # Web SSE path: project_entries → convert_projected_block → extract deltas
    sse_deltas = []
    for pb in project_entries(entries, WEB_POLICY):
        for event in _parse_sse_events(list(convert_projected_block(pb))):
            if event.get("type") == "text-delta":
                sse_deltas.append(event["delta"])

    assert history_texts == sse_deltas == ["First response", "Second response"]


def test_web_parity_no_tools_in_either_path():
    """Neither history nor SSE exposes tool_use when WEB_POLICY is applied."""
    entries = [_tool_use_entry("Read"), _tool_use_entry("Write")]

    history_blocks = list(project_entries(entries, WEB_POLICY))
    assert history_blocks == []

    sse_events: list[str] = []
    for pb in project_entries(entries, WEB_POLICY):
        sse_events.extend(list(convert_projected_block(pb)))
    assert sse_events == []


# ---------------------------------------------------------------------------
# convert_projected_block serializer
# ---------------------------------------------------------------------------


def test_convert_projected_block_text_emits_start_delta_end():
    pb = ProjectedBlock(
        block_type="text",
        block={"type": "text", "text": "Hello"},
        role="assistant",
        timestamp=None,
        entry_index=0,
    )
    events = list(convert_projected_block(pb))
    parsed = _parse_sse_events(events)
    types = [e["type"] for e in parsed]
    assert types == ["text-start", "text-delta", "text-end"]
    assert parsed[1]["delta"] == "Hello"


def test_convert_projected_block_thinking_emits_reasoning_events():
    pb = ProjectedBlock(
        block_type="thinking",
        block={"type": "thinking", "thinking": "Reasoning text"},
        role="assistant",
        timestamp=None,
        entry_index=0,
    )
    events = list(convert_projected_block(pb))
    parsed = _parse_sse_events(events)
    assert parsed[0]["type"] == "reasoning-start"
    assert parsed[1]["type"] == "reasoning-delta"
    assert parsed[1]["delta"] == "Reasoning text"


def test_convert_projected_block_tool_use_emits_tool_events():
    pb = ProjectedBlock(
        block_type="tool_use",
        block={"type": "tool_use", "id": "call_1", "name": "Read", "input": {}},
        role="assistant",
        timestamp=None,
        entry_index=0,
    )
    events = list(convert_projected_block(pb))
    parsed = _parse_sse_events(events)
    assert parsed[0]["type"] == "tool-input-start"
    assert parsed[0]["toolName"] == "Read"


def test_convert_projected_block_compaction_emits_nothing():
    """Compaction blocks produce no SSE events (no web-visible content)."""
    pb = ProjectedBlock(
        block_type="compaction",
        block={"type": "compaction", "text": "Context compacted"},
        role="system",
        timestamp=None,
        entry_index=0,
    )
    events = list(convert_projected_block(pb))
    assert events == []


# ---------------------------------------------------------------------------
# to_structured_message serializer
# ---------------------------------------------------------------------------


def test_to_structured_message_text_block():
    pb = ProjectedBlock(
        block_type="text",
        block={"type": "text", "text": "Hello"},
        role="assistant",
        timestamp="2025-01-01T12:00:00Z",
        entry_index=0,
    )
    sm = to_structured_message(pb)
    assert sm.text == "Hello"
    assert sm.role == "assistant"
    assert sm.type == "text"
    assert sm.timestamp == "2025-01-01T12:00:00Z"


def test_to_structured_message_tool_use_block():
    pb = ProjectedBlock(
        block_type="tool_use",
        block={"type": "tool_use", "id": "c1", "name": "Read", "input": {"file_path": "/tmp/f.py"}},
        role="assistant",
        timestamp=None,
        entry_index=2,
    )
    sm = to_structured_message(pb)
    assert "Read" in sm.text
    assert sm.type == "tool_use"
    assert sm.entry_index == 2


def test_to_structured_message_thinking_block():
    pb = ProjectedBlock(
        block_type="thinking",
        block={"type": "thinking", "thinking": "reasoning here"},
        role="assistant",
        timestamp=None,
        entry_index=1,
    )
    sm = to_structured_message(pb)
    assert sm.text == "reasoning here"
    assert sm.type == "thinking"


# ---------------------------------------------------------------------------
# project_entries: since filter
# ---------------------------------------------------------------------------


def test_project_entries_since_filter_skips_old_entries():
    old = _text_entry("Old response", timestamp="2025-01-01T11:00:00Z")
    new = _text_entry("New response", timestamp="2025-01-01T13:00:00Z")
    blocks = list(project_entries([old, new], PERMISSIVE_POLICY, since="2025-01-01T12:00:00Z"))
    texts = [b.block["text"] for b in blocks if b.block_type == "text"]
    assert texts == ["New response"]


def test_project_entries_no_since_includes_all():
    blocks = list(project_entries([_text_entry("A"), _text_entry("B")], PERMISSIVE_POLICY))
    assert len(blocks) == 2


# ---------------------------------------------------------------------------
# THREADED_CLEAN_POLICY: confirms includes tools but not tool results
# ---------------------------------------------------------------------------


def test_threaded_clean_policy_includes_text_and_tool_use():
    entries = [_text_entry("Hello"), _tool_use_entry("Bash"), _thinking_entry("Thinking...")]
    blocks = list(project_entries(entries, THREADED_CLEAN_POLICY))
    block_types = {b.block_type for b in blocks}
    assert "text" in block_types
    assert "tool_use" in block_types
    assert "thinking" in block_types


def test_threaded_clean_policy_suppresses_tool_results():
    entry: TranscriptEntry = {
        "type": "user",
        "timestamp": "2025-01-01T12:00:00Z",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "result text"}],
        },
    }
    blocks = list(project_entries([entry], THREADED_CLEAN_POLICY))
    tool_result_blocks = [b for b in blocks if b.block_type == "tool_result"]
    assert tool_result_blocks == []


# ---------------------------------------------------------------------------
# Terminal live projection (Task 3.3 protection)
# ---------------------------------------------------------------------------


def test_project_terminal_live_preserves_output():
    text = "session active\n> cursor"
    result = project_terminal_live(text)
    assert result.output == text


def test_project_terminal_live_empty_string():
    result = project_terminal_live("")
    assert result.output == ""


def test_project_terminal_live_multiline_preserves_content():
    text = "line1\nline2\n  indented\n"
    result = project_terminal_live(text)
    assert result.output == text


# ---------------------------------------------------------------------------
# C-1: Input sanitization — TELECLAUDE_SYSTEM_PREFIX and internal wrappers
# ---------------------------------------------------------------------------


def _user_text_entry(text: str, timestamp: str = "2025-01-01T12:00:00Z") -> TranscriptEntry:
    """Build a user text entry with plain string content."""
    return {
        "type": "user",
        "timestamp": timestamp,
        "message": {
            "role": "user",
            "content": text,  # type: ignore[typeddict-item]
        },
    }


def _user_block_text_entry(text: str, timestamp: str = "2025-01-01T12:00:00Z") -> TranscriptEntry:
    """Build a user text entry with block-based content."""
    return {
        "type": "user",
        "timestamp": timestamp,
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    }


def test_sanitize_teleclaude_system_prefix_string_content():
    """User string messages starting with TELECLAUDE_SYSTEM_PREFIX are stripped."""
    entry = _user_text_entry("[TeleClaude Checkpoint] - Context-aware checkpoint")
    blocks = list(project_entries([entry], PERMISSIVE_POLICY))
    assert blocks == []


def test_sanitize_teleclaude_system_prefix_block_content():
    """User block-based text starting with TELECLAUDE_SYSTEM_PREFIX is stripped."""
    entry = _user_block_text_entry("[TeleClaude Direct Conversation]\nSome internal text")
    blocks = list(project_entries([entry], PERMISSIVE_POLICY))
    assert blocks == []


def test_sanitize_task_notification_wrapper():
    """Pure <task-notification> user text is stripped."""
    entry = _user_text_entry("<task-notification>Worker stopped</task-notification>")
    blocks = list(project_entries([entry], PERMISSIVE_POLICY))
    assert blocks == []


def test_sanitize_system_reminder_wrapper():
    """Pure <system-reminder> user text is stripped."""
    entry = _user_text_entry("<system-reminder>Some internal reminder content</system-reminder>")
    blocks = list(project_entries([entry], PERMISSIVE_POLICY))
    assert blocks == []


def test_sanitize_preserves_normal_user_text():
    """Normal user text is NOT stripped."""
    entry = _user_text_entry("Hello, how are you?")
    blocks = list(project_entries([entry], PERMISSIVE_POLICY))
    assert len(blocks) == 1
    assert blocks[0].block_type == "text"
    assert blocks[0].role == "user"
    assert blocks[0].block["text"] == "Hello, how are you?"


def test_sanitize_preserves_normal_user_block_text():
    """Normal user block-based text is NOT stripped."""
    entry = _user_block_text_entry("What is the weather today?")
    blocks = list(project_entries([entry], PERMISSIVE_POLICY))
    assert len(blocks) == 1
    assert blocks[0].block_type == "text"
    assert blocks[0].role == "user"


def test_sanitize_drops_empty_user_message_after_stripping():
    """User messages emptied by sanitization produce no blocks (SC#5)."""
    entries = [
        _user_text_entry("[TeleClaude Worker Stopped]"),
        _text_entry("Assistant response after checkpoint"),
    ]
    blocks = list(project_entries(entries, PERMISSIVE_POLICY))
    assert len(blocks) == 1
    assert blocks[0].role == "assistant"


# ---------------------------------------------------------------------------
# I-3: System-role block-based entries are dropped (not coerced)
# ---------------------------------------------------------------------------


def test_system_role_block_entries_are_dropped():
    """System-role entries with block-based content should be skipped entirely."""
    entry: TranscriptEntry = {
        "type": "system",
        "timestamp": "2025-01-01T12:00:00Z",
        "message": {
            "role": "system",
            "content": [{"type": "text", "text": "System message with blocks"}],
        },
    }
    blocks = list(project_entries([entry], PERMISSIVE_POLICY))
    assert blocks == []


# ---------------------------------------------------------------------------
# I-5: project_conversation_chain direct tests
# ---------------------------------------------------------------------------


def test_project_conversation_chain_multi_file(tmp_path):
    """Multi-file chain yields blocks with correct file_index propagation."""
    import json as _json

    from teleclaude.output_projection.conversation_projector import project_conversation_chain

    for file_idx in range(2):
        file_path = tmp_path / f"transcript_{file_idx}.jsonl"
        entry = {
            "type": "assistant",
            "timestamp": f"2025-01-01T1{file_idx}:00:00Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": f"Response from file {file_idx}"}],
            },
        }
        file_path.write_text(_json.dumps(entry) + "\n")

    file_paths = [str(tmp_path / f"transcript_{i}.jsonl") for i in range(2)]
    blocks = project_conversation_chain(file_paths, "claude", PERMISSIVE_POLICY)

    assert len(blocks) == 2
    assert blocks[0].file_index == 0
    assert blocks[1].file_index == 1
    assert blocks[0].block["text"] == "Response from file 0"
    assert blocks[1].block["text"] == "Response from file 1"


def test_project_conversation_chain_skips_missing_files(tmp_path):
    """Non-existent files in the chain are skipped without error."""
    import json as _json

    from teleclaude.output_projection.conversation_projector import project_conversation_chain

    real_file = tmp_path / "transcript_0.jsonl"
    entry = {
        "type": "assistant",
        "timestamp": "2025-01-01T12:00:00Z",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "Only real file"}],
        },
    }
    real_file.write_text(_json.dumps(entry) + "\n")

    file_paths = [
        str(tmp_path / "nonexistent.jsonl"),
        str(real_file),
    ]
    blocks = project_conversation_chain(file_paths, "claude", PERMISSIVE_POLICY)

    assert len(blocks) == 1
    assert blocks[0].file_index == 1
    assert blocks[0].block["text"] == "Only real file"


# ---------------------------------------------------------------------------
# I-6: User text messages (plain string content) path
# ---------------------------------------------------------------------------


def test_user_string_content_yields_text_block():
    """User messages with plain string content yield a text ProjectedBlock."""
    entry = _user_text_entry("Can you help me?")
    blocks = list(project_entries([entry], PERMISSIVE_POLICY))
    assert len(blocks) == 1
    assert blocks[0].block_type == "text"
    assert blocks[0].role == "user"
    assert blocks[0].block == {"type": "text", "text": "Can you help me?"}
