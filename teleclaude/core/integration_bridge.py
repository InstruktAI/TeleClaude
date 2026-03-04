"""Bridge between orchestration lifecycle and the event platform.

Provides typed emission helpers that construct EventEnvelopes and emit
them through the configured EventProducer.  Also provides the integrator
session spawn/wake helper used by the integration trigger cartridge.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from teleclaude_events.envelope import EventLevel, EventVisibility
from teleclaude_events.producer import emit_event

logger = logging.getLogger(__name__)


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
    """Emit review.approved when mark-phase review approved succeeds."""
    ts = approved_at or datetime.now(timezone.utc).isoformat()
    return await emit_event(
        event="domain.software-development.review.approved",
        source=f"orchestrator/{os.environ.get('TELECLAUDE_SESSION_ID', 'unknown')}",
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


async def emit_deployment_started(
    slug: str,
    branch: str,
    sha: str,
    *,
    worker_session_id: str = "",
    orchestrator_session_id: str = "",
    ready_at: str | None = None,
) -> str:
    """Emit deployment.started when a finalizer reports FINALIZE_READY."""
    ts = ready_at or datetime.now(timezone.utc).isoformat()
    return await emit_event(
        event="domain.software-development.deployment.started",
        source=f"orchestrator/{orchestrator_session_id or os.environ.get('TELECLAUDE_SESSION_ID', 'unknown')}",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        description=f"Deployment started for {slug} ({branch}@{sha[:8]})",
        entity=slug,
        payload={
            "slug": slug,
            "branch": branch,
            "sha": sha,
            "worker_session_id": worker_session_id,
            "orchestrator_session_id": orchestrator_session_id,
            "ready_at": ts,
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
    ts = integrated_at or datetime.now(timezone.utc).isoformat()
    return await emit_event(
        event="domain.software-development.deployment.completed",
        source=f"integrator/{os.environ.get('TELECLAUDE_SESSION_ID', 'unknown')}",
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
    ts = blocked_at or datetime.now(timezone.utc).isoformat()
    return await emit_event(
        event="domain.software-development.deployment.failed",
        source=f"integrator/{os.environ.get('TELECLAUDE_SESSION_ID', 'unknown')}",
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
    )


# ---------------------------------------------------------------------------
# Integrator session spawn/wake
# ---------------------------------------------------------------------------


async def spawn_integrator_session(
    slug: str,
    branch: str,
    sha: str,
) -> dict[str, Any] | None:
    """Spawn or wake the singleton integrator session.

    Checks if an integrator session is already running.  If not, spawns one
    via ``telec sessions start`` with the integrator system role.  If one is
    already running, the candidate is already queued and the running
    integrator will drain it.

    Returns session info dict on spawn, or None if integrator already active.
    """
    import asyncio

    try:
        result = await asyncio.to_thread(
            _spawn_integrator_sync, slug, branch, sha
        )
        return result
    except Exception:
        logger.exception("Failed to spawn integrator session for %s", slug)
        return None


def _spawn_integrator_sync(
    slug: str, branch: str, sha: str
) -> dict[str, Any] | None:
    """Synchronous helper — check for running integrator and spawn if needed."""
    import json
    import subprocess

    # Check if an integrator session is already running
    try:
        list_result = subprocess.run(
            ["telec", "sessions", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if list_result.returncode == 0 and "integrator" in list_result.stdout.lower():
            logger.info(
                "Integrator session already running; candidate %s queued for drain", slug
            )
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.warning("Could not check for running integrator sessions")

    # Spawn a new integrator session
    project_path = os.environ.get("TELECLAUDE_PROJECT_PATH", os.getcwd())
    try:
        start_result = subprocess.run(
            [
                "telec",
                "sessions",
                "start",
                "--project",
                project_path,
                "--message",
                f"/next-integrate {slug} --branch {branch} --sha {sha}",
                "--title",
                f"integrator: {slug}",
                "--detach",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if start_result.returncode == 0:
            logger.info("Spawned integrator session for %s", slug)
            try:
                return json.loads(start_result.stdout)
            except json.JSONDecodeError:
                return {"status": "spawned", "slug": slug}
        else:
            logger.error(
                "Failed to spawn integrator: %s", start_result.stderr or start_result.stdout
            )
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.error("Integrator spawn failed: %s", exc)
        return None
