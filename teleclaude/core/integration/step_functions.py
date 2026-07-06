"""Integration step functions — git helpers, phase helpers, step implementations.

No imports from state_machine.py (circular-import guard).
Instruction formatters live in formatters.py.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from time import perf_counter
from typing import Any, NamedTuple

from instrukt_ai_logging import get_logger

from teleclaude.constants import ARTIFACT_IMPLEMENTATION_PLAN, ARTIFACT_REQUIREMENTS, WORKTREE_DIR
from teleclaude.core import integration_bridge as bridge
from teleclaude.core.blueprint import BlueprintStatus, regenerate_blueprint
from teleclaude.core.integration.candidate_scan import (
    CandidateStateReadError,
    _scan_finalize_ready_candidates,
    _sweep_stale_artifacts,
    _verify_slug_ready,
)
from teleclaude.core.integration.checkpoint import IntegrationCheckpoint, IntegrationPhase, _now_iso, _write_checkpoint
from teleclaude.core.integration.delivery_fold import assert_clean_before_push, reassert_delivered_fold
from teleclaude.core.integration.formatters import (
    _format_commit_decision,
    _format_conflict_decision,
    _format_content_gate_conflict,
    _format_error,
    _format_lease_busy,
    _format_push_rejected,
    _format_queue_empty,
)
from teleclaude.core.integration.git_ops import (
    _candidate_content_contained,
    _get_branch_log,
    _get_conflicted_files,
    _get_diff_stats,
    _get_head_sha,
    _get_remote_main_sha,
    _git_dir,
    _merge_head_exists,
    _run_git,
)
from teleclaude.core.integration.lease import IntegrationLeaseStore
from teleclaude.core.integration.readiness_projection import CandidateKey
from teleclaude.core.next_machine.delivery import cleanup_delivered_slug, reclaim_worktree_trash
from teleclaude.core.todos_db import get_todos_db_sync
from teleclaude.docs_reconcile import reconcile_delivered_snippets
from teleclaude.git_lock import main_branch_lock
from teleclaude.hooks.checkpoint_flags import record_integrator_maintenance_marker
from teleclaude.session_identity import get_session_id

logger = get_logger(__name__)

# Thread-local storage for event loop reference (used in fire-and-forget async emission)
_tls = threading.local()

_INTEGRATION_LEASE_KEY = "integration/main"
_INTEGRATION_LEASE_TTL_SECONDS = 120
_NEXT_INTEGRATE_PHASE_LOG = "NEXT_INTEGRATE_PHASE"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _read_artifact_safe(cwd: str, slug: str, name: str) -> str:
    """Read a todo artifact from todos.db, returning empty string on failure."""
    try:
        db = get_todos_db_sync(cwd)
        return str(db.read_artifact_sync(slug, name))
    except Exception:
        logger.debug("_read_artifact_safe failed for %s/%s", slug, name, exc_info=True)
        return ""


# ---------------------------------------------------------------------------
# Phase helpers
# ---------------------------------------------------------------------------


_CONTENT_GATE_MARKER = "Integration push blocked"


def _is_content_gate_rejection(rejection_reason: str) -> bool:
    """Classify a push rejection as content-gate (vs. fast-forward race).

    The pre-push hook (``.githooks/pre-push``, ``trees/_integration`` branch)
    prints this stable marker when ``telec code lint --all`` fails on the
    squash content. That failure is invariant under rebase — a fast-forward
    race is the only other rejection cause and is rebase-recoverable.
    """
    return _CONTENT_GATE_MARKER in rejection_reason


def _get_candidate_key(checkpoint: IntegrationCheckpoint) -> CandidateKey | None:
    if checkpoint.candidate_slug and checkpoint.candidate_branch and checkpoint.candidate_sha:
        return CandidateKey(
            slug=checkpoint.candidate_slug,
            branch=checkpoint.candidate_branch,
            sha=checkpoint.candidate_sha,
        )
    return None


def _integration_worktree_path(cwd: str) -> Path:
    """Compute the persistent integration worktree path."""
    return Path(cwd) / WORKTREE_DIR / "_integration"


def _ensure_integration_worktree(cwd: str) -> tuple[Path, str]:
    """Ensure persistent integration worktree exists and is synced to origin/main.

    Returns (worktree_path, error_message). Error is empty on success.
    """
    integration_wt = _integration_worktree_path(cwd)

    if not integration_wt.exists():
        rc, _, stderr = _run_git(["fetch", "origin", "main"], cwd=cwd)
        if rc != 0:
            return integration_wt, f"git fetch origin main failed:\n{stderr.strip()}"
        rc, _, stderr = _run_git(["worktree", "add", str(integration_wt), "origin/main", "--detach"], cwd=cwd)
        if rc != 0:
            return integration_wt, f"git worktree add (integration) failed:\n{stderr.strip()}"

    # Fresh dequeues always resync the integration worktree before pinning the
    # squash base; mid-merge re-entry routes through awaiting-commit instead.
    wt = str(integration_wt)
    rc, _, stderr = _run_git(["fetch", "origin"], cwd=wt)
    if rc != 0:
        return integration_wt, f"git fetch origin failed in integration worktree:\n{stderr.strip()}"
    rc, _, stderr = _run_git(["reset", "--hard", "origin/main"], cwd=wt)
    if rc != 0:
        return integration_wt, f"git reset to origin/main failed in integration worktree:\n{stderr.strip()}"

    return integration_wt, ""


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


# guard: loose-dict-func - lifecycle event payload shape varies per event type
async def _bridge_emit(
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Dispatch lifecycle event to the appropriate integration_bridge helper."""
    # Lazy import to avoid circular dependency at module load time
    try:
        if event_type == "integration.started":
            await bridge.emit_integration_started(
                slug=payload.get("slug", ""),
                session_id=payload.get("session_id", ""),
                queue_depth=int(payload.get("queue_depth", 0)),
            )
        elif event_type == "integration.candidate.delivered":
            await bridge.emit_integration_candidate_delivered(
                slug=payload.get("slug", ""),
                branch=payload.get("branch", ""),
                merge_commit_sha=payload.get("merge_commit_sha", ""),
            )
        elif event_type == "integration.candidate.blocked":
            await bridge.emit_integration_candidate_blocked(
                slug=payload.get("slug", ""),
                branch=payload.get("branch", ""),
                sha=payload.get("sha", ""),
                reason=payload.get("reason", ""),
            )
        # Other event types are observability-only; logged below, not wired to bridge
    except Exception:
        logger.debug("_bridge_emit failed for %s", event_type, exc_info=True)


# guard: loose-dict-func - lifecycle event payload shape varies per event type
def _emit_lifecycle_event(
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Fire-and-forget lifecycle event emission via bridge (threadsafe)."""
    logger.info("INTEGRATION_LIFECYCLE_EVENT type=%s payload=%s", event_type, payload)
    loop: asyncio.AbstractEventLoop | None = getattr(_tls, "loop", None)
    if loop is None or not loop.is_running():
        return
    try:
        asyncio.run_coroutine_threadsafe(_bridge_emit(event_type, payload), loop)
    except Exception:
        logger.debug("_emit_lifecycle_event scheduling failed for %s", event_type, exc_info=True)


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------


def _step_idle(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    lease_store: IntegrationLeaseStore,
    session_id: str,
    slug: str | None,
    cwd: str,
    started: float,
) -> tuple[bool, str]:
    """IDLE: sweep stale artifacts, scan for finalize-ready candidates, acquire lease, proceed to merge."""
    # Sweep worktrees for already-delivered slugs left by crashed integrations
    _sweep_stale_artifacts(cwd)
    trash_failures = reclaim_worktree_trash(cwd)
    if trash_failures:
        logger.warning("Worktree trash reclaim failed for %d entries: %s", len(trash_failures), trash_failures)

    exclude = checkpoint.candidate_slug

    try:
        if slug is not None:
            candidate = _verify_slug_ready(cwd, slug)
            candidates = [candidate] if candidate else []
        else:
            candidates = _scan_finalize_ready_candidates(cwd, exclude_slug=exclude)
    except CandidateStateReadError as exc:
        return False, _format_error("CANDIDATE_STATE_READ_FAILED", str(exc))

    if not candidates:
        elapsed_ms = int((perf_counter() - started) * 1000)
        _try_release_lease(lease_store, session_id, checkpoint.lease_token)
        return False, _format_queue_empty(
            checkpoint.items_processed,
            checkpoint.items_blocked,
            elapsed_ms,
            warnings=checkpoint.warnings or [],
        )

    # Acquire lease
    acquire_result = lease_store.acquire(
        key=_INTEGRATION_LEASE_KEY,
        owner_session_id=session_id,
        ttl_seconds=_INTEGRATION_LEASE_TTL_SECONDS,
    )
    if acquire_result.status != "acquired" or not acquire_result.lease:
        holder_id = acquire_result.holder.owner_session_id if acquire_result.holder else "unknown"
        return False, _format_lease_busy(holder_id)

    lease_token = acquire_result.lease.lease_token
    key = candidates[0].key
    now = _now_iso()
    checkpoint.phase = IntegrationPhase.CANDIDATE_DEQUEUED.value
    checkpoint.candidate_slug = key.slug
    checkpoint.candidate_branch = key.branch
    checkpoint.candidate_sha = key.sha
    checkpoint.lease_token = lease_token
    checkpoint.started_at = now
    _write_checkpoint(checkpoint_path, checkpoint)
    _stamp_integration_started(cwd, key.slug)

    logger.info("%s slug=%s phase=CANDIDATE_DEQUEUED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
    _emit_lifecycle_event(
        "integration.started", {"slug": key.slug, "session_id": session_id, "queue_depth": len(candidates)}
    )
    _emit_lifecycle_event("integration.candidate.dequeued", {"slug": key.slug, "branch": key.branch, "sha": key.sha})

    # Go straight to merge — worktree isolation + push rejection handle concurrency
    return True, ""  # loop into CANDIDATE_DEQUEUED → _do_merge


def _do_merge(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    key: CandidateKey,
    cwd: str,
) -> tuple[bool, str]:
    """Set up integration worktree, squash merge candidate. Write MERGE_CLEAN or MERGE_CONFLICTED."""
    # Ensure persistent integration worktree exists and is synced to origin/main
    integration_wt, err = _ensure_integration_worktree(cwd)
    if err:
        return False, _format_error("INTEGRATION_WORKTREE_FAILED", err)
    wt = str(integration_wt)

    # Record pre-merge HEAD for commit detection (in integration worktree)
    pre_merge_head = _get_head_sha(wt)
    checkpoint.pre_merge_head = pre_merge_head

    # Guard: skip candidates already merged to main (stale re-queue after restart)
    ancestor_rc, _, _ = _run_git(["merge-base", "--is-ancestor", key.sha, "HEAD"], cwd=wt)
    if ancestor_rc == 0:
        logger.info(
            "%s slug=%s sha=%s already ancestor of main — skipping as already integrated",
            _NEXT_INTEGRATE_PHASE_LOG,
            key.slug,
            key.sha[:8],
        )
        _emit_lifecycle_event(
            "integration.candidate.already_merged",
            {"slug": key.slug, "branch": key.branch, "sha": key.sha},
        )
        checkpoint.phase = IntegrationPhase.CANDIDATE_DELIVERED.value
        _write_checkpoint(checkpoint_path, checkpoint)
        return True, ""

    rc, _, _stderr = _run_git(["merge", "--squash", key.branch], cwd=wt)

    # Guard: squash merge produced no content changes — candidate already integrated.
    # Catches squash merges where ancestry check (above) doesn't fire because
    # squash commits don't create ancestry links.
    empty_rc, _, _ = _run_git(["diff", "--cached", "--quiet"], cwd=wt)
    if empty_rc == 0:
        conflicted = _get_conflicted_files(wt) if rc != 0 else []
        if not conflicted:
            logger.info(
                "%s slug=%s already integrated (empty squash merge) — skipping",
                _NEXT_INTEGRATE_PHASE_LOG,
                key.slug,
            )
            _emit_lifecycle_event(
                "integration.candidate.already_merged",
                {"slug": key.slug, "branch": key.branch, "sha": key.sha},
            )
            # Clean up SQUASH_MSG left by git (worktree-aware path)
            gd = _git_dir(wt)
            if gd:
                squash_msg = gd / "SQUASH_MSG"
                if squash_msg.exists():
                    squash_msg.unlink()
            checkpoint.phase = IntegrationPhase.CANDIDATE_DELIVERED.value
            _write_checkpoint(checkpoint_path, checkpoint)
            return True, ""

    if rc == 0:
        # Clean merge — fold the delivered slug's pending doc state into the live
        # contract (companions swapped in, planned markers stripped, delivered_by
        # cleared), then re-stage so the reconciliation rides the integrator's commit.
        try:
            if reconcile_delivered_snippets(integration_wt, key.slug):
                _run_git(["add", "-A"], cwd=wt)
        except OSError:
            # Non-fatal: never fail an already-clean merge over doc reconciliation.
            # Narrow to filesystem errors with a traceback — a programming error in
            # the reconcile path must still surface rather than be swallowed.
            logger.exception("delivered-snippet reconciliation failed for %s (non-fatal)", key.slug)

        # Read stats from integration worktree, context from repo root
        diff_stats = _get_diff_stats(wt)
        branch_log = _get_branch_log(wt, key.branch, base_ref="origin/main")
        requirements = _read_artifact_safe(cwd, key.slug, ARTIFACT_REQUIREMENTS)
        impl_plan = _read_artifact_safe(cwd, key.slug, ARTIFACT_IMPLEMENTATION_PLAN)

        checkpoint.phase = IntegrationPhase.MERGE_CLEAN.value
        checkpoint.error_context = {"merge_type": "clean"}
        _write_checkpoint(checkpoint_path, checkpoint)

        _emit_lifecycle_event("integration.merge.succeeded", {"slug": key.slug, "branch": key.branch})
        logger.info("%s slug=%s phase=MERGE_CLEAN", _NEXT_INTEGRATE_PHASE_LOG, key.slug)

        return False, _format_commit_decision(key.slug, key.branch, diff_stats, branch_log, requirements, impl_plan)
    else:
        # Conflict
        conflicted_files = _get_conflicted_files(wt)
        checkpoint.phase = IntegrationPhase.MERGE_CONFLICTED.value
        checkpoint.error_context = {"merge_type": "conflicted", "conflicted_files": conflicted_files}
        _write_checkpoint(checkpoint_path, checkpoint)

        _emit_lifecycle_event(
            "integration.merge.conflicted",
            {"slug": key.slug, "branch": key.branch, "conflicted_files": conflicted_files},
        )
        logger.info(
            "%s slug=%s phase=MERGE_CONFLICTED files=%d", _NEXT_INTEGRATE_PHASE_LOG, key.slug, len(conflicted_files)
        )

        return False, _format_conflict_decision(key.slug, key.branch, conflicted_files)


def _step_awaiting_commit(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """MERGE_CLEAN / MERGE_CONFLICTED / AWAITING_COMMIT: check if agent committed in integration worktree."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "Awaiting-commit phase has no candidate key")

    wt = str(_integration_worktree_path(cwd))

    # Check for unresolved merge conflicts first (in integration worktree)
    if _merge_head_exists(wt):
        conflicted_files = _get_conflicted_files(wt)
        checkpoint.error_context = {**(checkpoint.error_context or {}), "conflicted_files": conflicted_files}
        _write_checkpoint(checkpoint_path, checkpoint)

        return False, _format_conflict_decision(key.slug, key.branch, conflicted_files)

    # Check if HEAD advanced in integration worktree (commit happened)
    head_sha = _get_head_sha(wt)
    pre_merge = checkpoint.pre_merge_head
    if head_sha and pre_merge and head_sha != pre_merge:
        # Commit detected — advance to COMMITTED
        checkpoint.phase = IntegrationPhase.COMMITTED.value
        _write_checkpoint(checkpoint_path, checkpoint)

        _emit_lifecycle_event("integration.candidate.committed", {"slug": key.slug, "commit_sha": head_sha})
        logger.info("%s slug=%s phase=COMMITTED commit=%s", _NEXT_INTEGRATE_PHASE_LOG, key.slug, head_sha)
        return True, ""  # loop into COMMITTED

    # No commit yet — re-prompt
    merge_type = (checkpoint.error_context or {}).get("merge_type", "conflicted")
    if merge_type == "clean":
        diff_stats = _get_diff_stats(wt)
        branch_log = _get_branch_log(wt, key.branch, base_ref="origin/main")
        requirements = _read_artifact_safe(cwd, key.slug, ARTIFACT_REQUIREMENTS)
        impl_plan = _read_artifact_safe(cwd, key.slug, ARTIFACT_IMPLEMENTATION_PLAN)
        return False, _format_commit_decision(key.slug, key.branch, diff_stats, branch_log, requirements, impl_plan)
    else:
        conflicted_files = list((checkpoint.error_context or {}).get("conflicted_files", []))
        return False, _format_conflict_decision(key.slug, key.branch, conflicted_files)


def _step_committed(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """COMMITTED: transition to DELIVERY_BOOKKEEPING."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "COMMITTED phase has no candidate key")

    checkpoint.phase = IntegrationPhase.DELIVERY_BOOKKEEPING.value
    _write_checkpoint(checkpoint_path, checkpoint)

    return True, ""  # loop into DELIVERY_BOOKKEEPING


def _step_delivery_bookkeeping(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """DELIVERY_BOOKKEEPING: push the squash (plus any tracked staged change) to main.

    The todo delivery stamp and dependency cleanup are ``todos.db`` writes —
    untracked local state, never part of the pushed commit — deferred to the
    confirmed-push path in ``_step_push_succeeded``. Writing them here, before
    the push lands, would flag the todo delivered even on a rejected push.
    """
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "DELIVERY_BOOKKEEPING phase has no candidate key")

    integration_wt = _integration_worktree_path(cwd)
    wt = str(integration_wt)
    warnings = checkpoint.warnings if checkpoint.warnings is not None else []

    # Re-assert the idempotent delivered-snippet fold at this universal delivery
    # chokepoint (fails closed; see delivery_fold). Stage any change so the existing
    # cleanup commit carries it into the delivery before the push. Staging itself
    # must fail closed: an unstaged fold never reaches the commit, so an unfolded
    # tree would reach origin/main while the working-tree marker gate still passes.
    staged_changed, fold_error = reassert_delivered_fold(integration_wt, key.slug)
    if fold_error:
        return False, _format_error("RESIDUAL_MARKERS", fold_error)
    if staged_changed:
        add_rc, _, add_stderr = _run_git(["add", "-A"], cwd=wt)
        if add_rc != 0:
            return False, _format_error(
                "RESIDUAL_MARKERS",
                f"Staging the delivered-snippet fold failed for {key.slug}; refusing to push: {add_stderr.strip()}",
            )

    rc, _, _ = _run_git(["diff", "--cached", "--quiet"], cwd=wt)
    if rc != 0:
        rc_cleanup, _, stderr_cleanup = _run_git(
            [
                "commit",
                "-m",
                (
                    f"chore({key.slug}): integration worktree cleanup\n\n"
                    "🤖 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)\n\n"
                    "Co-Authored-By: TeleClaude <noreply@instrukt.ai>"
                ),
            ],
            cwd=wt,
        )
        if rc_cleanup != 0:
            # Fail closed: the staged fold (and any other staged delivery state) must
            # be committed before the push. A swallowed failure here pushes HEAD
            # without the fold, carrying the delivered slug's markers to origin/main.
            return False, _format_error(
                "RESIDUAL_MARKERS",
                f"Cleanup commit failed for {key.slug}; refusing to push: {stderr_cleanup.strip()}",
            )

    checkpoint.warnings = warnings

    # Fail-closed gate immediately before the push (see delivery_fold): a delivered
    # slug must never reach origin/main carrying live markers. With staging and the
    # cleanup commit both proven above, the worktree tree now equals the HEAD that
    # will be pushed, so this working-tree assertion gates the pushed commit too.
    gate_error = assert_clean_before_push(integration_wt, key.slug)
    if gate_error:
        return False, _format_error("RESIDUAL_MARKERS", gate_error)

    # --- Push the squash worktree commit to main ---
    # The delivery stamp and dependency cleanup are untracked todos.db writes made
    # only after this push is confirmed (in _step_push_succeeded). Serialize under
    # flock against concurrent integrator pushes.
    with main_branch_lock():
        rc, stdout, stderr = _run_git(["push", "origin", "HEAD:main"], cwd=wt)
    if rc == 0:
        head_sha = _get_head_sha(wt)
        checkpoint.phase = IntegrationPhase.PUSH_SUCCEEDED.value
        _write_checkpoint(checkpoint_path, checkpoint)

        _emit_lifecycle_event("integration.push.succeeded", {"slug": key.slug, "commit_sha": head_sha or "unknown"})
        logger.info("%s slug=%s phase=PUSH_SUCCEEDED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
        return True, ""  # loop into PUSH_SUCCEEDED
    else:
        rejection = (stderr or stdout).strip()
        _emit_lifecycle_event("integration.push.rejected", {"slug": key.slug, "rejection_reason": rejection})

        if _is_content_gate_rejection(rejection):
            # Content-gate rejection: the squash content itself violates a
            # repo-wide invariant, invariant under rebase. This is a logical
            # merge conflict the integrator owns — never abandon; stay stopped
            # on the candidate until it is resolved or escalated.
            checkpoint.phase = IntegrationPhase.CONTENT_GATE_BLOCKED.value
            checkpoint.error_context = {**(checkpoint.error_context or {}), "rejection_reason": rejection}
            _write_checkpoint(checkpoint_path, checkpoint)
            _emit_lifecycle_event(
                "integration.candidate.blocked",
                {"slug": key.slug, "branch": key.branch, "sha": key.sha, "reason": rejection},
            )
            logger.info("%s slug=%s phase=CONTENT_GATE_BLOCKED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
            return False, _format_content_gate_conflict(key.slug, key.branch, rejection, wt)

        checkpoint.phase = IntegrationPhase.PUSH_REJECTED.value
        checkpoint.error_context = {**(checkpoint.error_context or {}), "rejection_reason": rejection}
        _write_checkpoint(checkpoint_path, checkpoint)

        logger.info("%s slug=%s phase=PUSH_REJECTED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
        return False, _format_push_rejected(rejection, key.slug, wt)


class _RepushOutcome(NamedTuple):
    """Result of a shared re-push-and-reclassify attempt.

    ``resolved`` holds the ``(keep_going, instruction)`` tuple to return
    verbatim when the push landed (``PUSH_SUCCEEDED``) or the rejection was a
    content-gate block (``CONTENT_GATE_BLOCKED``). It is ``None`` when the
    rejection was a non-content-gate (fast-forward race) cause the caller must
    classify itself; ``rejection`` then carries the reason text and ``wt`` the
    resolved worktree path for the caller's fallback instruction.
    """

    resolved: tuple[bool, str] | None
    rejection: str
    wt: str


def _repush_and_reclassify(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
    key: CandidateKey,
) -> _RepushOutcome:
    """Re-attempt the push and reclassify the fresh rejection cause.

    Shared re-entry body for ``PUSH_REJECTED`` and ``CONTENT_GATE_BLOCKED``. If
    local HEAD already matches remote main, or the fresh push now lands,
    transitions to ``PUSH_SUCCEEDED`` and returns a keep-going result. On a
    content-gate rejection, transitions to ``CONTENT_GATE_BLOCKED``, emits the
    blocked beacon event, and returns the conflict instruction. On a
    non-content-gate rejection, stamps the reason into ``error_context`` and
    returns it unresolved so the caller classifies the phase itself.
    """
    wt = str(_integration_worktree_path(cwd))
    local_head = _get_head_sha(wt)
    remote_head = _get_remote_main_sha(wt)
    if local_head and remote_head and local_head == remote_head:
        checkpoint.phase = IntegrationPhase.PUSH_SUCCEEDED.value
        _write_checkpoint(checkpoint_path, checkpoint)

        _emit_lifecycle_event("integration.push.succeeded", {"slug": key.slug, "commit_sha": local_head})
        logger.info("%s slug=%s phase=PUSH_SUCCEEDED (recovered)", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
        return _RepushOutcome((True, ""), "", wt)  # loop into PUSH_SUCCEEDED

    with main_branch_lock():
        rc, stdout, stderr = _run_git(["push", "origin", "HEAD:main"], cwd=wt)
    if rc == 0:
        checkpoint.phase = IntegrationPhase.PUSH_SUCCEEDED.value
        _write_checkpoint(checkpoint_path, checkpoint)

        _emit_lifecycle_event("integration.push.succeeded", {"slug": key.slug, "commit_sha": local_head or "unknown"})
        logger.info("%s slug=%s phase=PUSH_SUCCEEDED (recovered)", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
        return _RepushOutcome((True, ""), "", wt)  # loop into PUSH_SUCCEEDED

    rejection = (stderr or stdout).strip()
    _emit_lifecycle_event("integration.push.rejected", {"slug": key.slug, "rejection_reason": rejection})

    if _is_content_gate_rejection(rejection):
        checkpoint.phase = IntegrationPhase.CONTENT_GATE_BLOCKED.value
        checkpoint.error_context = {**(checkpoint.error_context or {}), "rejection_reason": rejection}
        _write_checkpoint(checkpoint_path, checkpoint)
        _emit_lifecycle_event(
            "integration.candidate.blocked",
            {"slug": key.slug, "branch": key.branch, "sha": key.sha, "reason": rejection},
        )
        logger.info("%s slug=%s phase=CONTENT_GATE_BLOCKED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
        return _RepushOutcome(
            (False, _format_content_gate_conflict(key.slug, key.branch, rejection, wt)), rejection, wt
        )

    checkpoint.error_context = {**(checkpoint.error_context or {}), "rejection_reason": rejection}
    return _RepushOutcome(None, rejection, wt)


def _step_push_rejected(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """PUSH_REJECTED: re-attempt the push and reclassify the fresh rejection cause.

    Pushing (once the agent's out-of-band fetch/rebase is done) is mechanical, so
    the state machine performs it itself on every re-entry rather than trusting
    the checkpoint's stale ``rejection_reason``. This is what lets a
    rebase-then-re-push that now fails the content gate be observed and routed
    to ``CONTENT_GATE_BLOCKED`` — without it, that case would silently keep
    reissuing the stale race-recovery message forever (the freeze the diagnosis
    names). If local HEAD already matches remote main (the agent's own push
    already landed), no redundant push is attempted.
    """
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "PUSH_REJECTED phase has no candidate key")

    outcome = _repush_and_reclassify(checkpoint=checkpoint, checkpoint_path=checkpoint_path, cwd=cwd, key=key)
    if outcome.resolved is not None:
        return outcome.resolved

    _write_checkpoint(checkpoint_path, checkpoint)
    return False, _format_push_rejected(outcome.rejection or "unknown rejection", key.slug, outcome.wt)


def _step_content_gate_blocked(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """CONTENT_GATE_BLOCKED: integrator-owned logical merge conflict, re-entered.

    Mirrors ``_step_push_rejected``'s re-push-and-reclassify shape, minus
    abandonment: the candidate's ``finalize.status`` is never retracted, the
    worktree is never reset, and the checkpoint never returns to IDLE while the
    conflict stands — no later candidate is dequeued. If a fresh push attempt
    still fails the content gate, the candidate stays blocked and the
    conflict instruction is re-issued as a beacon; if it now fails as a
    fast-forward race instead, recovery hands off to the ordinary
    PUSH_REJECTED rebase loop.
    """
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "CONTENT_GATE_BLOCKED phase has no candidate key")

    outcome = _repush_and_reclassify(checkpoint=checkpoint, checkpoint_path=checkpoint_path, cwd=cwd, key=key)
    if outcome.resolved is not None:
        return outcome.resolved

    checkpoint.phase = IntegrationPhase.PUSH_REJECTED.value
    _write_checkpoint(checkpoint_path, checkpoint)
    logger.info("%s slug=%s phase=PUSH_REJECTED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
    return False, _format_push_rejected(outcome.rejection or "unknown rejection", key.slug, outcome.wt)


def _regenerate_blueprint_after_delivery(*, cwd: str, baseline_sha: str) -> str | None:
    """Refresh the codebase Blueprint after repo root syncs to pushed origin/main.

    The integrator is the single writer of the context-owned Blueprint cache.
    Best-effort by contract: regenerate_blueprint never raises; a non-ok status
    yields a warning string and never blocks delivery.
    """
    manifest = regenerate_blueprint(cwd, baseline_sha=baseline_sha)
    if manifest.status is not BlueprintStatus.OK:
        return (
            f"Blueprint regeneration did not complete (status={manifest.status.value}); "
            "blast-radius falls back to manual exploration until the next integrate."
        )
    logger.info("Blueprint regenerated at baseline %s", baseline_sha)
    return None


def _step_push_succeeded(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """PUSH_SUCCEEDED: confirm the candidate on origin/main, record delivery, sync, cleanup.

    Records the todo delivery and dependency cleanup in untracked todos.db only
    after the confirmation gate passes, then best-effort syncs repo root. Cleanup
    always runs regardless of pull outcome — the pull is a convenience sync.
    """
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "PUSH_SUCCEEDED phase has no candidate key")

    # Gate delivery on confirmed candidate-content containment on origin/main: a
    # failed re-fetch (stale ref), unresolved HEAD, or the candidate's own commit
    # (key.sha, never key.branch — the branch may have moved or vanished) missing
    # from origin/main all withhold delivery.
    wt = str(_integration_worktree_path(cwd))
    fetch_rc, _, _ = _run_git(["fetch", "origin"], cwd=wt)
    landed_sha = _get_head_sha(wt)

    contained = False
    probe_error = ""
    if fetch_rc == 0 and bool(landed_sha) and landed_sha != checkpoint.pre_merge_head:
        reset_rc, _, reset_stderr = _run_git(["reset", "--hard", "origin/main"], cwd=wt)
        if reset_rc == 0:
            contained, probe_error = _candidate_content_contained(wt, key.sha)
        else:
            probe_error = (
                f"failed to reset integration worktree to origin/main before containment probe: {reset_stderr.strip()}"
            )

    if not contained:
        # Candidate content not confirmed on origin/main: withhold delivery, route
        # back through normal rejection-recovery. No lifecycle event (no
        # delivery-confirmation event). A probe error is surfaced distinctly from
        # an ordinary "not contained" result.
        reason = (
            f"Delivery confirmation gate: candidate content {key.sha[:8]} not confirmed contained on "
            f"origin/main (worktree HEAD {landed_sha or '(unresolved)'} after push); delivery withheld."
            + (f" Containment probe error: {probe_error}" if probe_error else "")
        )
        checkpoint.error_context = {**(checkpoint.error_context or {}), "rejection_reason": reason}
        checkpoint.phase = IntegrationPhase.PUSH_REJECTED.value
        _write_checkpoint(checkpoint_path, checkpoint)
        logger.info("%s slug=%s phase=PUSH_REJECTED (confirmation gate)", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
        return False, _format_push_rejected(reason, key.slug, wt)

    # Confirmed on main: record the delivery against the landed commit.
    todos_db = get_todos_db_sync(cwd)
    delivered = todos_db.deliver_sync(key.slug, commit=landed_sha)
    if not delivered:
        # `deliver_sync` returns False either because the row is already
        # 'delivered' (idempotent — crash re-entry into this phase, or a
        # worker-side finalize) or because the slug is absent (genuine bug).
        # Probe to distinguish; fail fast on the missing case.
        if key.slug in todos_db.delivered_slugs_sync():
            logger.info(
                "integration.delivery.already_delivered",
                extra={"slug": key.slug, "commit_sha": landed_sha},
            )
        else:
            return False, _format_error(
                "DELIVERY_FAILED",
                f"todos_db.deliver_sync returned False for {key.slug} and the slug is not in delivered_slugs — todo entry is missing",
            )

    conn = todos_db._sync_conn()  # clean dependency references on the same gated path
    try:
        conn.execute("DELETE FROM todo_deps WHERE depends_on = ?", (key.slug,))  # guard: raw-sql
        conn.commit()
    finally:
        conn.close()

    # Best-effort sync of repo root with origin/main. Failure is logged
    # but does not block cleanup — the integration worktree already pushed.
    warnings = checkpoint.warnings if checkpoint.warnings is not None else []
    rc, _, _ = _run_git(["pull", "--ff-only", "origin", "main"], cwd=cwd)
    repo_root_synced = rc == 0
    if rc != 0:
        msg = (
            f"Repo root main is behind origin/main after delivering {key.slug}. "
            "Run: git pull --rebase origin main, then git push origin main — "
            "this requires no other work in progress on repo root main. "
            "Ask the user to confirm it is safe before running."
        )
        logger.warning(msg)
        warnings.append(msg)
    else:
        # Pull succeeded — push repo root bookkeeping if local main is ahead.
        # After ff-only pull, local is a superset of origin: push is guaranteed fast-forward.
        rc_ahead, stdout_ahead, _ = _run_git(["rev-list", "--count", "origin/main..HEAD"], cwd=cwd)
        ahead_count = int(stdout_ahead.strip() or "0") if rc_ahead == 0 else 0
        if ahead_count > 0:
            with main_branch_lock():
                rc_push, _, stderr_push = _run_git(["push", "origin", "main"], cwd=cwd)
            if rc_push == 0:
                logger.info("Pushed %d repo root bookkeeping commit(s) to origin/main", ahead_count)
            else:
                msg = f"Push repo root bookkeeping failed: {stderr_push.strip()}"
                logger.warning(msg)
                warnings.append(msg)
    checkpoint.warnings = warnings

    # Record the integrator-maintenance marker before CANDIDATE_DELIVERED clears
    # pre_merge_head. Range pre_merge_head..repo-root-HEAD captures every file
    # delivered this candidate; accumulated across candidates drained in one run.
    session_id = get_session_id()
    if session_id and checkpoint.pre_merge_head:
        current_head = _get_head_sha(cwd)
        if current_head:
            merge_range = f"{checkpoint.pre_merge_head}..{current_head}"
            try:
                record_integrator_maintenance_marker(session_id, merge_range)
                logger.info(
                    "Integrator maintenance marker recorded: session=%s range=%s",
                    session_id,
                    merge_range,
                )
            except OSError:
                msg = (
                    f"Failed to record integrator maintenance marker for session={session_id} "
                    f"range={merge_range} — post-merge maintenance will not be surfaced to the integrator"
                )
                logger.warning(msg, exc_info=True)
                warnings.append(msg)
                checkpoint.warnings = warnings

    # Refresh the Blueprint only once repo root holds the pushed origin/main, so its
    # baseline_sha matches the delivered commit. Best-effort: never blocks delivery.
    if repo_root_synced:
        baseline_sha = _get_head_sha(cwd)
        if baseline_sha:
            blueprint_warning = _regenerate_blueprint_after_delivery(cwd=cwd, baseline_sha=baseline_sha)
            if blueprint_warning:
                logger.warning(blueprint_warning)
                warnings.append(blueprint_warning)
                checkpoint.warnings = warnings

    checkpoint.phase = IntegrationPhase.CLEANUP.value
    _write_checkpoint(checkpoint_path, checkpoint)
    return _do_cleanup(checkpoint=checkpoint, checkpoint_path=checkpoint_path, key=key, cwd=cwd)


def _step_cleanup(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """CLEANUP: idempotent re-entry for cleanup after crash."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "CLEANUP phase has no candidate key")

    return _do_cleanup(checkpoint=checkpoint, checkpoint_path=checkpoint_path, key=key, cwd=cwd)


def _do_cleanup(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    key: CandidateKey,
    cwd: str,
) -> tuple[bool, str]:
    """Perform cleanup and advance to CANDIDATE_DELIVERED.

    The squash commit was pushed to origin/main during DELIVERY_BOOKKEEPING, and
    the todo delivery stamp plus dependency cleanup were written to untracked
    todos.db during the confirmed PUSH_SUCCEEDED gate. This step delegates to
    cleanup_delivered_slug, which handles physical artifacts (worktree removal,
    branch deletion, leftover directory removal) and runs
    clean_dependency_references idempotently on repo root.
    """
    # Merge commit SHA lives in the integration worktree (the pushed squash commit)
    wt = str(_integration_worktree_path(cwd))
    merge_commit = _get_head_sha(wt) or "unknown"

    # Delegates to cleanup_delivered_slug for physical artifacts (worktree,
    # branch, leftover dirs) plus idempotent dependency reference cleanup.
    try:
        cleanup_delivered_slug(cwd, key.slug, branch=key.branch)
    except Exception:
        msg = f"cleanup_delivered_slug failed for {key.slug} (non-fatal)"
        logger.warning(msg, exc_info=True)
        warnings = checkpoint.warnings if checkpoint.warnings is not None else []
        warnings.append(msg)
        checkpoint.warnings = warnings

    _emit_lifecycle_event(
        "integration.candidate.delivered",
        {"slug": key.slug, "branch": key.branch, "merge_commit_sha": merge_commit},
    )

    checkpoint.phase = IntegrationPhase.CANDIDATE_DELIVERED.value
    checkpoint.items_processed += 1
    _write_checkpoint(checkpoint_path, checkpoint)

    logger.info("%s slug=%s phase=CANDIDATE_DELIVERED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)

    return True, ""  # loop to pop next candidate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_release_lease(lease_store: IntegrationLeaseStore, session_id: str, lease_token: str | None) -> None:
    if not lease_token:
        return
    try:
        lease_store.release(key=_INTEGRATION_LEASE_KEY, owner_session_id=session_id, lease_token=lease_token)
    except Exception:
        logger.warning("Failed to release integration lease for session %s", session_id, exc_info=True)


def _stamp_integration_started(cwd: str, slug: str) -> None:
    """Stamp integration_phase='started' on an active slug's todo state.

    Best-effort: failures are logged but do not block the integration flow.
    Only called at candidate dequeue when the slug is still active.
    The 'delivered' stamp is handled by deliver_sync.
    """
    try:
        todos_db = get_todos_db_sync(cwd)
        state = todos_db.read_state_sync(slug)
        if state is None:
            return
        state["integration_phase"] = "started"
        todos_db.write_state_sync(slug, state)
    except Exception as exc:
        logger.warning("_stamp_integration_started failed for %s: %s", slug, exc)


__all__ = [
    "_do_merge",
    "_step_awaiting_commit",
    "_step_cleanup",
    "_step_committed",
    "_step_content_gate_blocked",
    "_step_delivery_bookkeeping",
    "_step_idle",
    "_step_push_rejected",
    "_step_push_succeeded",
]
