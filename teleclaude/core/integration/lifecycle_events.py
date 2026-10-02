"""Integration lifecycle event emission — fire-and-forget bridge dispatch.

No imports from state_machine.py or step_functions.py (circular-import guard).
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, cast

from instrukt_ai_logging import get_logger

from teleclaude.core import integration_bridge as bridge
from teleclaude.core.integration.checkpoint import ParkedCandidate
from teleclaude.events.envelope import EventSubject
from teleclaude.events.envelope_facts import subject_for_project_path

logger = get_logger(__name__)

# Thread-local storage for event loop reference (used in fire-and-forget async emission)
_tls = threading.local()

_EVENT_INTEGRATION_CANDIDATE_PARKED = "integration.candidate.parked"
_EVENT_INTEGRATION_DRAIN_COMPLETED = "integration.drain.completed"


def _workflow_subject_for_path(path: str | Path) -> EventSubject:
    """Resolve the registered workflow project for an integration root."""
    return subject_for_project_path(path)


# guard: loose-dict-func - lifecycle event payload shape varies per event type
async def _bridge_emit(
    event_type: str,
    payload: dict[str, Any],
    subject: EventSubject,
) -> None:
    """Dispatch lifecycle event to the appropriate integration_bridge helper."""
    # Lazy import to avoid circular dependency at module load time
    try:
        if event_type == "integration.started":
            await bridge.emit_integration_started(
                slug=payload.get("slug", ""),
                session_id=payload.get("session_id", ""),
                queue_depth=int(payload.get("queue_depth", 0)),
                subject=subject,
            )
        elif event_type == "integration.candidate.delivered":
            await bridge.emit_integration_candidate_delivered(
                slug=payload.get("slug", ""),
                branch=payload.get("branch", ""),
                merge_commit_sha=payload.get("merge_commit_sha", ""),
                subject=subject,
            )
        elif event_type == "integration.candidate.blocked":
            await bridge.emit_integration_candidate_blocked(
                slug=payload.get("slug", ""),
                branch=payload.get("branch", ""),
                sha=payload.get("sha", ""),
                reason=payload.get("reason", ""),
                subject=subject,
            )
        elif event_type == _EVENT_INTEGRATION_CANDIDATE_PARKED:
            await bridge.emit_integration_candidate_parked(
                slug=payload.get("slug", ""),
                branch=payload.get("branch", ""),
                sha=payload.get("sha", ""),
                reason=payload.get("reason", ""),
                parked_at=payload.get("parked_at") or None,
                subject=subject,
            )
        elif event_type == _EVENT_INTEGRATION_DRAIN_COMPLETED:
            await bridge.emit_integration_drain_completed(
                session_id=payload.get("session_id", ""),
                delivered_count=int(payload.get("delivered_count", 0)),
                parked=cast(list[ParkedCandidate], payload.get("parked", [])),
                completed_at=payload.get("completed_at") or None,
                subject=subject,
            )
        # Other event types are observability-only; logged below, not wired to bridge
    except Exception:
        logger.debug("_bridge_emit failed for %s", event_type, exc_info=True)


# guard: loose-dict-func - lifecycle event payload shape varies per event type
def _emit_lifecycle_event(
    event_type: str,
    payload: dict[str, Any],
    subject: EventSubject,
) -> None:
    """Fire-and-forget lifecycle event emission via bridge (threadsafe)."""
    logger.info("INTEGRATION_LIFECYCLE_EVENT type=%s payload=%s", event_type, payload)
    loop: asyncio.AbstractEventLoop | None = getattr(_tls, "loop", None)
    if loop is None or not loop.is_running():
        return
    try:
        asyncio.run_coroutine_threadsafe(_bridge_emit(event_type, payload, subject), loop)
    except Exception:
        logger.debug("_emit_lifecycle_event scheduling failed for %s", event_type, exc_info=True)


__all__ = [
    "_EVENT_INTEGRATION_CANDIDATE_PARKED",
    "_EVENT_INTEGRATION_DRAIN_COMPLETED",
    "_emit_lifecycle_event",
    "_tls",
    "_workflow_subject_for_path",
]
