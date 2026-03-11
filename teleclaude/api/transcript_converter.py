"""Stateless serializer: projected output blocks → AI SDK v5 UIMessage Stream SSE events.

Block-level converters (convert_text_block, convert_thinking_block, etc.) accept
already-projected block dicts. convert_projected_block() is the canonical entry
point for downstream SSE serialization after visibility policy has been applied
by the shared output_projection route.

convert_entry() is preserved for backward compatibility and operates independently
of the projection layer, emitting all assistant content blocks directly. Callers
that want visibility filtering should use project_entries(WEB_POLICY) +
convert_projected_block() instead (as _stream_sse() does after the cutover).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING

from teleclaude.utils.transcript import normalize_transcript_entry_message

if TYPE_CHECKING:
    from teleclaude.output_projection.models import ProjectedBlock


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


def convert_text_block(block: Mapping[str, object]) -> Iterator[str]:
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


def convert_thinking_block(block: Mapping[str, object]) -> Iterator[str]:
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


def convert_tool_use_block(block: Mapping[str, object]) -> Iterator[str]:
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


def convert_tool_result_block(block: Mapping[str, object]) -> Iterator[str]:
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
    """Emit ``data-send-result`` custom part for send_result events."""
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
# Projected block serializer (canonical SSE entry point)
# ---------------------------------------------------------------------------


def convert_projected_block(projected: ProjectedBlock) -> Iterator[str]:
    """Convert a projected block to SSE events.

    The visibility policy has already been applied by the projector — this
    function only handles serialization. Callers should use
    project_entries(WEB_POLICY) + convert_projected_block() for filtered output.

    Args:
        projected: A visibility-filtered ProjectedBlock from the projection route.

    Yields:
        SSE-formatted strings conforming to AI SDK v5 UIMessage Stream protocol.
    """
    block_type = projected.block_type
    block = projected.block

    if block_type == "text":
        yield from convert_text_block(block)
    elif block_type == "thinking":
        yield from convert_thinking_block(block)
    elif block_type == "tool_use":
        yield from convert_tool_use_block(block)
    elif block_type == "tool_result":
        yield from convert_tool_result_block(block)
    # compaction, user text, unknown: no SSE event emitted


# ---------------------------------------------------------------------------
# Entry-level dispatcher (backward compat — no visibility filtering)
# ---------------------------------------------------------------------------


def convert_entry(entry: dict[str, object]) -> Iterator[str]:  # guard: loose-dict
    """Convert a single JSONL transcript entry to zero or more SSE events.

    Preserved for backward compatibility. Emits all assistant content blocks
    without visibility filtering. For web-visible output with filtering, use:
        project_entries([entry], WEB_POLICY) + convert_projected_block()

    Dispatches on the entry's message content blocks. Entries without
    a recognized message structure are silently skipped.
    """
    message = normalize_transcript_entry_message(entry)
    if not isinstance(message, dict):
        return

    role = message.get("role")
    content = message.get("content")

    # Only process assistant messages — user/system content is handled elsewhere
    if role != "assistant":
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
