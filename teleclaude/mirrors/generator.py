"""Generate searchable conversation mirrors from native transcripts."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.summarizer import SUMMARY_SCHEMA, _call_summarizer, _parse_summary_response

from teleclaude.utils.transcript import StructuredMessage  # isort: skip  # transcript initialization imports the projector

from teleclaude.output_projection.conversation_projector import project_conversation_chain
from teleclaude.output_projection.models import VisibilityPolicy
from teleclaude.output_projection.serializers import to_structured_message

from .derivation import (
    DERIVATION_VERSION,
    derive_human_title,
    detect_launch,
    is_exact_loader_envelope,
    is_known_launch_command,
    is_worker_command,
    render_title,
    strip_injected_blocks,
)
from .store import JsonValue, MirrorRecord, delete_mirror, get_mirror, upsert_mirror

_MIRROR_VISIBILITY_POLICY = VisibilityPolicy(
    include_tools=False,
    include_tool_results=False,
    include_thinking=False,
    include_system_messages=False,
)


class MirrorGenerationOutcome(StrEnum):
    """Stable result states for one mirror generation attempt."""

    GENERATED = "generated"
    NO_CONVERSATION = "no_conversation"
    SHRINK_ACCEPTED = "shrink_accepted"
    SHRINK_REFUSED = "shrink_refused"


def _normalize_conversation_messages(
    messages: list[StructuredMessage], agent_name: AgentName
) -> list[StructuredMessage]:
    """Keep only conversation text and strip injected machine-context blocks."""
    normalized: list[StructuredMessage] = []
    for message in messages:
        if message.type != "text" or message.role not in {"user", "assistant"}:
            continue
        text = strip_injected_blocks(message.text, agent_name) if message.role == "user" else message.text.strip()
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
MIRROR_SHRINK_ACCEPTED = "mirror.regeneration.shrink_accepted"


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


def _drop_exact_loader_envelope(messages: list[StructuredMessage]) -> list[StructuredMessage]:
    """Drop only the first projected user block when it is a generated loader envelope."""
    for index, message in enumerate(messages):
        if message.role != "user":
            continue
        if is_exact_loader_envelope(message.text):
            return [*messages[:index], *messages[index + 1 :]]
        break
    return messages


def generate_mirror_sync(
    session_id: str | None,
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
) -> MirrorGenerationOutcome:
    """Extract conversation-only text from a transcript and upsert a mirror."""
    projected_blocks = project_conversation_chain(
        [transcript_path],
        agent_name,
        _MIRROR_VISIBILITY_POLICY,
    )
    structured = [to_structured_message(block) for block in projected_blocks]
    launch = detect_launch(structured)
    is_worker = is_worker_command(launch.command)
    conversation_messages = _drop_exact_loader_envelope(_normalize_conversation_messages(structured, agent_name))
    existing = get_mirror(source_identity=source_identity, db=db)

    if not conversation_messages:
        # A source that yields nothing is a degraded source, not an emptied conversation.
        # Truncation, corruption, a locked file, or a transcript-format change all land
        # here, and for most sessions the stored mirror is the only copy left. Leave the
        # row alone; the caller records a tombstone so the pass is not repeated blindly.
        if existing is None:
            delete_mirror(session_id=session_id, source_identity=source_identity, db=db)
        return MirrorGenerationOutcome.NO_CONVERSATION

    if existing is not None and len(conversation_messages) < existing.message_count:
        # The source parsed, but to fewer messages than are already stored. Overwriting
        # would replace a complete record with a partial one and leave no trace, so the
        # richer stored version wins. Message count is the unit, not text length: a
        # re-derivation may legitimately render the same messages more compactly.
        if existing.derivation_version < DERIVATION_VERSION:
            shrink_outcome = MirrorGenerationOutcome.SHRINK_ACCEPTED
        else:
            logger.info(
                MIRROR_SHRINK_REFUSED,
                source_identity=source_identity,
                stored_message_count=existing.message_count,
                projected_message_count=len(conversation_messages),
                stored_derivation_version=existing.derivation_version,
                current_derivation_version=DERIVATION_VERSION,
                outcome=MirrorGenerationOutcome.SHRINK_REFUSED,
            )
            return MirrorGenerationOutcome.SHRINK_REFUSED
    else:
        shrink_outcome = MirrorGenerationOutcome.GENERATED
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
    if shrink_outcome is MirrorGenerationOutcome.SHRINK_ACCEPTED:
        logger.info(
            MIRROR_SHRINK_ACCEPTED,
            source_identity=source_identity,
            stored_message_count=existing.message_count if existing is not None else 0,
            projected_message_count=len(conversation_messages),
            stored_derivation_version=existing.derivation_version if existing is not None else 0,
            current_derivation_version=DERIVATION_VERSION,
            outcome=MirrorGenerationOutcome.SHRINK_ACCEPTED,
        )
    return shrink_outcome


async def generate_mirror(
    session_id: str | None,
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
) -> MirrorGenerationOutcome:
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
