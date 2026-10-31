"""Antigravity conversation-store reader: the single owner of the subagent determination.

Antigravity keeps one directory per conversation, primary or subagent, beside the
conversation's transcript. A conversation born from an ``invoke_subagent`` call holds
a message record in that directory naming the call and the invoking conversation. No
hook payload carries this ancestry, so the record is the only evidence
(``third-party/antigravity-cli/sub-agents``).

Every read here is best-effort: a hook process that raises blocks the provider's tool
call, so an absent, unreadable or malformed record reads as "no record", which leaves
the conversation a primary one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

# Upper bound on how many invocation links one ancestry walk follows.
_MAX_ANCESTRY_DEPTH = 32
_RECORD_SKIPPED_LOG = "Antigravity message record skipped"


class AgyStoreName(StrEnum):
    """Names in the layout of one Antigravity conversation directory."""

    SYSTEM_GENERATED = ".system_generated"
    LOGS = "logs"
    MESSAGES = "messages"
    TRANSCRIPT = "transcript.jsonl"
    RECORD_PATTERN = "*.json"


class AgyRecordField(StrEnum):
    """Fields of a message record that name the tool call it originated from."""

    SOURCE_METADATA = "sourceMetadata"
    TOOL = "tool"
    TOOL_CALL = "toolCall"
    CONVERSATION_ID = "conversationId"
    NAME = "name"


class AgyInvocationTool(StrEnum):
    """The tool call whose message record marks a conversation as a subagent's."""

    INVOKE_SUBAGENT = "invoke_subagent"


@dataclass(frozen=True)
class AgySubagentOrigin:
    """Where a subagent conversation sits in its invocation chain."""

    root_conversation_id: str
    root_transcript_path: str


def _conversation_dir(transcript_path: str) -> Path | None:
    """Return the conversation directory a transcript path lives in, or None for any other layout."""
    path = Path(transcript_path)
    logs_dir = path.parent
    system_dir = logs_dir.parent
    if (
        path.name != AgyStoreName.TRANSCRIPT
        or logs_dir.name != AgyStoreName.LOGS
        or system_dir.name != AgyStoreName.SYSTEM_GENERATED
    ):
        return None
    return system_dir.parent


def _transcript_path(conversation_dir: Path) -> Path:
    return conversation_dir / AgyStoreName.SYSTEM_GENERATED / AgyStoreName.LOGS / AgyStoreName.TRANSCRIPT


def _invoking_conversation(record_path: Path) -> str | None:
    """Return the invoking conversation a message record names, or None when it is not an invoke_subagent origin."""
    try:
        record: object = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug(_RECORD_SKIPPED_LOG, record_path=str(record_path), error=str(exc))
        return None
    if not isinstance(record, dict):
        return None
    metadata = record.get(AgyRecordField.SOURCE_METADATA)
    tool = metadata.get(AgyRecordField.TOOL) if isinstance(metadata, dict) else None
    if not isinstance(tool, dict):
        return None
    tool_call = tool.get(AgyRecordField.TOOL_CALL)
    if not isinstance(tool_call, dict) or tool_call.get(AgyRecordField.NAME) != AgyInvocationTool.INVOKE_SUBAGENT:
        return None
    conversation_id = tool.get(AgyRecordField.CONVERSATION_ID)
    return conversation_id if isinstance(conversation_id, str) and conversation_id else None


def parent_conversation_id(transcript_path: str) -> str | None:
    """Return the conversation that invoked the transcript's conversation, or None for a primary one.

    Never raises: any unreadable store reads as a primary conversation.
    """
    conversation_dir = _conversation_dir(transcript_path)
    if conversation_dir is None:
        return None
    messages_dir = conversation_dir / AgyStoreName.SYSTEM_GENERATED / AgyStoreName.MESSAGES
    try:
        record_paths = sorted(messages_dir.glob(AgyStoreName.RECORD_PATTERN))
    except (OSError, ValueError) as exc:
        logger.debug(_RECORD_SKIPPED_LOG, record_path=str(messages_dir), error=str(exc))
        return None
    for record_path in record_paths:
        invoking = _invoking_conversation(record_path)
        if invoking is not None:
            return invoking
    return None


def read_subagent_origin(transcript_path: str) -> AgySubagentOrigin | None:
    """Return the root of a subagent conversation's invocation chain, or None for a primary conversation.

    The root is the conversation at the top of the chain: the first ancestor whose own
    store holds no invoke_subagent record. The walk is bounded and stops at a repeated
    conversation, so a malformed store cannot loop it. Never raises.
    """
    conversation_dir = _conversation_dir(transcript_path)
    parent_id = parent_conversation_id(transcript_path)
    if conversation_dir is None or parent_id is None:
        return None
    brain_root = conversation_dir.parent
    visited = {conversation_dir.name}
    root_id = parent_id
    for _ in range(_MAX_ANCESTRY_DEPTH):
        visited.add(root_id)
        next_id = parent_conversation_id(str(_transcript_path(brain_root / root_id)))
        if next_id is None or next_id in visited:
            break
        root_id = next_id
    return AgySubagentOrigin(
        root_conversation_id=root_id,
        root_transcript_path=str(_transcript_path(brain_root / root_id)),
    )
