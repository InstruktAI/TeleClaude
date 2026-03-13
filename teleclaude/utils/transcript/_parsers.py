"""Transcript entry normalization: parse agent-native formats into a uniform message dict."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast


def _extract_codex_reasoning_text(
    payload: Mapping[str, object],  # guard: loose-dict - External payload
) -> str:
    """Extract displayable reasoning text from a Codex reasoning payload."""
    chunks: list[str] = []

    summary = payload.get("summary")
    if isinstance(summary, list):
        for item in summary:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
            elif isinstance(item, str) and item.strip():
                chunks.append(item.strip())

    direct_text = payload.get("text")
    if isinstance(direct_text, str) and direct_text.strip():
        chunks.append(direct_text.strip())

    content = payload.get("content")
    if isinstance(content, str) and content.strip():
        chunks.append(content.strip())
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            block_text = block.get("text")
            if isinstance(block_text, str) and block_text.strip():
                chunks.append(block_text.strip())

    # Preserve source order, drop exact duplicates.
    seen: set[str] = set()
    deduped: list[str] = []
    for chunk in chunks:
        if chunk in seen:
            continue
        seen.add(chunk)
        deduped.append(chunk)

    return "\n\n".join(deduped)


def normalize_transcript_entry_message(
    entry: Mapping[str, object],  # guard: loose-dict - External entry
) -> dict[str, object] | None:  # guard: loose-dict - Normalized message
    """Normalize transcript entry variants into a message-like dict.

    Supports:
    - native ``message`` entries
    - ``response_item`` entries with ``payload.type == "message"``
    - Codex reasoning payloads mapped to assistant ``thinking`` blocks
    """
    message = entry.get("message")
    if isinstance(message, dict):
        return cast(dict[str, object], message)  # guard: loose-dict - External message

    if entry.get("type") != "response_item":
        return None

    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return None

    payload_type = payload.get("type")
    if payload_type == "reasoning":
        reasoning_text = _extract_codex_reasoning_text(payload)
        if not reasoning_text.strip():
            return None
        return {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": reasoning_text}],
        }

    if payload_type == "message" or (isinstance(payload.get("role"), str) and "content" in payload):
        return cast(dict[str, object], payload)  # guard: loose-dict - External payload message

    return None
