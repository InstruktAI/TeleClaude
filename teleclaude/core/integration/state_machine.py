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
from pathlib import Path
from time import perf_counter

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.db import Db
from teleclaude.core.integration.checkpoint import (
    IntegrationCheckpoint,
    IntegrationPhase,
    _default_state_dir,
    _get_candidate_key,
    _read_checkpoint,
    _reset_candidate,
    _write_checkpoint,
)
from teleclaude.core.integration.delivery_fold import (
    DeliveredMarkerRecoveryFault,
    UnrepairableMarkerDivergence,
    recover_delivered_marker_divergence,
)
from teleclaude.core.integration.formatters import (
    _format_error,
    _format_queue_empty,
    _format_repo_root_sync_instruction,
)
from teleclaude.core.integration.git_ops import (
    RepoRootSyncOutcome,
    RepoRootSyncStage,
    _mark_repo_root_sync_failure,
    _publish_repo_root_main,
    _run_git,
    _synchronize_repo_root,
)
from teleclaude.core.integration.lease import IntegrationLeaseStore
from teleclaude.core.integration.lifecycle_events import _tls
from teleclaude.core.integration.push_recovery import _step_content_gate_blocked, _step_push_rejected
from teleclaude.core.integration.step_functions import (
    _NEXT_INTEGRATE_PHASE_LOG,
    _do_merge,
    _step_awaiting_commit,
    _step_cleanup,
    _step_committed,
    _step_delivery_bookkeeping,
    _step_idle,
    _step_push_succeeded,
)
from teleclaude.core.operation_progress import emit_operation_progress
from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root
from teleclaude.core.todos_db import get_todos_db_sync
from teleclaude.runtime.command_runner import (
    ProcessGroupCancellation,
    ProcessGroupCancellationRequested,
    process_group_cancellation_scope,
)
from teleclaude.session_identity import get_session_id

logger = get_logger(__name__)

_LOOP_LIMIT = 50  # safety cap on internal state transitions per call
_REPO_ROOT_SYNC_PROGRESS_PHASE = "repo_root_sync"
_DELIVERED_MARKER_RECOVERY_FINISHED_EVENT = "integration.delivered_marker_recovery.finished"
_DELIVERED_MARKER_RECOVERY_FINISHED_LOG = "Delivered-marker recovery finished"
_DELIVERED_MARKER_RECOVERY_FAULTED_OUTCOME = "faulted"
_DELIVERED_MARKER_RECOVERY_PUBLISHED_OUTCOME = "published"
_PUBLICATION_CONFIRMATION_FAILED_OPERATION = "publication_confirmation"
_PUBLICATION_CONFIRMATION_FAILED_DIAGNOSTIC = "repo-root publication was not confirmed as synchronized"

# Re-export IntegrationPhase for backward compatibility
# (external code imports it from this module)
__all__ = ["IntegrationPhase", "next_integrate"]


# ---------------------------------------------------------------------------
# Core phase dispatch (synchronous inner loop)
# ---------------------------------------------------------------------------


def _candidate_belongs_to_project(checkpoint: IntegrationCheckpoint, *, cwd: str) -> bool:
    """True when the checkpoint's candidate has a branch or worktree in this project."""
    if checkpoint.candidate_branch:
        rc, _, _ = _run_git(["rev-parse", "--verify", f"refs/heads/{checkpoint.candidate_branch}"], cwd=cwd)
        if rc == 0:
            return True
    return (Path(cwd) / WORKTREE_DIR / (checkpoint.candidate_slug or "")).exists()


def _emit_repo_root_sync_progress(sync_id: str, outcome: str, loop: asyncio.AbstractEventLoop | None) -> None:
    """Publish one repo-root synchronization outcome to the operation receipt."""
    progress_args = (_REPO_ROOT_SYNC_PROGRESS_PHASE, outcome, sync_id)
    if loop is None:
        emit_operation_progress(*progress_args)
    else:
        loop.call_soon_threadsafe(emit_operation_progress, *progress_args)


def _log_delivered_marker_recovery_fault(
    fault: DeliveredMarkerRecoveryFault,
    *,
    session_id: str,
    sync_id: str,
) -> None:
    """Record one non-blocking delivered-marker reconciliation fault."""
    logger.error(
        _DELIVERED_MARKER_RECOVERY_FINISHED_LOG,
        event=_DELIVERED_MARKER_RECOVERY_FINISHED_EVENT,
        outcome=_DELIVERED_MARKER_RECOVERY_FAULTED_OUTCOME,
        session_id=session_id,
        sync_id=sync_id,
        slug=fault.receipt.slug,
        transition_id=fault.receipt.transition_id,
        reason=fault.receipt.reason,
        divergence_paths=tuple(finding.relative_path for finding in fault.divergences),
        divergence_lines=tuple(finding.line for finding in fault.divergences),
    )


def _log_delivered_marker_recovery_publication(
    *,
    session_id: str,
    sync_id: str,
    source_head: str,
    recovery_slug: str,
    recovery_commit: str,
    transition_id: str,
) -> None:
    """Record a delivered-marker recovery only after its root commit is published."""
    logger.info(
        _DELIVERED_MARKER_RECOVERY_FINISHED_LOG,
        event=_DELIVERED_MARKER_RECOVERY_FINISHED_EVENT,
        outcome=_DELIVERED_MARKER_RECOVERY_PUBLISHED_OUTCOME,
        session_id=session_id,
        sync_id=sync_id,
        slug=recovery_slug,
        source_head=source_head,
        recovery_commit=recovery_commit,
        transition_id=transition_id,
    )


def _format_recovery_fault_anomaly(fault: DeliveredMarkerRecoveryFault) -> str:
    """Describe one unfoldable slug as work the integrator completes by hand."""
    paths = ", ".join(sorted({finding.relative_path for finding in fault.divergences}))
    return (
        f"Delivered-marker fold did not apply for `{fault.receipt.slug}` ({fault.receipt.reason}). "
        f"Documentation lives on main and every `telec docs` read resolves there, so fold it there "
        f"yourself before ending this session. Affected: {paths or '(no path recorded)'}"
    )


def _format_unrepairable_anomaly(divergence: UnrepairableMarkerDivergence) -> str:
    """Describe a settled slug that is reported but deliberately not auto-folded."""
    paths = ", ".join(sorted({finding.relative_path for finding in divergence.divergences}))
    return (
        f"Settled slug `{divergence.slug}` (status {divergence.status}) still carries live markers. "
        f"No terminal fold is defined for this status, so none was attempted — resolve it on main "
        f"yourself. Affected: {paths or '(no path recorded)'}"
    )


def _recover_delivered_markers(
    *,
    cwd: str,
    session_id: str,
    loop: asyncio.AbstractEventLoop | None,
    sync_id: str,
) -> tuple[str | None, list[str]]:
    """Repair delivered-marker divergence, surfacing whatever would not fold.

    The machine folds what it can. What it cannot — almost always a path another
    session is holding dirty — is handed back as an anomaly rather than left in a
    log, because completing it is the integrator's work. It never blocks: a dirty
    path clears when its owner commits, and parking the queue on someone else's
    working tree helps nobody. It is re-derived on every idle entry instead, so it
    keeps being handed over until the fold actually lands and stops the moment it
    does.
    """
    recovery = recover_delivered_marker_divergence(Path(cwd), get_todos_db_sync(cwd).delivered_slugs_sync())
    anomalies: list[str] = []
    for fault in recovery.faults:
        _log_delivered_marker_recovery_fault(fault, session_id=session_id, sync_id=sync_id)
        anomalies.append(_format_recovery_fault_anomaly(fault))
    for divergence in recovery.unrepairable:
        anomalies.append(_format_unrepairable_anomaly(divergence))
    if not recovery.applied_receipts:
        return None, anomalies

    repo_root_sync = _synchronize_repo_root(cwd=cwd, session_id=session_id, stage=RepoRootSyncStage.ENTRY)
    _emit_repo_root_sync_progress(repo_root_sync.sync_id, repo_root_sync.outcome.value, loop)
    if not repo_root_sync.is_ready:
        return _format_repo_root_sync_instruction(repo_root_sync, project_root=cwd), anomalies
    if repo_root_sync.outcome is not RepoRootSyncOutcome.AHEAD_ONLY:
        return None, anomalies

    publication = _publish_repo_root_main(cwd=cwd, synchronization=repo_root_sync)
    if not publication.succeeded:
        return _format_repo_root_sync_instruction(publication.synchronization, project_root=cwd), anomalies
    confirmation = _synchronize_repo_root(cwd=cwd, session_id=session_id, stage=RepoRootSyncStage.ENTRY)
    _emit_repo_root_sync_progress(confirmation.sync_id, confirmation.outcome.value, loop)
    if not confirmation.is_ready:
        return _format_repo_root_sync_instruction(confirmation, project_root=cwd), anomalies
    if confirmation.outcome is RepoRootSyncOutcome.AHEAD_ONLY:
        failed_confirmation = _mark_repo_root_sync_failure(
            confirmation,
            outcome=RepoRootSyncOutcome.BOOKKEEPING_PUSH_FAILED,
            failed_operation=_PUBLICATION_CONFIRMATION_FAILED_OPERATION,
            diagnostic=_PUBLICATION_CONFIRMATION_FAILED_DIAGNOSTIC,
        )
        return _format_repo_root_sync_instruction(failed_confirmation, project_root=cwd), anomalies
    if publication.source_head is not None:
        for receipt in recovery.applied_receipts:
            if receipt.commit is not None:
                _log_delivered_marker_recovery_publication(
                    session_id=session_id,
                    sync_id=publication.synchronization.sync_id,
                    source_head=publication.source_head,
                    recovery_slug=receipt.slug,
                    recovery_commit=receipt.commit,
                    transition_id=receipt.transition_id,
                )
    return None, anomalies


def _dispatch_sync(
    *,
    session_id: str,
    slug: str | None,
    cwd: str,
    state_dir: Path,
    started: float,
    loop: asyncio.AbstractEventLoop | None = None,
    abandon: bool = False,
) -> str:
    """Synchronous state machine loop. Returns instruction string for the agent."""
    _tls.loop = loop

    resolved = str(resolve_project_root(cwd))
    if resolved != cwd:
        logger.info("Resolved cwd from worktree %s to repo root %s", cwd, resolved)
        cwd = resolved
    checkpoint_path = state_dir / "state.json"
    lease_store = IntegrationLeaseStore(state_path=state_dir / "lease.json")
    initial_checkpoint = _read_checkpoint(checkpoint_path)

    repo_root_sync = _synchronize_repo_root(
        cwd=cwd,
        session_id=session_id,
        stage=RepoRootSyncStage.ENTRY,
    )
    _emit_repo_root_sync_progress(repo_root_sync.sync_id, repo_root_sync.outcome.value, loop)
    if not repo_root_sync.is_ready:
        return _format_repo_root_sync_instruction(repo_root_sync, project_root=cwd)

    unfolded_anomalies: list[str] = []
    if initial_checkpoint.phase == IntegrationPhase.IDLE.value:
        recovery_instruction, unfolded_anomalies = _recover_delivered_markers(
            cwd=cwd, session_id=session_id, loop=loop, sync_id=repo_root_sync.sync_id
        )
        if recovery_instruction:
            return recovery_instruction

    # Reset session-scoped counters on fresh entry so they reflect only this
    # run's work, not accumulated totals from previous integrator sessions.
    if initial_checkpoint.phase == IntegrationPhase.IDLE.value:
        initial_checkpoint.items_processed = 0
        initial_checkpoint.items_blocked = 0
        initial_checkpoint.parked = []
        # Seeded after the reset, never before: the anomalies are re-derived on
        # every idle entry, so they persist while unfolded and vanish once folded.
        initial_checkpoint.warnings = list(unfolded_anomalies)
        _write_checkpoint(checkpoint_path, initial_checkpoint)
    elif initial_checkpoint.candidate_slug and not _candidate_belongs_to_project(initial_checkpoint, cwd=cwd):
        # A non-IDLE checkpoint whose candidate has no branch or worktree in this
        # project is foreign or phantom — resuming it wedges the integrator in an
        # unadvanceable loop. Reset to IDLE so the loop below re-scans this
        # project's own finalize-ready candidates instead.
        initial_checkpoint.phase = IntegrationPhase.IDLE.value
        initial_checkpoint.candidate_slug = None
        initial_checkpoint.candidate_branch = None
        initial_checkpoint.candidate_sha = None
        initial_checkpoint.lease_token = None
        _write_checkpoint(checkpoint_path, initial_checkpoint)

    if abandon and initial_checkpoint.phase != IntegrationPhase.CONTENT_GATE_BLOCKED.value:
        return _format_error(
            "ABANDON_WRONG_PHASE",
            f"--abandon requires the checkpoint to be at CONTENT_GATE_BLOCKED, "
            f"but it is at {initial_checkpoint.phase!r}",
        )

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
        try:
            keep_going, instruction = _step(
                phase=phase,
                checkpoint=checkpoint,
                checkpoint_path=checkpoint_path,
                lease_store=lease_store,
                session_id=session_id,
                slug=slug,
                cwd=cwd,
                started=started,
                abandon=abandon,
            )
        except Exception:
            logger.exception(
                "_step raised: phase=%s slug=%s iter=%d", phase.value, checkpoint.candidate_slug or slug, _iter
            )
            raise
        logger.info(
            "_step returned: phase=%s keep_going=%s instruction_len=%d", phase.value, keep_going, len(instruction)
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
    abandon: bool = False,
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
            session_id=session_id,
            cwd=cwd,
        )

    if phase == IntegrationPhase.CONTENT_GATE_BLOCKED:
        return _step_content_gate_blocked(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            cwd=cwd,
            abandon=abandon,
        )

    if phase == IntegrationPhase.CLEANUP:
        return _step_cleanup(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            cwd=cwd,
        )

    if phase == IntegrationPhase.CANDIDATE_DELIVERED:
        # Reset and prepare for next candidate
        _reset_candidate(checkpoint)
        _write_checkpoint(checkpoint_path, checkpoint)

        return True, ""  # loop

    if phase == IntegrationPhase.COMPLETED:
        elapsed_ms = int((perf_counter() - started) * 1000)
        return False, _format_queue_empty(
            checkpoint.items_processed,
            checkpoint.items_blocked,
            elapsed_ms,
            checkpoint.parked,
            warnings=checkpoint.warnings or [],
        )

    return False, _format_error("UNHANDLED_PHASE", f"No handler for phase: {phase.value}")


# ---------------------------------------------------------------------------
# Public async entry point
# ---------------------------------------------------------------------------


async def next_integrate(
    db: Db,
    slug: str | None,
    cwd: str,
    *,
    abandon: bool = False,
) -> str:
    """Integration state machine entry point.

    Reads current state from a durable checkpoint, executes the next
    deterministic step, and returns structured instructions at decision
    points where agent intelligence is required.

    Args:
        db: Database instance (reserved for future use).
        slug: Optional slug filter — must match next candidate in FIFO queue.
        cwd: Project root directory for git operations.
        abandon: The integrator's judgment that a ``CONTENT_GATE_BLOCKED``
            rejection is ungroundable — resets the integration worktree to the
            checkpoint-frozen ``pre_merge_head`` and parks the candidate.
            Refused when the checkpoint is not at that phase.

    Returns:
        Plain text instruction block for the agent to execute.
    """
    session_id = get_session_id() or ""
    started = perf_counter()
    state_dir = _default_state_dir(cwd)
    state_dir.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()
    cancellation = ProcessGroupCancellation()
    with process_group_cancellation_scope(cancellation):
        worker = asyncio.create_task(
            asyncio.to_thread(
                _dispatch_sync,
                session_id=session_id,
                slug=slug,
                cwd=cwd,
                state_dir=state_dir,
                started=started,
                loop=loop,
                abandon=abandon,
            )
        )
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancellation.request()
            try:
                await worker
            except ProcessGroupCancellationRequested:
                pass
            raise
