"""Generate searchable conversation mirrors from native transcripts."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.summarizer import SUMMARY_SCHEMA, _call_summarizer, _parse_summary_response
from teleclaude.utils.transcript import StructuredMessage, extract_structured_messages

from .derivation import (
    DERIVATION_VERSION,
    derive_human_title,
    detect_launch,
    is_known_launch_command,
    is_worker_command,
    render_title,
    strip_injected_blocks,
)
from .store import JsonValue, MirrorRecord, delete_mirror, get_mirror, upsert_mirror


def _normalize_conversation_messages(messages: list[StructuredMessage]) -> list[StructuredMessage]:
    """Keep only conversation text and strip injected machine-context blocks."""
    normalized: list[StructuredMessage] = []
    for message in messages:
        if message.type != "text" or message.role not in {"user", "assistant"}:
            continue
        text = strip_injected_blocks(message.text) if message.role == "user" else message.text.strip()
        if not text:
            continue
        normalized.append(replace(message, text=text))
    return normalized


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

MIRROR_SHRINK_REFUSED = "mirror.regeneration.shrink_refused"


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
    launch = detect_launch(structured)
    is_worker = is_worker_command(launch.command)
    conversation_messages = _normalize_conversation_messages(structured)
    existing = get_mirror(source_identity=source_identity, db=db)

    if not conversation_messages:
        # A source that yields nothing is a degraded source, not an emptied conversation.
        # Truncation, corruption, a locked file, or a transcript-format change all land
        # here, and for most sessions the stored mirror is the only copy left. Leave the
        # row alone; the caller records a tombstone so the pass is not repeated blindly.
        if existing is None:
            delete_mirror(session_id=session_id, source_identity=source_identity, db=db)
        return False

    if existing is not None and len(conversation_messages) < existing.message_count:
        # The source parsed, but to fewer messages than are already stored. Overwriting
        # would replace a complete record with a partial one and leave no trace, so the
        # richer stored version wins. Message count is the unit, not text length: a
        # re-derivation may legitimately render the same messages more compactly.
        logger.warning(
            MIRROR_SHRINK_REFUSED,
            extra={
                "source_identity": source_identity,
                "stored_messages": existing.message_count,
                "parsed_messages": len(conversation_messages),
            },
        )
        return False
    now = datetime.now(UTC).isoformat()
    timestamp_start = conversation_messages[0].timestamp
    timestamp_end = conversation_messages[-1].timestamp
    conversation_text = _render_conversation(conversation_messages)
    title = (
        render_title(launch.command, launch.slug)
        if is_known_launch_command(launch.command)
        else derive_human_title(conversation_messages)
    )

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
        title=title,
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
        command=launch.command,
        slug=launch.slug,
        is_worker=is_worker,
        derivation_version=DERIVATION_VERSION,
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
