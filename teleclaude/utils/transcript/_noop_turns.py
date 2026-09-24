"""Keep the no-output sentinel and silent agent turns out of rendered output."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from teleclaude.core.models import JsonDict
from teleclaude.core.session_output import is_bare_noop_output

from ._parsers import normalize_transcript_entry_message
from ._user_turns import is_user_tool_result_only_message

_CONTENT_KEY = "content"
_ROLE_KEY = "role"
_TEXT_KEY = "text"
_TYPE_KEY = "type"
_TEXT_JOINER = "\n\n"


class _MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class _AuthoredTextBlockType(StrEnum):
    TEXT = "text"
    OUTPUT_TEXT = "output_text"


def _opens_turn(entry: Mapping[str, object]) -> bool:
    """Any input that starts an agent turn: human, wake, reminder — never a tool result."""
    message = normalize_transcript_entry_message(entry)
    if not isinstance(message, dict) or message.get(_ROLE_KEY) != _MessageRole.USER:
        return False
    return not is_user_tool_result_only_message(message)


def _authored_text(entry: Mapping[str, object]) -> str | None:
    """Return the non-empty assistant text one entry authored, or None when it authored none."""
    message = normalize_transcript_entry_message(entry)
    if not isinstance(message, dict) or message.get(_ROLE_KEY) != _MessageRole.ASSISTANT:
        return None
    content = message.get(_CONTENT_KEY)
    if isinstance(content, str):
        return content if content.strip() else None
    if not isinstance(content, list):
        return None
    texts = [
        text
        for block in content
        if isinstance(block, Mapping) and block.get(_TYPE_KEY) in set(_AuthoredTextBlockType)
        if isinstance(text := block.get(_TEXT_KEY), str)
    ]
    joined = _TEXT_JOINER.join(text for text in texts if text.strip())
    return joined or None


def _is_sentinel_entry(entry: Mapping[str, object]) -> bool:
    text = _authored_text(entry)
    return text is not None and is_bare_noop_output(text)


def _visible_turn(turn: list[JsonDict]) -> list[JsonDict]:
    """Drop a silent turn whole; otherwise drop only its sentinel entries."""
    authored = [text for text in (_authored_text(entry) for entry in turn) if text is not None]
    if authored and all(is_bare_noop_output(text) for text in authored):
        return []
    return [entry for entry in turn if not _is_sentinel_entry(entry)]


def without_noop_output(entries: list[JsonDict]) -> list[JsonDict]:
    """Remove every ``NOOP`` sentinel, and every turn that authored nothing else.

    A turn whose only authored text is the sentinel is silent: its thinking and
    tool calls go with it. A turn that also authored real text keeps that text;
    only the sentinel is removed. Turn inputs are always kept, so the result
    renders the same wherever a turn sits in the window.
    """
    kept: list[JsonDict] = []
    turn: list[JsonDict] = []
    for entry in entries:
        if _opens_turn(entry):
            kept.extend(_visible_turn(turn))
            kept.append(entry)
            turn = []
            continue
        turn.append(entry)
    kept.extend(_visible_turn(turn))
    return kept
