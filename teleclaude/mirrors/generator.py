"""Generate searchable conversation mirrors from native transcripts."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.caller_identity import SystemCliCaller
from teleclaude.config import config
from teleclaude.constants import ROLE_WORKER
from teleclaude.core.agents import AgentName
from teleclaude.identity_reach import resolve_reach

from teleclaude.utils.transcript import StructuredMessage  # isort: skip  # transcript initialization imports the projector

from teleclaude.output_projection.conversation_projector import project_conversation_chain
from teleclaude.output_projection.models import VisibilityPolicy
from teleclaude.output_projection.serializers import to_structured_message

from ._attribution import MirrorSessionAttribution
from ._types import JsonValue
from .derivation import DERIVATION_VERSION, derive_human_title
from .session_context import MirrorAttributionReason, SessionMirrorContext
from .store import (
    MirrorRecord,
    delete_mirror,
    get_mirror,
    record_mirror_shrink_refusal,
    upsert_mirror,
)

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


def _normalize_conversation_messages(messages: list[StructuredMessage]) -> list[StructuredMessage]:
    """Keep only conversation text after canonical projection has cleaned it."""
    normalized: list[StructuredMessage] = []
    for message in messages:
        if message.type != "text" or message.role not in {"user", "assistant"}:
            continue
        text = message.text.strip()
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


logger = get_logger(__name__)

MIRROR_SHRINK_REFUSED = "mirror.regeneration.shrink_refused"
MIRROR_SHRINK_ACCEPTED = "mirror.regeneration.shrink_accepted"
MIRROR_ATTRIBUTION_RECORDED_EVENT = "mirror.session_attribution.recorded"


class MirrorWriteTrigger(StrEnum):
    """The writer that caused a mirror upsert."""

    RECONCILE = "reconcile"
    FANOUT = "fanout"


class MirrorAttributionOutcome(StrEnum):
    """Whether a mirror write found an owning session record."""

    ATTRIBUTED = "attributed"
    UNATTRIBUTED = "unattributed"


def generate_mirror_sync(
    native_session_id: str,
    source_identity: str,
    transcript_path: str,
    agent_name: AgentName,
    db: str | Path | None,
    *,
    context: SessionMirrorContext | None = None,
    trigger: MirrorWriteTrigger,
    reconcile_id: str | None = None,
    fallback_project_path: str | None = None,
) -> MirrorGenerationOutcome:
    """Extract conversation-only text from a transcript and upsert a mirror.

    Session classification and facts come from the session record. Transcript text
    supplies a title only when creating a new unattributed mirror.
    """
    projected_blocks = project_conversation_chain(
        [transcript_path],
        agent_name,
        _MIRROR_VISIBILITY_POLICY,
        cleanup_runtime_user_spans=True,
    )
    structured = [to_structured_message(block) for block in projected_blocks]
    is_worker = context.system_role == ROLE_WORKER if context is not None else None
    conversation_messages = _normalize_conversation_messages(structured)
    existing = get_mirror(source_identity=source_identity, reach=resolve_reach(SystemCliCaller()), db=db)

    if not conversation_messages:
        # A source that yields nothing is a degraded source, not an emptied conversation.
        # Truncation, corruption, a locked file, or a transcript-format change all land
        # here, and for most sessions the stored mirror is the only copy left. Leave the
        # row alone; the caller records a tombstone so the pass is not repeated blindly.
        if existing is None:
            delete_mirror(native_session_id=native_session_id, source_identity=source_identity, db=db)
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
            record_mirror_shrink_refusal(
                source_identity,
                shrink_refused_at=datetime.now(UTC).isoformat(),
                db=db,
            )
            return MirrorGenerationOutcome.SHRINK_REFUSED
    else:
        shrink_outcome = MirrorGenerationOutcome.GENERATED
    now = datetime.now(UTC).isoformat()
    timestamp_start = conversation_messages[0].timestamp
    timestamp_end = conversation_messages[-1].timestamp
    conversation_text = _render_conversation(conversation_messages)
    resolved_title = (
        context.title
        if context is not None
        else existing.title
        if existing is not None
        else derive_human_title(conversation_messages)
    )
    metadata: dict[str, JsonValue] = {}
    metadata["transcript_path"] = transcript_path
    metadata["agent"] = agent_name.value
    if context is not None and context.last_input_origin:
        metadata["origin_channel"] = context.last_input_origin
    if context is not None:
        metadata.update(context.channel_identifiers)

    record = MirrorRecord(
        native_session_id=native_session_id,
        session_id=context.session_id if context is not None else None,
        position=context.position if context is not None else None,
        computer=(context.computer or config.computer.name) if context is not None else config.computer.name,
        agent=agent_name.value,
        project_path=context.project_path if context is not None else fallback_project_path,
        title=resolved_title,
        timestamp_start=timestamp_start,
        timestamp_end=timestamp_end,
        conversation_text=conversation_text,
        message_count=len(conversation_messages),
        metadata=metadata,
        created_at=existing.created_at if existing else now,
        updated_at=now,
        source_identity=source_identity,
        human_email=context.human_email if context is not None else None,
        visibility=context.visibility if context is not None else None,
        command=context.command if context is not None else None,
        todo=context.todo if context is not None else None,
        is_worker=is_worker,
        derivation_version=DERIVATION_VERSION,
    )
    attribution = (
        MirrorSessionAttribution(
            session_id=context.session_id,
            principal=context.principal,
            subject=context.subject,
            subject_owner=context.subject_owner,
            project=context.project,
            subdir=context.subdir,
            initiator_session_id=context.initiator_session_id,
            initiator_computer=context.initiator_computer,
            initiated_by_ai=context.initiated_by_ai,
            job=context.job,
            started_at=context.created_at,
            closed_at=None,
        )
        if context is not None
        else None
    )
    upsert_mirror(record, attribution, db=db)
    reason = context.reason if context is not None else MirrorAttributionReason.NO_RECORD
    logger.info(
        MIRROR_ATTRIBUTION_RECORDED_EVENT,
        trigger=trigger,
        reconcile_id=reconcile_id,
        outcome=MirrorAttributionOutcome.ATTRIBUTED if context is not None else MirrorAttributionOutcome.UNATTRIBUTED,
        reason=reason,
        session_id=context.session_id if context is not None else None,
        native_session_id=native_session_id,
        position=context.position if context is not None else None,
        has_principal=bool(context and context.principal),
        has_project=bool(context and context.project),
        facts_supplied=context is not None,
        source_identity=source_identity,
    )
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
    native_session_id: str,
    source_identity: str,
    transcript_path: str,
    agent_name: AgentName,
    db: str | Path | None,
    *,
    context: SessionMirrorContext | None = None,
    trigger: MirrorWriteTrigger,
    reconcile_id: str | None = None,
    fallback_project_path: str | None = None,
) -> MirrorGenerationOutcome:
    """Async entry point that offloads blocking mirror generation work."""
    return await asyncio.to_thread(
        generate_mirror_sync,
        native_session_id=native_session_id,
        source_identity=source_identity,
        transcript_path=transcript_path,
        agent_name=agent_name,
        db=db,
        context=context,
        trigger=trigger,
        reconcile_id=reconcile_id,
        fallback_project_path=fallback_project_path,
    )
