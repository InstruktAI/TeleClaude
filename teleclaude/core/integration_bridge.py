"""Bridge between orchestration lifecycle and the event platform.

Provides typed emission helpers that construct EventEnvelopes and emit
them through the configured EventProducer. Also provides the integrator
session spawn helper used by the integration trigger cartridge.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import ROLE_INTEGRATOR, JobRole
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.integration.checkpoint import ParkedCandidate
from teleclaude.core.models import (
    AgentDispatchMode,
    HumanActionIntent,
    SessionEntryPoint,
    SessionLaunchIntent,
    SessionLaunchKind,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.producer import emit_event
from teleclaude.events.schemas.software_development import IntegrationEventType
from teleclaude.session_identity import get_session_id
from teleclaude.types.commands import CreateSessionCommand

logger = get_logger(__name__)

_SOFTWARE_DEVELOPMENT_DOMAIN = "software-development"
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
    approved_at: str | None = None,
) -> str:
    """Emit review.approved when a build review verdict stamps as approve."""
    ts = approved_at or datetime.now(UTC).isoformat()
    return await emit_event(
        event="domain.software-development.review.approved",
        source=f"orchestrator/{(get_session_id() or 'unknown')}",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        description=f"Review approved for {slug} (round {review_round})",
        entity=slug,
        payload={
            "slug": slug,
            "review_round": review_round,
            "reviewer_session_id": reviewer_session_id,
            "approved_at": ts,
        },
    )


async def emit_deployment_completed(
    slug: str,
    branch: str,
    sha: str,
    merge_commit: str,
    *,
    integrated_at: str | None = None,
) -> str:
    """Emit deployment.completed after successful integration to main."""
    ts = integrated_at or datetime.now(UTC).isoformat()
    return await emit_event(
        event="domain.software-development.deployment.completed",
        source=f"integrator/{(get_session_id() or 'unknown')}",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        description=f"Deployment completed for {slug} (merge {merge_commit[:8]})",
        entity=slug,
        payload={
            "slug": slug,
            "branch": branch,
            "sha": sha,
            "merge_commit": merge_commit,
            "integrated_at": ts,
        },
    )


async def emit_deployment_failed(
    slug: str,
    branch: str,
    sha: str,
    *,
    conflict_evidence: list[str] | None = None,
    diagnostics: list[str] | None = None,
    next_action: str = "",
    blocked_at: str | None = None,
) -> str:
    """Emit deployment.failed when integration is blocked."""
    ts = blocked_at or datetime.now(UTC).isoformat()
    return await emit_event(
        event="domain.software-development.deployment.failed",
        source=f"integrator/{(get_session_id() or 'unknown')}",
        level=EventLevel.BUSINESS,
        domain="software-development",
        description=f"Deployment failed for {slug} ({branch}@{sha[:8]})",
        entity=slug,
        payload={
            "slug": slug,
            "branch": branch,
            "sha": sha,
            "conflict_evidence": conflict_evidence or [],
            "diagnostics": diagnostics or [],
            "next_action": next_action,
            "blocked_at": ts,
        },
        visibility=EventVisibility.LOCAL,
        human_action=HumanActionIntent(
            topic="Integration is blocked",
            summary=f"Deployment failed for {slug}.",
            action=next_action or "Investigate the integration failure",
        ),
    )


# ---------------------------------------------------------------------------
# Integration lifecycle event helpers (state machine emissions)
# ---------------------------------------------------------------------------


async def emit_integration_started(
    slug: str,
    session_id: str,
    queue_depth: int,
) -> str:
    """Emit integration.started when the state machine begins processing a candidate."""
    return await emit_event(
        event="domain.software-development.integration.started",
        source=f"integrator/{session_id or (get_session_id() or 'unknown')}",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        description=f"Integration started for {slug} (queue depth: {queue_depth})",
        entity=slug,
        payload={
            "slug": slug,
            "session_id": session_id,
            "queue_depth": queue_depth,
        },
    )


async def emit_integration_candidate_delivered(
    slug: str,
    branch: str,
    merge_commit_sha: str,
    *,
    integrated_at: str | None = None,
) -> str:
    """Emit integration.candidate.delivered after a candidate is fully integrated."""
    ts = integrated_at or datetime.now(UTC).isoformat()
    return await emit_event(
        event="domain.software-development.integration.candidate.delivered",
        source=f"integrator/{(get_session_id() or 'unknown')}",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        description=f"Candidate delivered: {slug} ({branch} \u2192 main, merge {merge_commit_sha[:8]})",
        entity=slug,
        payload={
            "slug": slug,
            "branch": branch,
            "merge_commit_sha": merge_commit_sha,
            "integrated_at": ts,
        },
    )


async def emit_integration_candidate_blocked(
    slug: str,
    branch: str,
    sha: str,
    *,
    reason: str = "",
    blocked_at: str | None = None,
) -> str:
    """Emit integration.candidate.blocked when a candidate cannot be integrated."""
    ts = blocked_at or datetime.now(UTC).isoformat()
    return await emit_event(
        event="domain.software-development.integration.candidate.blocked",
        source=f"integrator/{(get_session_id() or 'unknown')}",
        level=EventLevel.BUSINESS,
        domain="software-development",
        description=f"Integration blocked for {slug} ({branch}@{sha[:8]}): {reason or 'unknown reason'}",
        entity=slug,
        payload={
            "slug": slug,
            "branch": branch,
            "sha": sha,
            "reason": reason,
            "blocked_at": ts,
        },
        visibility=EventVisibility.LOCAL,
    )


async def emit_integration_candidate_parked(
    slug: str,
    branch: str,
    sha: str,
    reason: str,
    *,
    parked_at: str | None = None,
) -> str:
    """Emit integration.candidate.parked when a candidate is set aside."""
    ts = parked_at or datetime.now(UTC).isoformat()
    session_id = get_session_id() or _UNKNOWN_SESSION
    return await emit_event(
        event=IntegrationEventType.CANDIDATE_PARKED,
        source=_INTEGRATOR_SOURCE.format(session_id=session_id),
        level=EventLevel.BUSINESS,
        domain=_SOFTWARE_DEVELOPMENT_DOMAIN,
        description=_CANDIDATE_PARKED_DESCRIPTION.format(
            slug=slug,
            branch=branch,
            sha=sha[:8],
            reason=reason,
        ),
        entity=slug,
        payload={
            "slug": slug,
            "branch": branch,
            "sha": sha,
            "reason": reason,
            "parked_at": ts,
        },
        visibility=EventVisibility.LOCAL,
    )


async def emit_integration_drain_completed(
    session_id: str,
    delivered_count: int,
    parked: list[ParkedCandidate],
    *,
    completed_at: str | None = None,
) -> str:
    """Emit integration.drain.completed with the drain's complete outcome."""
    ts = completed_at or datetime.now(UTC).isoformat()
    source_session_id = session_id or (get_session_id() or _UNKNOWN_SESSION)
    return await emit_event(
        event=IntegrationEventType.DRAIN_COMPLETED,
        source=_INTEGRATOR_SOURCE.format(session_id=source_session_id),
        level=EventLevel.BUSINESS,
        domain=_SOFTWARE_DEVELOPMENT_DOMAIN,
        description=_DRAIN_COMPLETED_DESCRIPTION.format(
            delivered_count=delivered_count,
            parked_count=len(parked),
        ),
        entity=source_session_id,
        payload={
            "session_id": source_session_id,
            "delivered_count": delivered_count,
            "parked": [dict(candidate) for candidate in parked],
            "completed_at": ts,
        },
        visibility=EventVisibility.LOCAL,
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

    Returns session info dict on spawn, or None if an integrator is already open
    for this project.
    Raises on spawn failure — the caller (cartridge) is responsible for handling.
    """
    try:
        sessions = await db.list_sessions()
    except Exception:
        logger.exception("Could not check for running integrator sessions for %s; refusing duplicate spawn", slug)
        raise

    integrator_session = next(
        (s for s in sessions if s.job == JobRole.INTEGRATOR and s.project_path == project_path),
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

    cmd = CreateSessionCommand(
        project_path=project_path,
        origin=InputOrigin.TERMINAL.value,
        initial_input="/next-integrate",
        launch_intent=SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
            thinking_mode="slow",
            message="/next-integrate",
            dispatch_mode=AgentDispatchMode.AUTOMATIC,
        ),
        system_role=ROLE_INTEGRATOR,
        job=JobRole.INTEGRATOR.value,
        entry_point=SessionEntryPoint.INTEGRATION,
        skip_listener_registration=True,
        initiator_session_id=caller_session_id,
        initiator_computer=config.computer.name,
    )
    await get_command_service().create_session(cmd)
    logger.info("Spawned integrator session for %s (caller=%s)", slug, caller_session_id)
    return _SpawnResult(status="spawned", slug=slug)
