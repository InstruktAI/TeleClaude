"""Generate searchable conversation mirrors from native transcripts."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone

from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript import StructuredMessage, extract_structured_messages

from .store import MirrorRecord, delete_mirror, get_mirror, upsert_mirror

_SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", flags=re.DOTALL)
_TITLE_MAX_CHARS = 120


def _clean_user_text(text: str) -> str:
    return _SYSTEM_REMINDER_RE.sub("", text).strip()


def _normalize_conversation_messages(messages: list[StructuredMessage]) -> list[StructuredMessage]:
    """Keep only conversation text and strip injected reminder blocks."""
    normalized: list[StructuredMessage] = []
    for message in messages:
        if message.type != "text" or message.role not in {"user", "assistant"}:
            continue
        text = _clean_user_text(message.text) if message.role == "user" else message.text.strip()
        if not text:
            continue
        normalized.append(replace(message, text=text))
    return normalized


def _title_from_messages(messages: list[StructuredMessage]) -> str:
    for message in messages:
        if message.role == "user" and message.text.strip():
            title = message.text.strip()
            if len(title) <= _TITLE_MAX_CHARS:
                return title
            return title[: _TITLE_MAX_CHARS - 3].rstrip() + "..."
    return ""


def _render_conversation(messages: list[StructuredMessage]) -> str:
    lines = [f"{message.role.capitalize()}: {message.text}" for message in messages]
    return "\n\n".join(lines)


async def generate_mirror(
    session_id: str,
    transcript_path: str,
    agent_name: AgentName,
    computer: str,
    project: str,
    db: object | None,
) -> None:
    """Extract conversation-only text from a transcript and upsert a mirror."""
    structured = extract_structured_messages(
        transcript_path,
        agent_name,
        include_tools=False,
        include_thinking=False,
    )
    conversation_messages = _normalize_conversation_messages(structured)
    if not conversation_messages:
        delete_mirror(session_id, db=db)
        return

    existing = get_mirror(session_id, db=db)
    now = datetime.now(timezone.utc).isoformat()
    timestamp_start = conversation_messages[0].timestamp
    timestamp_end = conversation_messages[-1].timestamp

    record = MirrorRecord(
        session_id=session_id,
        computer=computer,
        agent=agent_name.value,
        project=project,
        title=_title_from_messages(conversation_messages),
        timestamp_start=timestamp_start,
        timestamp_end=timestamp_end,
        conversation_text=_render_conversation(conversation_messages),
        message_count=len(conversation_messages),
        metadata={"transcript_path": transcript_path, "agent": agent_name.value},
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    upsert_mirror(record, db=db)
