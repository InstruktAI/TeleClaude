"""Real user-turn detection for agent-native transcript entries."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from teleclaude.core.agents import AgentName
from teleclaude.core.models import JsonDict
from teleclaude.output_projection.visibility import is_hook_side_channel_artifact

from ._parsers import normalize_transcript_entry_message
from ._utils import _parse_timestamp

_CLAUDE_TASK_NOTIFICATION_RE = re.compile(r"^\s*<task-notification\b", re.DOTALL)
_CLAUDE_COMPACT_SUMMARY_FIELD = "isCompactSummary"


@dataclass(frozen=True)
class RealUserTurn:
    """The transcript location and content for a real user turn."""

    entry_index: int
    next_index: int
    text: str | None
    timestamp: datetime | None


def _agent_value(agent_name: AgentName | str | None) -> str | None:
    if isinstance(agent_name, AgentName):
        return agent_name.value
    if isinstance(agent_name, str):
        return agent_name.lower()
    return None


def _entry_timestamp(entry: Mapping[str, object]) -> datetime | None:
    entry_ts = entry.get("timestamp")
    return _parse_timestamp(entry_ts) if isinstance(entry_ts, str) else None


def extract_text_from_message_content(content: object, role: str) -> str | None:
    """Extract the first text block from normalized message content."""
    if isinstance(content, str):
        return content if content.strip() else None

    if not isinstance(content, list):
        return None

    valid_types = ("input_text", "text") if role == "user" else ("text", "output_text")
    for block in content:
        if not isinstance(block, dict) or block.get("type") not in valid_types:
            continue
        text = str(block.get("text", ""))
        if text.strip():
            return text
    return None


def is_user_tool_result_only_message(message: Mapping[str, object]) -> bool:
    """Return True when a user message only carries tool_result blocks.

    Claude writes tool outputs as role=user messages. Those entries are part
    of the assistant turn and must not reset current-turn boundaries.
    """
    if message.get("role") != "user":
        return False

    content = message.get("content")
    if isinstance(content, str):
        return False
    if not isinstance(content, list) or not content:
        return False

    saw_block = False
    for block in content:
        if not isinstance(block, dict):
            return False
        saw_block = True
        if block.get("type") != "tool_result":
            return False
    return saw_block


def _is_teleclaude_control_text(text: str) -> bool:
    """Return True for exact TeleClaude-owned non-human input envelopes."""
    return is_hook_side_channel_artifact(text)


def _is_claude_internal_user_entry(entry: Mapping[str, object], text: str | None) -> bool:
    """Classify Claude Code user-shaped runtime artifacts by native envelope."""
    if entry.get(_CLAUDE_COMPACT_SUMMARY_FIELD) is True:
        return True
    if entry.get("isMeta") is True:
        return True

    origin = entry.get("origin")
    if isinstance(origin, Mapping) and origin.get("kind") == "task-notification":
        return True

    attachment = entry.get("attachment")
    if isinstance(attachment, Mapping):
        if attachment.get("type") == "hook_blocking_error":
            return True
        if attachment.get("commandMode") == "task-notification":
            return True

    if text is None:
        return False

    # Older Claude task-notification transcript entries did not always include
    # origin metadata. The XML wrapper is a Claude CLI envelope, not user prose.
    if entry.get("permissionMode") == "bypassPermissions" and _CLAUDE_TASK_NOTIFICATION_RE.match(text):
        return True

    return _is_teleclaude_control_text(text)


def _is_codex_internal_user_entry(entry: Mapping[str, object], text: str | None) -> bool:
    """Classify Codex user-shaped runtime artifacts by native envelope."""
    if text is None:
        return False
    return _is_teleclaude_control_text(text)


def _is_gemini_internal_user_entry(text: str | None) -> bool:
    """Classify Gemini user-shaped runtime artifacts.

    Gemini session JSON currently stores TeleClaude hook/notification prompts
    as plain user entries with no source metadata, so the exact TeleClaude
    system envelope is the contract available in the native book.
    """
    if text is None:
        return False
    return _is_teleclaude_control_text(text)


def is_real_user_turn_entry(
    entry: Mapping[str, object],
    agent_name: AgentName | str | None = None,
) -> bool:
    """Return True only for transcript entries that start a real user turn."""
    message = normalize_transcript_entry_message(entry)
    if not isinstance(message, dict) or message.get("role") != "user":
        return False
    if is_user_tool_result_only_message(message):
        return False

    text = extract_text_from_message_content(message.get("content"), "user")
    agent = _agent_value(agent_name)

    if agent == AgentName.CLAUDE.value and _is_claude_internal_user_entry(entry, text):
        return False
    if agent == AgentName.CODEX.value and _is_codex_internal_user_entry(entry, text):
        return False
    if agent == AgentName.GEMINI.value and _is_gemini_internal_user_entry(text):
        return False

    if agent is None and text is not None and _is_teleclaude_control_text(text):
        return False
    return text is not None


def extract_real_user_text_from_entry(
    entry: Mapping[str, object],
    agent_name: AgentName | str | None = None,
) -> str | None:
    """Return user text only when the entry is a real user turn."""
    if not is_real_user_turn_entry(entry, agent_name):
        return None
    message = normalize_transcript_entry_message(entry)
    if not isinstance(message, dict):
        return None
    return extract_text_from_message_content(message.get("content"), "user")


def find_last_real_user_turn(
    entries: Sequence[JsonDict],
    agent_name: AgentName | str | None = None,
) -> RealUserTurn | None:
    """Find the last real user turn in a transcript entry sequence."""
    for i in range(len(entries) - 1, -1, -1):
        entry = entries[i]
        if not is_real_user_turn_entry(entry, agent_name):
            continue
        return RealUserTurn(
            entry_index=i,
            next_index=i + 1,
            text=extract_real_user_text_from_entry(entry, agent_name),
            timestamp=_entry_timestamp(entry),
        )
    return None


def find_turn_start_idx(
    entries: Sequence[JsonDict],
    full_session: bool,
    agent_name: AgentName | str | None = None,
) -> int:
    """Return the first entry index for current-turn transcript inspection."""
    if full_session:
        return 0
    turn = find_last_real_user_turn(entries, agent_name)
    return turn.next_index if turn is not None else 0


__all__ = [
    "RealUserTurn",
    "extract_real_user_text_from_entry",
    "extract_text_from_message_content",
    "find_last_real_user_turn",
    "find_turn_start_idx",
    "is_real_user_turn_entry",
    "is_user_tool_result_only_message",
]
