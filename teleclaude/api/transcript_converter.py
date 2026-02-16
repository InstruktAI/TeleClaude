"""Stateless converter: Claude JSONL transcript entries → AI SDK v5 UIMessage Stream SSE events.

Each function takes a JSONL entry dict and yields SSE-formatted strings
(``data: {json}\\n\\n``) conforming to the Vercel AI SDK UIMessage Stream v1 protocol.
"""

from __future__ import annotations

import json
import uuid
from typing import Iterator


def _sse_event(payload: dict[str, object]) -> str:  # guard: loose-dict - SSE payload
    """Format a single SSE data line."""
    return f"data: {json.dumps(payload)}\n\n"


def _make_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Top-level message lifecycle events
# ---------------------------------------------------------------------------


def message_start(message_id: str | None = None) -> str:
    """Emit ``start`` event opening a new assistant message."""
    return _sse_event({"type": "start", "messageId": message_id or _make_id()})


def message_finish(message_id: str | None = None) -> str:
    """Emit ``finish`` event closing the assistant message."""
    if message_id:
        return _sse_event({"type": "finish", "messageId": message_id})
    return _sse_event({"type": "finish"})


def stream_done() -> str:
    """Emit the terminal ``[DONE]`` sentinel."""
    return "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Text parts
# ---------------------------------------------------------------------------


def convert_text_block(block: dict[str, object]) -> Iterator[str]:  # guard: loose-dict
    """Convert a ``text`` or ``output_text`` JSONL block to SSE events.

    Yields: text-start, text-delta, text-end.
    """
    text = str(block.get("text", ""))
    part_id = _make_id()
    yield _sse_event({"type": "text-start", "id": part_id})
    if text:
        yield _sse_event({"type": "text-delta", "id": part_id, "delta": text})
    yield _sse_event({"type": "text-end", "id": part_id})


# ---------------------------------------------------------------------------
# Reasoning / thinking parts
# ---------------------------------------------------------------------------


def convert_thinking_block(block: dict[str, object]) -> Iterator[str]:  # guard: loose-dict
    """Convert a ``thinking`` JSONL block to SSE events.

    Yields: reasoning-start, reasoning-delta, reasoning-end.
    """
    thinking = str(block.get("thinking", ""))
    part_id = _make_id()
    yield _sse_event({"type": "reasoning-start", "id": part_id})
    if thinking:
        yield _sse_event({"type": "reasoning-delta", "id": part_id, "delta": thinking})
    yield _sse_event({"type": "reasoning-end", "id": part_id})


# ---------------------------------------------------------------------------
# Tool parts
# ---------------------------------------------------------------------------


def convert_tool_use_block(block: dict[str, object]) -> Iterator[str]:  # guard: loose-dict
    """Convert a ``tool_use`` JSONL block to SSE events.

    Yields: tool-input-start, tool-input-available (with complete input).
    """
    tool_name = str(block.get("name", "unknown"))
    tool_input = block.get("input", {})
    tool_call_id = str(block.get("id", _make_id()))

    yield _sse_event(
        {
            "type": "tool-input-start",
            "toolCallId": tool_call_id,
            "toolName": tool_name,
        }
    )
    yield _sse_event(
        {
            "type": "tool-input-available",
            "toolCallId": tool_call_id,
            "toolName": tool_name,
            "input": tool_input,
        }
    )


def convert_tool_result_block(block: dict[str, object]) -> Iterator[str]:  # guard: loose-dict
    """Convert a ``tool_result`` JSONL block to SSE events.

    Yields: tool-output-available.
    """
    tool_call_id = str(block.get("tool_use_id", _make_id()))
    content = block.get("content", "")
    is_error = bool(block.get("is_error", False))

    yield _sse_event(
        {
            "type": "tool-output-available",
            "toolCallId": tool_call_id,
            "output": content,
            "isError": is_error,
        }
    )


# ---------------------------------------------------------------------------
# Custom extension parts
# ---------------------------------------------------------------------------


def convert_send_result(data: object) -> str:
    """Emit ``data-send-result`` custom part for MCP send_result events."""
    return _sse_event({"type": "data-send-result", "data": data})


def convert_session_status(status: str, session_id: str) -> str:
    """Emit ``data-session-status`` custom part for session state changes."""
    return _sse_event(
        {
            "type": "data-session-status",
            "sessionId": session_id,
            "status": status,
        }
    )


# ---------------------------------------------------------------------------
# Entry-level dispatcher
# ---------------------------------------------------------------------------


def convert_entry(entry: dict[str, object]) -> Iterator[str]:  # guard: loose-dict
    """Convert a single JSONL transcript entry to zero or more SSE events.

    Dispatches on the entry's message content blocks. Entries without
    a recognized message structure are silently skipped.
    """
    message = entry.get("message")
    if not isinstance(message, dict):
        return

    role = message.get("role")
    content = message.get("content")

    # User messages with string content → skip (handled by message ingestion)
    if role == "user" and isinstance(content, str):
        return

    if not isinstance(content, list):
        return

    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")

        if block_type in ("text", "output_text"):
            yield from convert_text_block(block)
        elif block_type == "thinking":
            yield from convert_thinking_block(block)
        elif block_type == "tool_use":
            yield from convert_tool_use_block(block)
        elif block_type == "tool_result":
            yield from convert_tool_result_block(block)
