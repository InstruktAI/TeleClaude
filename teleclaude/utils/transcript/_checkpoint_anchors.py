"""Checkpoint-compliance anchors in agent-native transcripts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from teleclaude.constants import CHECKPOINT_PREFIX
from teleclaude.core.agents import AgentName
from teleclaude.core.models import JsonDict

from ._parsers import normalize_transcript_entry_message
from ._user_turns import extract_text_from_message_content, find_turn_start_idx
from ._utils import _parse_timestamp

_CODEX_STOP_HOOK_PROMPT_RE = re.compile(
    r"^\s*<hook_prompt\b(?=[^>]*\bhook_run_id=[\"']stop:)[^>]*>",
    re.DOTALL,
)
_CLAUDE_STOP_HOOK_FEEDBACK_PREFIX = "Stop hook feedback:"


@dataclass(frozen=True)
class CheckpointAnchor:
    """Transcript location for a checkpoint compliance round."""

    entry_index: int
    next_index: int
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


def _is_checkpoint_body(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith(CHECKPOINT_PREFIX) or stripped.startswith("[TeleClaude Checkpoint]")


def _is_codex_stop_checkpoint_prompt(text: str) -> bool:
    match = _CODEX_STOP_HOOK_PROMPT_RE.match(text)
    if not match:
        return False
    return _is_checkpoint_body(text[match.end() :])


def _is_claude_stop_checkpoint_feedback(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped.startswith(_CLAUDE_STOP_HOOK_FEEDBACK_PREFIX):
        return False
    return _is_checkpoint_body(stripped[len(_CLAUDE_STOP_HOOK_FEEDBACK_PREFIX) :])


def is_checkpoint_anchor_entry(
    entry: Mapping[str, object],
    agent_name: AgentName | str | None = None,
) -> bool:
    """Return True when an entry starts a checkpoint-compliance round."""
    message = normalize_transcript_entry_message(entry)
    if not isinstance(message, dict) or message.get("role") != "user":
        return False

    text = extract_text_from_message_content(message.get("content"), "user")
    if not text:
        return False

    agent = _agent_value(agent_name)
    if agent == AgentName.CODEX.value:
        return _is_codex_stop_checkpoint_prompt(text)
    if agent == AgentName.CLAUDE.value:
        return _is_claude_stop_checkpoint_feedback(text)
    if agent == AgentName.GEMINI.value:
        return _is_checkpoint_body(text)
    return (
        _is_codex_stop_checkpoint_prompt(text) or _is_claude_stop_checkpoint_feedback(text) or _is_checkpoint_body(text)
    )


def find_last_checkpoint_anchor(
    entries: Sequence[JsonDict],
    agent_name: AgentName | str | None = None,
) -> CheckpointAnchor | None:
    """Find the latest checkpoint-compliance anchor in a transcript."""
    for i in range(len(entries) - 1, -1, -1):
        entry = entries[i]
        if not is_checkpoint_anchor_entry(entry, agent_name):
            continue
        return CheckpointAnchor(
            entry_index=i,
            next_index=i + 1,
            timestamp=_entry_timestamp(entry),
        )
    return None


def find_checkpoint_scope_start_idx(
    entries: Sequence[JsonDict],
    full_session: bool,
    agent_name: AgentName | str | None = None,
) -> int:
    """Return checkpoint evidence start: latest checkpoint, else real user turn."""
    if full_session:
        return 0
    anchor = find_last_checkpoint_anchor(entries, agent_name)
    if anchor is not None:
        return anchor.next_index
    return find_turn_start_idx(entries, full_session=False, agent_name=agent_name)


__all__ = [
    "CheckpointAnchor",
    "find_checkpoint_scope_start_idx",
    "find_last_checkpoint_anchor",
    "is_checkpoint_anchor_entry",
]
