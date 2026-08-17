"""Real user-turn detection for agent-native transcript entries."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from teleclaude.core.agents import AgentName
from teleclaude.core.models import JsonDict
from teleclaude.output_projection.visibility import is_hook_side_channel_artifact

from ._parsers import normalize_transcript_entry_message
from ._utils import _parse_timestamp

_CLAUDE_TASK_NOTIFICATION_RE = re.compile(r"^\s*<task-notification\b", re.DOTALL)
_CLAUDE_COMPACT_SUMMARY_FIELD = "isCompactSummary"
_CLAUDE_ENTRY_ID_FIELD = "uuid"
_CLAUDE_PARENT_ENTRY_ID_FIELD = "parentUuid"
_MESSAGE_ROLE_FIELD = "role"
_ASSISTANT_ROLE = "assistant"


class ClaudeTurnCommitmentOutcome(StrEnum):
    """Closed receipt-less Claude candidate commitment outcomes."""

    COMMITTED = "committed"
    PROVISIONAL = "provisional"
    UNRESOLVED = "unresolved"


class ClaudeTurnCommitmentReason(StrEnum):
    """Stable structural reasons for a Claude candidate commitment outcome."""

    ASSISTANT_DESCENDANT = "assistant_descendant"
    ASSISTANT_DESCENDANT_PENDING = "assistant_descendant_pending"
    CANDIDATE_NOT_FOUND = "candidate_not_found"
    CANDIDATE_NOT_USER = "candidate_not_user"
    DUPLICATE_ENTRY_ID = "duplicate_entry_id"
    MALFORMED_DESCENDANT_ID = "malformed_descendant_id"
    MISSING_PARENT_ENTRY = "missing_parent_entry"
    ANCESTRY_CYCLE = "ancestry_cycle"


@dataclass(frozen=True)
class ClaudeTurnCommitment:
    """Structural commitment decision for one receipt-less Claude candidate."""

    outcome: ClaudeTurnCommitmentOutcome
    reason: ClaudeTurnCommitmentReason
    candidate_entry_id: str
    parent_entry_id: str | None
    alternative_entry_ids: tuple[str, ...]


@dataclass(frozen=True)
class _ClaudeGraphNode:
    """Indexed Claude entry fields needed for descendant traversal."""

    entry_id: str | None
    parent_entry_id: str | None
    role: str | None
    is_real_user: bool


@dataclass(frozen=True)
class RealUserTurn:
    """The transcript location and content for a real user turn."""

    entry_index: int
    next_index: int
    text: str | None
    timestamp: datetime | None


class ClaudeTurnCommitmentResolver:
    """One-pass Claude graph index with per-candidate commitment queries."""

    def __init__(self, entries: Sequence[JsonDict]) -> None:
        self._nodes_by_id: dict[str, _ClaudeGraphNode] = {}
        self._duplicate_entry_ids: set[str] = set()
        self._children_by_parent_id: dict[str, list[_ClaudeGraphNode]] = {}
        for entry in entries:
            raw_entry_id = entry.get(_CLAUDE_ENTRY_ID_FIELD)
            entry_id = raw_entry_id if isinstance(raw_entry_id, str) and raw_entry_id else None
            raw_parent_entry_id = entry.get(_CLAUDE_PARENT_ENTRY_ID_FIELD)
            parent_entry_id = (
                raw_parent_entry_id if isinstance(raw_parent_entry_id, str) and raw_parent_entry_id else None
            )
            message = normalize_transcript_entry_message(entry)
            raw_role = message.get(_MESSAGE_ROLE_FIELD) if isinstance(message, Mapping) else None
            role = raw_role if isinstance(raw_role, str) else None
            node = _ClaudeGraphNode(
                entry_id=entry_id,
                parent_entry_id=parent_entry_id,
                role=role,
                is_real_user=is_real_user_turn_entry(entry, AgentName.CLAUDE),
            )
            if entry_id is not None:
                if entry_id in self._nodes_by_id:
                    self._duplicate_entry_ids.add(entry_id)
                else:
                    self._nodes_by_id[entry_id] = node
            if parent_entry_id is not None:
                self._children_by_parent_id.setdefault(parent_entry_id, []).append(node)

    def resolve(self, candidate_entry_id: str) -> ClaudeTurnCommitment:
        """Resolve whether Claude continued from one receipt-less candidate."""
        candidate = self._nodes_by_id.get(candidate_entry_id)
        if candidate is None:
            return ClaudeTurnCommitment(
                outcome=ClaudeTurnCommitmentOutcome.UNRESOLVED,
                reason=ClaudeTurnCommitmentReason.CANDIDATE_NOT_FOUND,
                candidate_entry_id=candidate_entry_id,
                parent_entry_id=None,
                alternative_entry_ids=(),
            )

        parent_entry_id = candidate.parent_entry_id
        sibling_nodes = self._children_by_parent_id.get(parent_entry_id, ()) if parent_entry_id is not None else ()
        alternatives = tuple(
            node.entry_id
            for node in sibling_nodes
            if node.entry_id is not None and node.entry_id != candidate_entry_id and node.is_real_user
        )

        def result(
            outcome: ClaudeTurnCommitmentOutcome,
            reason: ClaudeTurnCommitmentReason,
        ) -> ClaudeTurnCommitment:
            return ClaudeTurnCommitment(
                outcome=outcome,
                reason=reason,
                candidate_entry_id=candidate_entry_id,
                parent_entry_id=parent_entry_id,
                alternative_entry_ids=alternatives,
            )

        if candidate_entry_id in self._duplicate_entry_ids:
            return result(ClaudeTurnCommitmentOutcome.UNRESOLVED, ClaudeTurnCommitmentReason.DUPLICATE_ENTRY_ID)
        if not candidate.is_real_user:
            return result(ClaudeTurnCommitmentOutcome.UNRESOLVED, ClaudeTurnCommitmentReason.CANDIDATE_NOT_USER)
        if parent_entry_id is not None and parent_entry_id not in self._nodes_by_id:
            return result(ClaudeTurnCommitmentOutcome.UNRESOLVED, ClaudeTurnCommitmentReason.MISSING_PARENT_ENTRY)

        pending_ids = [candidate_entry_id]
        visited_ids: set[str] = set()
        assistant_descendant_present = False
        while pending_ids:
            parent_id = pending_ids.pop()
            if parent_id in visited_ids:
                return result(ClaudeTurnCommitmentOutcome.UNRESOLVED, ClaudeTurnCommitmentReason.ANCESTRY_CYCLE)
            visited_ids.add(parent_id)
            for child in self._children_by_parent_id.get(parent_id, ()):
                child_id = child.entry_id
                if child_id is None:
                    return result(
                        ClaudeTurnCommitmentOutcome.UNRESOLVED,
                        ClaudeTurnCommitmentReason.MALFORMED_DESCENDANT_ID,
                    )
                if child_id in self._duplicate_entry_ids:
                    return result(
                        ClaudeTurnCommitmentOutcome.UNRESOLVED,
                        ClaudeTurnCommitmentReason.DUPLICATE_ENTRY_ID,
                    )
                if child.role == _ASSISTANT_ROLE:
                    assistant_descendant_present = True
                pending_ids.append(child_id)

        if assistant_descendant_present:
            return result(ClaudeTurnCommitmentOutcome.COMMITTED, ClaudeTurnCommitmentReason.ASSISTANT_DESCENDANT)
        return result(
            ClaudeTurnCommitmentOutcome.PROVISIONAL,
            ClaudeTurnCommitmentReason.ASSISTANT_DESCENDANT_PENDING,
        )


def resolve_claude_turn_commitment(
    entries: Sequence[JsonDict],
    candidate_entry_id: str,
) -> ClaudeTurnCommitment:
    """Resolve one candidate through a freshly indexed Claude transcript graph."""
    return ClaudeTurnCommitmentResolver(entries).resolve(candidate_entry_id)


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
    "ClaudeTurnCommitment",
    "ClaudeTurnCommitmentOutcome",
    "ClaudeTurnCommitmentReason",
    "ClaudeTurnCommitmentResolver",
    "RealUserTurn",
    "extract_real_user_text_from_entry",
    "extract_text_from_message_content",
    "find_last_real_user_turn",
    "find_turn_start_idx",
    "is_real_user_turn_entry",
    "is_user_tool_result_only_message",
    "resolve_claude_turn_commitment",
]
