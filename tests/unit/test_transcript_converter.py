"""Unit tests for the JSONL → SSE transcript converter."""

import json

from teleclaude.api.transcript_converter import (
    convert_entry,
    convert_send_result,
    convert_session_status,
    convert_text_block,
    convert_thinking_block,
    convert_tool_result_block,
    convert_tool_use_block,
    message_finish,
    message_start,
    stream_done,
)


def _parse_sse_events(raw: str | list[str]) -> list[dict[str, object]]:  # guard: loose-dict - test helper
    """Parse SSE event strings into dicts for assertion."""
    if isinstance(raw, list):
        raw = "".join(raw)
    results: list[dict[str, object]] = []  # guard: loose-dict - test helper
    for line in raw.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: ") and line != "data: [DONE]":
            payload = json.loads(line[6:])
            results.append(payload)
    return results


# ---------------------------------------------------------------------------
# Message lifecycle
# ---------------------------------------------------------------------------


def test_message_start_default_id():
    event = message_start()
    parsed = _parse_sse_events(event)
    assert len(parsed) == 1
    assert parsed[0]["type"] == "start"
    assert "messageId" in parsed[0]


def test_message_start_custom_id():
    event = message_start("custom-123")
    parsed = _parse_sse_events(event)
    assert parsed[0]["messageId"] == "custom-123"


def test_message_finish_no_id():
    event = message_finish()
    parsed = _parse_sse_events(event)
    assert parsed[0]["type"] == "finish"
    assert "messageId" not in parsed[0]


def test_message_finish_with_id():
    event = message_finish("msg-abc")
    parsed = _parse_sse_events(event)
    assert parsed[0]["type"] == "finish"
    assert parsed[0]["messageId"] == "msg-abc"


def test_stream_done():
    assert stream_done() == "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Text blocks
# ---------------------------------------------------------------------------


def test_convert_text_block():
    block = {"type": "text", "text": "Hello world"}
    events = list(convert_text_block(block))
    parsed = _parse_sse_events(events)
    assert len(parsed) == 3
    assert parsed[0]["type"] == "text-start"
    assert parsed[1]["type"] == "text-delta"
    assert parsed[1]["delta"] == "Hello world"
    assert parsed[2]["type"] == "text-end"
    # IDs should match across start/delta/end
    assert parsed[0]["id"] == parsed[1]["id"] == parsed[2]["id"]


def test_convert_text_block_empty():
    block = {"type": "text", "text": ""}
    events = list(convert_text_block(block))
    parsed = _parse_sse_events(events)
    # Should still emit start and end, but no delta with empty text
    assert len(parsed) == 2
    assert parsed[0]["type"] == "text-start"
    assert parsed[1]["type"] == "text-end"


def test_convert_output_text_block():
    block = {"type": "output_text", "text": "Codex output"}
    events = list(convert_text_block(block))
    parsed = _parse_sse_events(events)
    assert parsed[1]["type"] == "text-delta"
    assert parsed[1]["delta"] == "Codex output"


# ---------------------------------------------------------------------------
# Thinking / reasoning blocks
# ---------------------------------------------------------------------------


def test_convert_thinking_block():
    block = {"type": "thinking", "thinking": "Let me analyze this..."}
    events = list(convert_thinking_block(block))
    parsed = _parse_sse_events(events)
    assert len(parsed) == 3
    assert parsed[0]["type"] == "reasoning-start"
    assert parsed[1]["type"] == "reasoning-delta"
    assert parsed[1]["delta"] == "Let me analyze this..."
    assert parsed[2]["type"] == "reasoning-end"


def test_convert_thinking_block_empty():
    block = {"type": "thinking", "thinking": ""}
    events = list(convert_thinking_block(block))
    parsed = _parse_sse_events(events)
    assert len(parsed) == 2
    assert parsed[0]["type"] == "reasoning-start"
    assert parsed[1]["type"] == "reasoning-end"


# ---------------------------------------------------------------------------
# Tool blocks
# ---------------------------------------------------------------------------


def test_convert_tool_use_block():
    block = {"type": "tool_use", "id": "call_123", "name": "Read", "input": {"file_path": "/tmp/test.py"}}
    events = list(convert_tool_use_block(block))
    parsed = _parse_sse_events(events)
    assert len(parsed) == 2
    assert parsed[0]["type"] == "tool-input-start"
    assert parsed[0]["toolCallId"] == "call_123"
    assert parsed[0]["toolName"] == "Read"
    assert parsed[1]["type"] == "tool-input-available"
    assert parsed[1]["input"] == {"file_path": "/tmp/test.py"}


def test_convert_tool_result_block():
    block = {"type": "tool_result", "tool_use_id": "call_123", "content": "File contents here", "is_error": False}
    events = list(convert_tool_result_block(block))
    parsed = _parse_sse_events(events)
    assert len(parsed) == 1
    assert parsed[0]["type"] == "tool-output-available"
    assert parsed[0]["toolCallId"] == "call_123"
    assert parsed[0]["output"] == "File contents here"
    assert parsed[0]["isError"] is False


def test_convert_tool_result_error():
    block = {"type": "tool_result", "tool_use_id": "call_456", "content": "Permission denied", "is_error": True}
    events = list(convert_tool_result_block(block))
    parsed = _parse_sse_events(events)
    assert parsed[0]["isError"] is True


# ---------------------------------------------------------------------------
# Custom parts
# ---------------------------------------------------------------------------


def test_convert_send_result():
    event = convert_send_result({"url": "https://example.com"})
    parsed = _parse_sse_events(event)
    assert parsed[0]["type"] == "data-send-result"
    assert parsed[0]["data"] == {"url": "https://example.com"}


def test_convert_session_status():
    event = convert_session_status("streaming", "sess-abc")
    parsed = _parse_sse_events(event)
    assert parsed[0]["type"] == "data-session-status"
    assert parsed[0]["sessionId"] == "sess-abc"
    assert parsed[0]["status"] == "streaming"


# ---------------------------------------------------------------------------
# Entry-level dispatcher
# ---------------------------------------------------------------------------


def test_convert_entry_text_message():
    entry = {
        "type": "assistant",
        "timestamp": "2025-01-01T12:00:00Z",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello"}],
        },
    }
    events = list(convert_entry(entry))
    parsed = _parse_sse_events(events)
    types = [p["type"] for p in parsed]
    assert "text-start" in types
    assert "text-delta" in types
    assert "text-end" in types


def test_convert_entry_with_thinking_and_text():
    entry = {
        "message": {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "Analyzing..."},
                {"type": "text", "text": "Result"},
            ],
        },
    }
    events = list(convert_entry(entry))
    parsed = _parse_sse_events(events)
    types = [p["type"] for p in parsed]
    assert "reasoning-start" in types
    assert "reasoning-delta" in types
    assert "reasoning-end" in types
    assert "text-start" in types


def test_convert_entry_user_message_skipped():
    entry = {
        "message": {
            "role": "user",
            "content": "Hello, how are you?",
        },
    }
    events = list(convert_entry(entry))
    assert events == []


def test_convert_entry_no_message_skipped():
    entry = {"type": "summary"}
    events = list(convert_entry(entry))
    assert events == []


def test_convert_entry_tool_use_and_result():
    entry = {
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
            ],
        },
    }
    events = list(convert_entry(entry))
    parsed = _parse_sse_events(events)
    assert parsed[0]["type"] == "tool-input-start"
    assert parsed[1]["type"] == "tool-input-available"


# ---------------------------------------------------------------------------
# SSE format correctness
# ---------------------------------------------------------------------------


def test_sse_format_ends_with_double_newline():
    event = message_start("test")
    assert event.endswith("\n\n")


def test_sse_format_data_prefix():
    event = message_start("test")
    assert event.startswith("data: ")
