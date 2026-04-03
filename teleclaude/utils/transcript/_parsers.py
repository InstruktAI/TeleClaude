"""Transcript entry normalization: parse agent-native formats into a uniform message dict."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import cast


def clean_command_message_text(text: str) -> str:
    """Clean verbose prompt blocks from injected command messages."""
    trimmed = text.strip()
    if trimmed.startswith("<command-message>"):
        name_match = re.search(r"<command-name>([\s\S]*?)</command-name>", text)
        args_match = re.search(r"<command-args>([\s\S]*?)</command-args>", text)
        if name_match:
            name = name_match.group(1).strip()
            args = args_match.group(1).strip() if args_match else ""
            return f"{name} {args}".strip()
    return text


def _clean_message_content(
    message: dict[str, object],  # guard: loose-dict - External message payload
) -> dict[str, object]:  # guard: loose-dict - Normalized message payload
    """Return a new message dict with cleaned command texts, avoiding in-place mutation."""
    content = message.get("content")
    if isinstance(content, str):
        cleaned_text = clean_command_message_text(content)
        if cleaned_text != content:
            new_message = dict(message)
            new_message["content"] = cleaned_text
            return new_message
        return message

    if not isinstance(content, list):
        return message

    needs_cleaning = False
    for block in content:
        if isinstance(block, dict) and block.get("type") in ("text", "input_text"):
            text_val = block.get("text")
            if isinstance(text_val, str) and clean_command_message_text(text_val) != text_val:
                needs_cleaning = True
                break

    if not needs_cleaning:
        return message

    new_message = dict(message)
    new_content = []
    for block in content:
        if isinstance(block, dict) and block.get("type") in ("text", "input_text"):
            text_val = block.get("text")
            if isinstance(text_val, str):
                cleaned_text = clean_command_message_text(text_val)
                if cleaned_text != text_val:
                    new_block = dict(block)
                    new_block["text"] = cleaned_text
                    new_content.append(new_block)
                    continue
        new_content.append(block)

    new_message["content"] = new_content
    return new_message


def _extract_codex_reasoning_text(  # pylint: disable=too-many-branches
    payload: Mapping[str, object],  # guard: loose-dict - External payload
) -> str:
    """Extract displayable reasoning text from a Codex reasoning payload.

    Skips summary-level text (verbose chain-of-thought noise); only extracts
    direct text and content blocks which carry actual thinking.
    """
    chunks: list[str] = []

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


def normalize_transcript_entry_message(  # pylint: disable=too-many-return-statements
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
        return _clean_message_content(cast(dict[str, object], message))  # guard: loose-dict - External message

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

    if payload_type == "function_call":
        name = str(payload.get("name", "unknown"))
        arguments = payload.get("arguments", "")
        input_data: dict[str, object] = {}  # guard: loose-dict
        if isinstance(arguments, str):
            try:
                input_data = json.loads(arguments)
            except (json.JSONDecodeError, TypeError):
                input_data = {"raw": arguments}
        # Codex wraps everything in exec_command — use the actual command as the tool name.
        if name == "exec_command" and isinstance(input_data.get("cmd"), str):
            name = str(input_data["cmd"]).split("\n", maxsplit=1)[0]
        return {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": name, "id": payload.get("call_id", ""), "input": input_data}],
        }

    if payload_type == "function_call_output":
        output = payload.get("output", "")
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": payload.get("call_id", ""),
                    "content": [{"type": "text", "text": str(output)}],
                }
            ],
        }

    if payload_type == "message" or (isinstance(payload.get("role"), str) and "content" in payload):
        return _clean_message_content(cast(dict[str, object], payload))  # guard: loose-dict - External payload message

    return None
