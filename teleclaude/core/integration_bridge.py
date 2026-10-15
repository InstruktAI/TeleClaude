"""Bridge between orchestration lifecycle and the event platform.

Provides typed emission helpers that construct typed events and publish
them through the configured EventProducer. Also provides the integrator
session spawn helper used by the integration trigger consumer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.integration.checkpoint import ParkedCandidate
from teleclaude.core.models import (
    AgentDispatchMode,
    SessionEntryPoint,
    SessionLaunchIntent,
    SessionLaunchKind,
)
from teleclaude.core.next_machine.lanes import LifecycleProcedure
from teleclaude.core.origins import InputOrigin
from teleclaude.core.procedure_entry import EntryContext, EntryRefusal, resolve_entry
from teleclaude.core.roles import RoleName
from teleclaude.events.envelope import EventHome, EventLevel, EventVisibility
from teleclaude.events.producer import publish_event
from teleclaude.events.references import SessionRef, TodoRef
from teleclaude.events.schemas.sdlc import (
    CandidateBlockedData,
    CandidateDeliveredData,
    CandidateParkedData,
    DrainCompletedData,
    IntegrationCandidateBlocked,
    IntegrationCandidateDelivered,
    IntegrationCandidateParked,
    IntegrationDrainCompleted,
    IntegrationStarted,
    IntegrationStartedData,
    ParkedCandidateData,
    ReviewApproved,
    ReviewApprovedData,
)
from teleclaude.events.wire import LegacyFacts
from teleclaude.session_identity import get_session_id
from teleclaude.types.commands import CreateSessionCommand

logger = get_logger(__name__)

_SDLC_DOMAIN = "sdlc"
_UNKNOWN_SESSION = "unknown"
_INTEGRATOR_SOURCE = "integrator/{session_id}"
_CANDIDATE_PARKED_DESCRIPTION = "Candidate parked: {slug} ({branch}@{sha}): {reason}"
_DRAIN_COMPLETED_DESCRIPTION = "Integration drain completed: {delivered_count} delivered, {parked_count} parked"


# ---------------------------------------------------------------------------
# Event emission helpers
# ---------------------------------------------------------------------------


async def emit_review_approved(
    slug: str,
    reviewer_session_id: str,
    review_round: int,
    *,
    home: EventHome,
    approved_at: str | None = None,
) -> str:
    """Emit review.approved when a build review verdict stamps as approve."""
    ts = approved_at or datetime.now(UTC).isoformat()
    return await publish_event(
        ReviewApproved(
            subject=TodoRef(slug),
            home=home,
            data=ReviewApprovedData(
                slug=slug,
                review_round=review_round,
                reviewer_session_id=reviewer_session_id,
                approved_at=ts,
            ),
        ),
        LegacyFacts(
            producer=f"orchestrator/{(get_session_id() or 'unknown')}",
            level=EventLevel.WORKFLOW,
            domain=_SDLC_DOMAIN,
            entity=slug,
            description=f"Review approved for {slug} (round {review_round})",
        ),
    )


# ---------------------------------------------------------------------------
# Integration lifecycle event helpers (state machine emissions)
# ---------------------------------------------------------------------------


async def emit_integration_started(
    slug: str,
    session_id: str,
    queue_depth: int,
    *,
    home: EventHome,
) -> str:
    """Emit integration.started when the state machine begins processing a candidate."""
    return await publish_event(
        IntegrationStarted(
            subject=TodoRef(slug),
            home=home,
            data=IntegrationStartedData(slug=slug, session_id=session_id, queue_depth=queue_depth),
        ),
        LegacyFacts(
            producer=_INTEGRATOR_SOURCE.format(session_id=session_id or (get_session_id() or _UNKNOWN_SESSION)),
            level=EventLevel.WORKFLOW,
            domain=_SDLC_DOMAIN,
            entity=slug,
            description=f"Integration started for {slug} (queue depth: {queue_depth})",
        ),
    )


async def emit_integration_candidate_delivered(
    slug: str,
    branch: str,
    merge_commit_sha: str,
    *,
    home: EventHome,
    integrated_at: str | None = None,
) -> str:
    """Emit integration.candidate.delivered after a candidate is fully integrated."""
    ts = integrated_at or datetime.now(UTC).isoformat()
    return await publish_event(
        IntegrationCandidateDelivered(
            subject=TodoRef(slug),
            home=home,
            data=CandidateDeliveredData(
                slug=slug,
                branch=branch,
                merge_commit_sha=merge_commit_sha,
                integrated_at=ts,
            ),
        ),
        LegacyFacts(
            producer=_INTEGRATOR_SOURCE.format(session_id=get_session_id() or _UNKNOWN_SESSION),
            level=EventLevel.WORKFLOW,
            domain=_SDLC_DOMAIN,
            entity=slug,
            description=f"Candidate delivered: {slug} ({branch} \u2192 main, merge {merge_commit_sha[:8]})",
        ),
    )


async def emit_integration_candidate_blocked(
    slug: str,
    branch: str,
    sha: str,
    *,
    home: EventHome,
    reason: str = "",
    blocked_at: str | None = None,
) -> str:
    """Emit integration.candidate.blocked when a candidate cannot be integrated."""
    ts = blocked_at or datetime.now(UTC).isoformat()
    return await publish_event(
        IntegrationCandidateBlocked(
            subject=TodoRef(slug),
            home=home,
            data=CandidateBlockedData(slug=slug, branch=branch, sha=sha, reason=reason, blocked_at=ts),
        ),
        LegacyFacts(
            producer=_INTEGRATOR_SOURCE.format(session_id=get_session_id() or _UNKNOWN_SESSION),
            level=EventLevel.BUSINESS,
            domain=_SDLC_DOMAIN,
            visibility=EventVisibility.LOCAL,
            entity=slug,
            description=f"Integration blocked for {slug} ({branch}@{sha[:8]}): {reason or 'unknown reason'}",
        ),
    )


async def emit_integration_candidate_parked(
    slug: str,
    branch: str,
    sha: str,
    reason: str,
    *,
    home: EventHome,
    parked_at: str | None = None,
) -> str:
    """Emit integration.candidate.parked when a candidate is set aside."""
    ts = parked_at or datetime.now(UTC).isoformat()
    session_id = get_session_id() or _UNKNOWN_SESSION
    return await publish_event(
        IntegrationCandidateParked(
            subject=TodoRef(slug),
            home=home,
            data=CandidateParkedData(slug=slug, branch=branch, sha=sha, reason=reason, parked_at=ts),
        ),
        LegacyFacts(
            producer=_INTEGRATOR_SOURCE.format(session_id=session_id),
            level=EventLevel.BUSINESS,
            domain=_SDLC_DOMAIN,
            visibility=EventVisibility.LOCAL,
            entity=slug,
            description=_CANDIDATE_PARKED_DESCRIPTION.format(slug=slug, branch=branch, sha=sha[:8], reason=reason),
        ),
    )


async def emit_integration_drain_completed(
    session_id: str,
    delivered_count: int,
    parked: list[ParkedCandidate],
    *,
    home: EventHome,
    completed_at: str | None = None,
) -> str:
    """Emit integration.drain.completed with the drain's complete outcome."""
    ts = completed_at or datetime.now(UTC).isoformat()
    source_session_id = session_id or (get_session_id() or _UNKNOWN_SESSION)
    return await publish_event(
        IntegrationDrainCompleted(
            subject=SessionRef(source_session_id),
            home=home,
            data=DrainCompletedData(
                session_id=source_session_id,
                delivered_count=delivered_count,
                parked=[ParkedCandidateData(**candidate) for candidate in parked],
                completed_at=ts,
            ),
        ),
        LegacyFacts(
            producer=_INTEGRATOR_SOURCE.format(session_id=source_session_id),
            level=EventLevel.BUSINESS,
            domain=_SDLC_DOMAIN,
            visibility=EventVisibility.LOCAL,
            entity=source_session_id,
            description=_DRAIN_COMPLETED_DESCRIPTION.format(delivered_count=delivered_count, parked_count=len(parked)),
        ),
    )


# ---------------------------------------------------------------------------
class _SpawnResult(TypedDict, total=False):
    status: str
    slug: str


# Integrator session spawn/wake
# ---------------------------------------------------------------------------


async def spawn_integrator_session(
    slug: str,
    branch: str,
    sha: str,
    caller_session_id: str,
    project_path: str,
) -> _SpawnResult | None:
    """Spawn the per-project singleton integrator session when none is already open.

    Checks if an integrator session is already running for this ``project_path``
    via the DB directly. The singleton is scoped per project: an integrator
    running in another project never blocks a spawn here.
    If one is already running for this project, leaves it undisturbed; the
    integrator state machine drains queued candidates on its next pass.
    If none is running for this project, spawns a fresh integrator via the
    command service.

    The integrator is an independent platform activation: it records no initiator, so it is never in the claiming group
    of the driver whose stamp caused it. ``caller_session_id`` names the requester for the log and the notice only.

    Returns session info dict on spawn, or None if an integrator is already open
    for this project.
    Raises on spawn failure — the caller (the integration trigger consumer) is responsible for handling.
    """
    try:
        sessions = await db.list_sessions()
    except Exception:
        logger.exception("Could not check for running integrator sessions for %s; refusing duplicate spawn", slug)
        raise

    integrator_session = next(
        (s for s in sessions if s.role == RoleName.INTEGRATOR and s.project_path == project_path),
        None,
    )
    if integrator_session:
        logger.debug(
            "integration.candidate.spawner_skipped_existing_integrator",
            slug=slug,
            branch=branch,
            sha=sha[:8],
            session_id=integrator_session.session_id,
        )
        return None

    # Caller identity is only required when spawning a new integrator session
    if not caller_session_id or caller_session_id == "unknown":
        raise ValueError(f"Cannot spawn integrator for {slug}: missing caller session identity")
    if not project_path:
        raise ValueError(f"Cannot spawn integrator for {slug}: missing project_path")

    session_id = str(uuid.uuid4())
    try:
        resolved = resolve_entry(
            procedure_token=LifecycleProcedure.INTEGRATE.value,
            arguments="",
            project_root=Path(project_path),
            caller=None,
            entry=EntryContext(),
            caller_mode=None,
        )
    except EntryRefusal as exc:
        raise ValueError(f"Cannot spawn integrator for {slug}: {exc.detail}") from exc
    cmd = CreateSessionCommand(
        session_id=session_id,
        project_path=project_path,
        origin=InputOrigin.TERMINAL.value,
        command=resolved.procedure_id,
        initial_input=resolved.procedure_id,
        launch_intent=SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
            thinking_mode=resolved.thinking_mode.value,
            message=resolved.loader,
            dispatch_mode=AgentDispatchMode.AUTOMATIC,
            candidate_order=resolved.agents,
            invocation=resolved.record,
        ),
        role=resolved.role.name.value,
        entry_point=SessionEntryPoint.INTEGRATION,
        skip_listener_registration=True,
    )
    await get_command_service().create_session(cmd)
    logger.info("Spawned integrator session for %s (caller=%s)", slug, caller_session_id)
    return _SpawnResult(status="spawned", slug=slug)
