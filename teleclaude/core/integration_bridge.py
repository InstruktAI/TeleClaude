"""Bridge between orchestration lifecycle and the event platform.

Provides typed emission helpers that construct typed events and publish
them through the configured EventProducer.
"""

from __future__ import annotations

from datetime import UTC, datetime

from teleclaude.core.integration.checkpoint import ParkedCandidate
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
