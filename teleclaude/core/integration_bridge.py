"""Bridge between orchestration lifecycle and the event platform.

Provides typed emission helpers that construct EventEnvelopes and emit
them through the configured EventProducer.  Also provides the integrator
session spawn/wake helper used by the integration trigger cartridge.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import TypedDict

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


async def emit_branch_pushed(
    branch: str,
    sha: str,
    remote: str,
    *,
    pushed_at: str | None = None,
    pusher: str = "",
) -> str:
    """Emit branch.pushed when a worktree branch is pushed to origin before integration."""
    ts = pushed_at or datetime.now(timezone.utc).isoformat()
    return await emit_event(
        event="domain.software-development.branch.pushed",
        source=f"finalizer/{os.environ.get('TELECLAUDE_SESSION_ID', 'unknown')}",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        description=f"Branch pushed: {remote}/{branch}@{sha[:8]}",
        entity=branch,
        payload={
            "branch": branch,
            "sha": sha,
            "remote": remote,
            "pushed_at": ts,
            "pusher": pusher or f"orchestrator/{os.environ.get('TELECLAUDE_SESSION_ID', 'unknown')}",
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
        source=f"integrator/{session_id or os.environ.get('TELECLAUDE_SESSION_ID', 'unknown')}",
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
    ts = integrated_at or datetime.now(timezone.utc).isoformat()
    return await emit_event(
        event="domain.software-development.integration.candidate.delivered",
        source=f"integrator/{os.environ.get('TELECLAUDE_SESSION_ID', 'unknown')}",
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
    ts = blocked_at or datetime.now(timezone.utc).isoformat()
    return await emit_event(
        event="domain.software-development.integration.candidate.blocked",
        source=f"integrator/{os.environ.get('TELECLAUDE_SESSION_ID', 'unknown')}",
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
) -> _SpawnResult | None:
    """Spawn or wake the singleton integrator session.

    Checks if an integrator session is already running. If not, spawns one
    via ``telec sessions start`` with the integrator system role. The
    integrator drains the durable queue itself, so the wake-up command stays
    generic and does not target a specific slug. If one is already running,
    the candidate is already queued and the running integrator will drain it.

    Returns session info dict on spawn, or None if integrator already active.
    """
    import asyncio

    try:
        result = await asyncio.to_thread(_spawn_integrator_sync, slug, branch, sha)
        return result
    except Exception:
        logger.exception("Failed to spawn integrator session for %s", slug)
        return None


def _spawn_integrator_sync(slug: str, branch: str, sha: str) -> _SpawnResult | None:
    """Synchronous helper — check for running integrator and spawn if needed."""
    import subprocess

    # Check if an integrator session is already running via structured job filter.
    try:
        list_result = subprocess.run(
            ["telec", "sessions", "list", "--all", "--job", "integrator"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if list_result.returncode != 0:
            logger.warning(
                "Integrator guard check failed (exit %d); proceeding to spawn. stderr: %s",
                list_result.returncode,
                (list_result.stderr or "").strip() or "(empty)",
            )
        else:
            sessions = json.loads(list_result.stdout)
            if sessions:
                logger.info("Integrator session already running; candidate %s queued for drain", slug)
                return None
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        logger.warning("Could not check for running integrator sessions")

    # Spawn a new queue-draining integrator session with parity evidence for main push authorization.
    project_path = os.environ.get("TELECLAUDE_PROJECT_PATH", os.getcwd())
    spawn_env = os.environ.copy()
    spawn_env["TELECLAUDE_INTEGRATOR_PARITY_EVIDENCE"] = "accepted"
    try:
        start_result = subprocess.run(
            [
                "telec",
                "sessions",
                "run",
                "--command",
                "/next-integrate",
                "--project",
                project_path,
                "--detach",
            ],
            env=spawn_env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if start_result.returncode == 0:
            logger.info("Spawned integrator session for %s", slug)
            return _SpawnResult(status="spawned", slug=slug)
        else:
            logger.error("Failed to spawn integrator: %s", start_result.stderr or start_result.stdout)
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.error("Integrator spawn failed: %s", exc)
        return None
