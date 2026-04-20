"""Generate searchable conversation mirrors from native transcripts."""

from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.summarizer import SUMMARY_SCHEMA, _call_summarizer, _parse_summary_response
from teleclaude.utils.transcript import StructuredMessage, extract_structured_messages

from .store import JsonValue, MirrorRecord, delete_mirror, get_mirror, upsert_mirror

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
    lines = [
        f"[{message.timestamp}] {message.role.capitalize()}: {message.text}"
        if message.timestamp is not None
        else f"{message.role.capitalize()}: {message.text}"
        for message in messages
    ]
    return "\n\n".join(lines)


_SUMMARY_MAX_INPUT_CHARS = 4000

logger = get_logger(__name__)


def _build_mirror_summary_prompt(conversation_text: str) -> str:
    """Build a prompt asking for a one-paragraph session summary."""
    truncated = conversation_text[:_SUMMARY_MAX_INPUT_CHARS]
    return f"""Summarize this conversation in one concise paragraph.

## Conversation:
{truncated}

## Output:
1. **summary**: A concise one-paragraph summary of what happened in this conversation.
"""


def _generate_session_summary(conversation_text: str) -> str | None:
    """Generate a one-paragraph session summary. Best-effort — failure does not block mirror creation."""
    if not conversation_text:
        return None
    prompt = _build_mirror_summary_prompt(conversation_text)
    try:
        return asyncio.run(  # type: ignore[no-any-return]
            _call_summarizer(prompt, SUMMARY_SCHEMA, _parse_summary_response)
        )
    except Exception:
        logger.debug("Mirror summary generation failed (best-effort skip)")
        return None


def generate_mirror_sync(
    session_id: str,
    source_identity: str,
    transcript_path: str,
    agent_name: AgentName,
    computer: str,
    project: str,
    db: str | Path | None,
    *,
    human_email: str | None = None,
    visibility: str = "private",
    last_input_origin: str | None = None,
    channel_identifiers: dict[str, str] | None = None,
) -> bool:
    """Extract conversation-only text from a transcript and upsert a mirror."""
    structured = extract_structured_messages(
        transcript_path,
        agent_name,
        include_tools=False,
        include_thinking=False,
    )
    conversation_messages = _normalize_conversation_messages(structured)
    if not conversation_messages:
        delete_mirror(session_id=session_id, source_identity=source_identity, db=db)
        return False

    existing = get_mirror(source_identity=source_identity, db=db)
    now = datetime.now(UTC).isoformat()
    timestamp_start = conversation_messages[0].timestamp
    timestamp_end = conversation_messages[-1].timestamp
    conversation_text = _render_conversation(conversation_messages)

    metadata: dict[str, JsonValue] = {"transcript_path": transcript_path, "agent": agent_name.value}
    if last_input_origin:
        metadata["origin_channel"] = last_input_origin
    if channel_identifiers:
        metadata.update(channel_identifiers)

    summary = _generate_session_summary(conversation_text)

    record = MirrorRecord(
        session_id=session_id,
        computer=computer,
        agent=agent_name.value,
        project=project,
        title=_title_from_messages(conversation_messages),
        timestamp_start=timestamp_start,
        timestamp_end=timestamp_end,
        conversation_text=conversation_text,
        message_count=len(conversation_messages),
        metadata=metadata,
        created_at=existing.created_at if existing else now,
        updated_at=now,
        source_identity=source_identity,
        summary=summary,
        human_email=human_email,
        visibility=visibility,
    )
    upsert_mirror(record, db=db)
    return True


async def generate_mirror(
    session_id: str,
    source_identity: str,
    transcript_path: str,
    agent_name: AgentName,
    computer: str,
    project: str,
    db: str | Path | None,
    *,
    human_email: str | None = None,
    visibility: str = "private",
    last_input_origin: str | None = None,
    channel_identifiers: dict[str, str] | None = None,
) -> bool:
    """Async entry point that offloads blocking mirror generation work."""
    return await asyncio.to_thread(
        generate_mirror_sync,
        session_id=session_id,
        source_identity=source_identity,
        transcript_path=transcript_path,
        agent_name=agent_name,
        computer=computer,
        project=project,
        db=db,
        human_email=human_email,
        visibility=visibility,
        last_input_origin=last_input_origin,
        channel_identifiers=channel_identifiers,
    )
