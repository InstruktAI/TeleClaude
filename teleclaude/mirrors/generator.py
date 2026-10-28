"""Refresh a session-owned conversation mirror from the session's complete transcript lineage."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config
from teleclaude.core.agents import AgentName, resolve_parser_agent
from teleclaude.core.roles import is_focused_role

from teleclaude.utils.transcript import StructuredMessage  # isort: skip  # transcript initialization imports the projector

from teleclaude.output_projection.conversation_projector import project_conversation_chain
from teleclaude.output_projection.models import VisibilityPolicy
from teleclaude.output_projection.serializers import to_structured_message
from teleclaude.utils.transcript_discovery import (
    agent_for_transcript_path,
    build_source_identity,
    classify_transcript,
    extract_session_id,
)

from ._attribution import MirrorSessionAttribution
from ._types import JsonValue
from .conversations import (
    ConversationFacts,
    ConversationState,
    ConversationUpdate,
    MissingSource,
    RecordedCoverage,
    SourceMessage,
    SourceState,
    SourceUpdate,
    get_conversation_state,
    stamp_coverage,
    write_conversation,
)
from .derivation import DERIVATION_VERSION, derive_human_title
from .session_context import SessionMirrorContext, get_session_context
from .store import record_mirror_shrink_refusal

_MIRROR_VISIBILITY_POLICY = VisibilityPolicy(
    include_tools=False,
    include_tool_results=False,
    include_thinking=False,
    include_system_messages=False,
)

logger = get_logger(__name__)

MIRROR_SHRINK_REFUSED = "mirror.regeneration.shrink_refused"
MIRROR_SHRINK_ACCEPTED = "mirror.regeneration.shrink_accepted"
MIRROR_ATTRIBUTION_RECORDED_EVENT = "mirror.session_attribution.recorded"
MIRROR_SOURCE_FAILED_EVENT = "mirror.source_read_failed"
MIRROR_SOURCE_SKIPPED_EVENT = "mirror.source_skipped"
MIRROR_COVERAGE_RECORDED_EVENT = "mirror.coverage_recorded"
_ORIGIN_CHANNEL_FIELD = "origin_channel"
_AGENT_FIELD = "agent"


class MirrorWriteTrigger(StrEnum):
    """The writer that caused a mirror refresh."""

    RECONCILE = "reconcile"
    FANOUT = "fanout"
    CLOSURE = "closure"


class SourceReadOutcome(StrEnum):
    """What one refresh did with one native source of the conversation."""

    UNCHANGED = "unchanged"
    READ = "read"
    SHRINK_ACCEPTED = "shrink_accepted"
    SHRINK_REFUSED = "shrink_refused"
    NO_CONVERSATION = "no_conversation"
    MISSING = "missing"
    EXCLUDED = "excluded"
    FAILED = "failed"


@dataclass(frozen=True)
class MirrorCoverage:
    """How far a session's conversation mirror covers its lineage after a refresh.

    ``ready`` holds once every source present on disk has been read under the current derivation rules; a
    source whose file is gone does not prevent it and is named in ``missing_sources`` with its retained
    content. ``complete`` is false whenever such a source exists.
    """

    session_id: str
    covered_at: str
    ready: bool
    complete: bool
    missing_sources: tuple[MissingSource, ...]
    message_count: int
    text_changed: bool
    source_outcomes: dict[str, SourceReadOutcome]
    config_subject: str | None
    previously_ready: bool


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


def _source_messages(messages: list[StructuredMessage]) -> tuple[SourceMessage, ...]:
    """Key each message by its transcript entry and its block position within that entry."""
    block_ordinals: Counter[int] = Counter()
    keyed: list[SourceMessage] = []
    for message in messages:
        ordinal = block_ordinals[message.entry_index]
        block_ordinals[message.entry_index] += 1
        keyed.append(
            SourceMessage(
                entry_index=message.entry_index,
                block_ordinal=ordinal,
                timestamp=message.timestamp,
                role=message.role,
                text=message.text,
            )
        )
    return tuple(keyed)


@dataclass(frozen=True)
class _SourcePlan:
    """One lineage source resolved for this refresh."""

    path: str
    agent: AgentName
    identity: str
    position: int
    stored: SourceState | None


def _lineage_plans(context: SessionMirrorContext) -> list[_SourcePlan]:
    fallback = resolve_parser_agent(context.agent)
    plans: list[_SourcePlan] = []
    for position, path in enumerate(context.lineage):
        agent = agent_for_transcript_path(path, fallback=fallback)
        plans.append(_SourcePlan(path, agent, build_source_identity(path, agent), position, None))
    return plans


def _kept(
    plan: _SourcePlan, *, missing: bool, file_size: int | None = None, file_mtime_ns: str | None = None
) -> SourceUpdate:
    """A source whose stored content stays: its file is gone, unchanged, or its read was refused."""
    stored = plan.stored
    return SourceUpdate(
        source_identity=plan.identity,
        native_session_id=stored.native_session_id if stored else None,
        agent=plan.agent.value,
        transcript_path=plan.path,
        position=plan.position,
        file_size=file_size,
        file_mtime_ns=file_mtime_ns,
        missing=missing,
        derivation_version=stored.derivation_version if stored else 0,
        messages=None,
    )


def _read_source(
    plan: _SourcePlan, path: Path, size: int, mtime_ns: str, db: str | Path | None
) -> tuple[SourceUpdate, SourceReadOutcome]:
    """Project one present source and decide what the store keeps of it."""
    projected = project_conversation_chain(
        [plan.path], plan.agent, _MIRROR_VISIBILITY_POLICY, cleanup_runtime_user_spans=True
    )
    messages = _normalize_conversation_messages([to_structured_message(block) for block in projected])
    stored = plan.stored
    if not messages:
        # A source that yields nothing is a degraded source, not an emptied conversation: stored content
        # stays, and an unseen source is recorded empty so an unchanged file is not read again.
        if stored is not None and (stored.has_messages or stored.message_count):
            return _kept(plan, missing=False, file_size=size, file_mtime_ns=mtime_ns), SourceReadOutcome.NO_CONVERSATION
        empty = replace(
            _kept(plan, missing=False, file_size=size, file_mtime_ns=mtime_ns),
            native_session_id=str(extract_session_id(path, plan.agent)),
            derivation_version=DERIVATION_VERSION,
            messages=(),
        )
        return empty, SourceReadOutcome.NO_CONVERSATION
    outcome = SourceReadOutcome.READ
    if stored is not None and len(messages) < stored.message_count:
        if stored.derivation_version >= DERIVATION_VERSION:
            logger.info(
                MIRROR_SHRINK_REFUSED,
                source_identity=plan.identity,
                stored_message_count=stored.message_count,
                projected_message_count=len(messages),
                stored_derivation_version=stored.derivation_version,
                current_derivation_version=DERIVATION_VERSION,
                outcome=SourceReadOutcome.SHRINK_REFUSED,
            )
            record_mirror_shrink_refusal(stored.id, shrink_refused_at=datetime.now(UTC).isoformat(), db=db)
            return _kept(plan, missing=False, file_size=size, file_mtime_ns=mtime_ns), SourceReadOutcome.SHRINK_REFUSED
        outcome = SourceReadOutcome.SHRINK_ACCEPTED
    update = SourceUpdate(
        source_identity=plan.identity,
        native_session_id=str(extract_session_id(path, plan.agent)),
        agent=plan.agent.value,
        transcript_path=plan.path,
        position=plan.position,
        file_size=size,
        file_mtime_ns=mtime_ns,
        missing=False,
        derivation_version=DERIVATION_VERSION,
        messages=_source_messages(messages),
    )
    return update, outcome


def _observe_source(plan: _SourcePlan, db: str | Path | None) -> tuple[SourceUpdate | None, SourceReadOutcome]:
    """Observe one lineage source: its stored content stays unless its file was read and yielded conversation."""
    path = Path(plan.path).expanduser()
    if not path.exists():
        return _kept(plan, missing=True), SourceReadOutcome.MISSING
    stat = path.stat()
    mtime_ns = str(stat.st_mtime_ns)
    stored = plan.stored
    if (
        stored is not None
        and stored.file_size == stat.st_size
        and stored.file_mtime_ns == mtime_ns
        and stored.derivation_version >= DERIVATION_VERSION
    ):
        return _kept(plan, missing=False, file_size=stat.st_size, file_mtime_ns=mtime_ns), SourceReadOutcome.UNCHANGED
    is_subagent, is_headless = classify_transcript(path, plan.agent)
    if is_subagent or is_headless:
        logger.info(
            MIRROR_SOURCE_SKIPPED_EVENT, source_identity=plan.identity, subagent=is_subagent, headless=is_headless
        )
        return None, SourceReadOutcome.EXCLUDED
    try:
        return _read_source(plan, path, stat.st_size, mtime_ns, db)
    except Exception as exc:
        logger.error(MIRROR_SOURCE_FAILED_EVENT, source_identity=plan.identity, error=str(exc), exc_info=True)
        return _kept(plan, missing=False), SourceReadOutcome.FAILED


def _attribution(context: SessionMirrorContext) -> MirrorSessionAttribution:
    return MirrorSessionAttribution(
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


def _facts(
    context: SessionMirrorContext,
    state: ConversationState | None,
    updates: list[SourceUpdate],
) -> ConversationFacts:
    first_messages = next((update.messages for update in updates if update.messages), None)
    title = context.title or (state.title if state else None)
    if not title and first_messages:
        title = derive_human_title(
            StructuredMessage(role=message.role, type="text", text=message.text) for message in first_messages
        )
    metadata: dict[str, JsonValue] = {_AGENT_FIELD: updates[-1].agent}
    if context.last_input_origin:
        metadata[_ORIGIN_CHANNEL_FIELD] = context.last_input_origin
    metadata.update(context.channel_identifiers)
    return ConversationFacts(
        computer=context.computer or config.computer.name,
        project_path=context.project_path,
        title=title,
        human_email=context.human_email,
        visibility=context.visibility,
        command=context.command,
        todo=context.todo,
        is_worker=is_focused_role(context.role),
        metadata=metadata,
    )


def _changed(update: SourceUpdate, plan: _SourcePlan) -> bool:
    """Whether a source's observation differs from what the store holds."""
    stored = plan.stored
    if update.messages is not None or stored is None or (stored.missing_at is not None) != update.missing:
        return True
    return (update.file_size is not None and stored.file_size != update.file_size) or (
        update.file_mtime_ns is not None and stored.file_mtime_ns != update.file_mtime_ns
    )


@dataclass(frozen=True)
class _Reached:
    """What a refresh established about coverage, whichever way it wrote."""

    session_id: str
    covered_at: str
    ready: bool
    config_subject: str | None
    previously_ready: bool
    outcomes: dict[str, SourceReadOutcome]

    def coverage(self, recorded: RecordedCoverage, *, text_changed: bool) -> MirrorCoverage:
        """The coverage one recording committed: its time, readiness, count and completeness, never mixed."""
        return MirrorCoverage(
            session_id=self.session_id,
            covered_at=recorded.covered_at or self.covered_at,
            ready=recorded.ready,
            complete=not recorded.missing_sources,
            missing_sources=recorded.missing_sources,
            message_count=recorded.message_count,
            text_changed=text_changed,
            source_outcomes=self.outcomes,
            config_subject=self.config_subject,
            previously_ready=self.previously_ready,
        )

    def unrecorded(self) -> MirrorCoverage:
        """The coverage of a refresh that found no source to record anything for."""
        return MirrorCoverage(
            session_id=self.session_id,
            covered_at=self.covered_at,
            ready=self.ready,
            complete=True,
            missing_sources=(),
            message_count=0,
            text_changed=False,
            source_outcomes=self.outcomes,
            config_subject=self.config_subject,
            previously_ready=self.previously_ready,
        )


def refresh_session_mirror_sync(
    session_id: str,
    *,
    db: str | Path | None,
    trigger: MirrorWriteTrigger,
    reconcile_id: str | None = None,
) -> MirrorCoverage | None:
    """Refresh one session's conversation mirror from its complete transcript lineage.

    Each source is read through the shared conversation chain projector, only when its file or the
    derivation rules changed. Stored content survives a missing, unreadable, empty or shorter source.
    An unchanged conversation only has its coverage time stamped. ``None`` means no session record
    exists for the id.
    """
    context = get_session_context(session_id=session_id)
    if context is None:
        logger.debug("Mirror refresh skipped: session context missing", session_id=session_id)
        return None
    lineage = _lineage_plans(context)
    state = get_conversation_state(session_id=session_id, source_identities=[plan.identity for plan in lineage], db=db)
    plans = [replace(plan, stored=state.source(plan.identity) if state else None) for plan in lineage]
    updates: list[SourceUpdate] = []
    outcomes: dict[str, SourceReadOutcome] = {}
    for plan in plans:
        update, outcome = _observe_source(plan, db)
        outcomes[plan.identity] = outcome
        if update is not None:
            updates.append(update)
    reached = _Reached(
        session_id=session_id,
        covered_at=datetime.now(UTC).isoformat(),
        ready=SourceReadOutcome.FAILED not in outcomes.values(),
        config_subject=context.subject,
        previously_ready=state.coverage_ready if state else False,
        outcomes=outcomes,
    )
    plan_by_identity = {plan.identity: plan for plan in plans}
    unchanged = state is not None and not any(
        _changed(update, plan_by_identity[update.source_identity]) for update in updates
    )
    if state is not None and (not updates or unchanged):
        recorded = stamp_coverage(state.mirror_id, covered_at=reached.covered_at, ready=reached.ready, db=db)
        return reached.coverage(recorded, text_changed=False)
    if not updates:
        return reached.unrecorded()
    result = write_conversation(
        ConversationUpdate(
            facts=_facts(context, state, updates),
            attribution=_attribution(context),
            sources=tuple(updates),
            covered_at=reached.covered_at,
            ready=reached.ready,
        ),
        db=db,
    )
    logger.info(
        MIRROR_COVERAGE_RECORDED_EVENT,
        trigger=trigger,
        reconcile_id=reconcile_id,
        session_id=session_id,
        ready=result.coverage.ready,
        missing_sources=len(result.coverage.missing_sources),
        sources=len(updates),
        message_count=result.coverage.message_count,
        text_changed=result.text_changed,
    )
    for identity, outcome in outcomes.items():
        if outcome is SourceReadOutcome.SHRINK_ACCEPTED:
            logger.info(MIRROR_SHRINK_ACCEPTED, source_identity=identity, outcome=outcome)
    return reached.coverage(result.coverage, text_changed=result.text_changed)


async def refresh_session_mirror(
    session_id: str,
    *,
    db: str | Path | None,
    trigger: MirrorWriteTrigger,
    reconcile_id: str | None = None,
) -> MirrorCoverage | None:
    """Async entry point that offloads blocking mirror refresh work."""
    return await asyncio.to_thread(
        refresh_session_mirror_sync,
        session_id,
        db=db,
        trigger=trigger,
        reconcile_id=reconcile_id,
    )
