"""Deterministic state machine for integration lifecycle management.

Implements `next_integrate()` — the entry point for `telec todo integrate`.
Each call reads a durable checkpoint, executes the next deterministic step,
and returns structured instructions at decision points where agent intelligence
is required.

The state machine is the authority on sequencing.
The agent is the authority on intelligence. Neither does the other's job.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from time import perf_counter

from instrukt_ai_logging import get_logger

from teleclaude.core.db import Db
from teleclaude.core.integration.checkpoint import (
    IntegrationCheckpoint,
    IntegrationPhase,
    _default_state_dir,
    _read_checkpoint,
    _write_checkpoint,
)
from teleclaude.core.integration.formatters import _format_error, _format_queue_empty
from teleclaude.core.integration.lease import IntegrationLeaseStore
from teleclaude.core.integration.step_functions import (
    _NEXT_INTEGRATE_PHASE_LOG,
    _do_merge,
    _get_candidate_key,
    _run_git,
    _step_awaiting_commit,
    _step_cleanup,
    _step_committed,
    _step_delivery_bookkeeping,
    _step_idle,
    _step_push_rejected,
    _step_push_succeeded,
    _tls,
)

logger = get_logger(__name__)

_LOOP_LIMIT = 50  # safety cap on internal state transitions per call

# Re-export IntegrationPhase for backward compatibility
# (external code imports it from this module)
__all__ = ["IntegrationPhase", "next_integrate"]


# ---------------------------------------------------------------------------
# Core phase dispatch (synchronous inner loop)
# ---------------------------------------------------------------------------


def _dispatch_sync(
    *,
    session_id: str,
    slug: str | None,
    cwd: str,
    state_dir: Path,
    started: float,
    loop: asyncio.AbstractEventLoop | None = None,
) -> str:
    """Synchronous state machine loop. Returns instruction string for the agent."""
    _tls.loop = loop
    checkpoint_path = state_dir / "integrate-state.json"
    lease_store = IntegrationLeaseStore(state_path=state_dir / "lease.json")

    # Sync repo root with origin/main on every entry.
    # The integration worktree pushes directly to origin/main; without this
    # pull, repo root diverges and cleanup commits cause merge conflicts.
    rc, _, stderr = _run_git(["pull", "--ff-only", "origin", "main"], cwd=cwd)
    if rc != 0:
        return _format_error(
            "REPO_ROOT_DIVERGED",
            f"git pull --ff-only origin main failed on repo root:\n{stderr.strip()}\n\n"
            "Repo root main has diverged from origin/main. "
            "Resolve the divergence (merge or reset to origin/main) before re-running integration.",
        )

    # Reset session-scoped counters on fresh entry so they reflect only this
    # run's work, not accumulated totals from previous integrator sessions.
    initial_checkpoint = _read_checkpoint(checkpoint_path)
    if initial_checkpoint.phase == IntegrationPhase.IDLE.value:
        initial_checkpoint.items_processed = 0
        initial_checkpoint.items_blocked = 0
        _write_checkpoint(checkpoint_path, initial_checkpoint)

    for _iter in range(_LOOP_LIMIT):
        checkpoint = _read_checkpoint(checkpoint_path)

        try:
            phase = IntegrationPhase(checkpoint.phase)
        except ValueError:
            return _format_error("UNKNOWN_PHASE", f"Unrecognised checkpoint phase: {checkpoint.phase!r}")

        logger.info(
            "%s slug=%s phase=%s session=%s iter=%d",
            _NEXT_INTEGRATE_PHASE_LOG,
            checkpoint.candidate_slug or slug or "<auto>",
            phase.value,
            session_id,
            _iter,
        )

        # Each handler returns (continue_loop: bool, instruction: str)
        keep_going, instruction = _step(
            phase=phase,
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            lease_store=lease_store,
            session_id=session_id,
            slug=slug,
            cwd=cwd,
            started=started,
        )
        if not keep_going:
            return instruction

    return _format_error("LOOP_LIMIT", f"State machine exceeded {_LOOP_LIMIT} internal transitions")


def _step(
    *,
    phase: IntegrationPhase,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    lease_store: IntegrationLeaseStore,
    session_id: str,
    slug: str | None,
    cwd: str,
    started: float,
) -> tuple[bool, str]:
    """Execute one phase step. Returns (continue_loop, instruction_or_empty)."""
    if phase == IntegrationPhase.IDLE:
        return _step_idle(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            lease_store=lease_store,
            session_id=session_id,
            slug=slug,
            cwd=cwd,
            started=started,
        )

    if phase == IntegrationPhase.CANDIDATE_DEQUEUED:
        # After dequeue, go straight to merge (worktree isolation + push rejection
        # handle concurrency; no pre-flight clearance check needed).
        key = _get_candidate_key(checkpoint)
        if not key:
            return False, _format_error("INVALID_STATE", "CANDIDATE_DEQUEUED checkpoint missing candidate key")
        return _do_merge(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            key=key,
            cwd=cwd,
        )

    if phase in (IntegrationPhase.MERGE_CLEAN, IntegrationPhase.MERGE_CONFLICTED, IntegrationPhase.AWAITING_COMMIT):
        return _step_awaiting_commit(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            cwd=cwd,
        )

    if phase == IntegrationPhase.COMMITTED:
        return _step_committed(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            cwd=cwd,
        )

    if phase == IntegrationPhase.DELIVERY_BOOKKEEPING:
        return _step_delivery_bookkeeping(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            cwd=cwd,
        )

    if phase == IntegrationPhase.PUSH_REJECTED:
        return _step_push_rejected(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            cwd=cwd,
        )

    if phase == IntegrationPhase.PUSH_SUCCEEDED:
        return _step_push_succeeded(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            cwd=cwd,
        )

    if phase == IntegrationPhase.CLEANUP:
        return _step_cleanup(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            cwd=cwd,
        )

    if phase == IntegrationPhase.CANDIDATE_DELIVERED:
        # Reset and loop for next candidate
        checkpoint.phase = IntegrationPhase.IDLE.value
        checkpoint.candidate_slug = None
        checkpoint.candidate_branch = None
        checkpoint.candidate_sha = None
        checkpoint.lease_token = None
        checkpoint.pre_merge_head = None
        checkpoint.error_context = None
        _write_checkpoint(checkpoint_path, checkpoint)
        return True, ""  # loop

    if phase == IntegrationPhase.COMPLETED:
        elapsed_ms = int((perf_counter() - started) * 1000)
        return False, _format_queue_empty(checkpoint.items_processed, checkpoint.items_blocked, elapsed_ms)

    return False, _format_error("UNHANDLED_PHASE", f"No handler for phase: {phase.value}")


# ---------------------------------------------------------------------------
# Public async entry point
# ---------------------------------------------------------------------------


async def next_integrate(
    db: Db,  # pylint: disable=unused-argument — reserved for future DB-backed state
    slug: str | None,
    cwd: str,
    caller_session_id: str | None = None,
) -> str:
    """Integration state machine entry point.

    Reads current state from a durable checkpoint, executes the next
    deterministic step, and returns structured instructions at decision
    points where agent intelligence is required.

    Args:
        db: Database instance (reserved for future use).
        slug: Optional slug filter — must match next candidate in FIFO queue.
        cwd: Project root directory for git operations.
        caller_session_id: Session ID of the calling agent (lease owner).

    Returns:
        Plain text instruction block for the agent to execute.
    """
    session_id = caller_session_id or os.environ.get("TELECLAUDE_SESSION_ID", "unknown")
    started = perf_counter()
    state_dir = _default_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()

    return await asyncio.to_thread(
        _dispatch_sync,
        session_id=session_id,
        slug=slug,
        cwd=cwd,
        state_dir=state_dir,
        started=started,
        loop=loop,
    )
