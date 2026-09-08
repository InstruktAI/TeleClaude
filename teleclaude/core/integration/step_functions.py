"""Integration step functions — git helpers, phase helpers, step implementations.

No imports from state_machine.py (circular-import guard).
Instruction formatters live in formatters.py.
"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import main_only_action_ids_for_files
from teleclaude.constants import (
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_REQUIREMENTS,
)
from teleclaude.core.blueprint import BlueprintStatus, regenerate_blueprint
from teleclaude.core.integration.candidate_scan import (
    CandidateKey,
    CandidateStateReadError,
    _scan_finalize_ready_candidates,
    _stamp_integration_started,
    _sweep_stale_artifacts,
    _verify_slug_ready,
)
from teleclaude.core.integration.checkpoint import (
    IntegrationCheckpoint,
    IntegrationPhase,
    _get_candidate_key,
    _now_iso,
    _write_checkpoint,
)
from teleclaude.core.integration.delivery_fold import assert_clean_before_push, reassert_delivered_fold
from teleclaude.core.integration.formatters import (
    _format_commit_decision,
    _format_conflict_decision,
    _format_error,
    _format_lease_busy,
    _format_push_rejected,
    _format_queue_empty,
    _format_repo_root_sync_instruction,
)
from teleclaude.core.integration.git_ops import (
    RepoRootSyncOutcome,
    RepoRootSyncStage,
    _ensure_integration_worktree,
    _get_branch_log,
    _get_conflicted_files,
    _get_diff_stats,
    _get_head_sha,
    _git_dir,
    _integration_worktree_path,
    _mark_repo_root_sync_failure,
    _merge_head_exists,
    _run_git,
    _synchronize_repo_root,
)
from teleclaude.core.integration.lease import IntegrationLeaseStore
from teleclaude.core.integration.lifecycle_events import (
    _EVENT_INTEGRATION_DRAIN_COMPLETED,
    _emit_lifecycle_event,
)
from teleclaude.core.integration.park import (
    _TEXTUAL_CONFLICT_PARK_REASON,
    _format_content_gate_conflict_or_invariant_error,
    _park_candidate,
)
from teleclaude.core.integration.push_recovery import _is_content_gate_rejection
from teleclaude.core.next_machine.delivery import cleanup_delivered_slug, reclaim_worktree_trash
from teleclaude.core.next_machine.marker_reconciliation import (
    MarkerMoment,
    MarkerOutcome,
    MarkerReceipt,
    reconcile_lifecycle_markers,
)
from teleclaude.core.todos_db import get_todos_db_sync
from teleclaude.git_lock import main_branch_lock
from teleclaude.hooks.checkpoint import _git_diff_names
from teleclaude.hooks.checkpoint_flags import record_integrator_maintenance_marker

logger = get_logger(__name__)

_INTEGRATION_LEASE_KEY = "integration/main"
_INTEGRATION_LEASE_TTL_SECONDS = 120
_NEXT_INTEGRATE_PHASE_LOG = "NEXT_INTEGRATE_PHASE"
_GIT_RANGE_SEPARATOR = ".."
_GIT_DIFF_UNMERGED_ARGS = ("diff", "--name-only", "--diff-filter=U")
_GIT_DIFF_STAGED_QUIET_ARGS = ("diff", "--cached", "--quiet")
_INTEGRATOR_MAINTENANCE_RECORDING_FAILED = "Failed to {operation} integrator maintenance {target} for range={merge_range} — post-merge maintenance will not be surfaced to the integrator"
_INTEGRATOR_MAINTENANCE_MARKER_RECORDED_LOG = "integration.maintenance_marker.recorded"
_GIT_PUSH_ORIGIN_MAIN_ARGS = ("push", "origin", "main")
_REPO_ROOT_SYNC_SOURCE, _INTEGRATION_WORKTREE_SYNC_SOURCE = "repo_root", "integration_worktree"
_BLUEPRINT_REGENERATED_LOG = "integration.blueprint.regenerated"
_REPO_ROOT_BOOKKEEPING_PUSHED_LOG = "Pushed %d repo root bookkeeping commit(s) to origin/main"

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


_CLEANUP_COMMIT_SUBJECT_TEMPLATE = "chore({slug}): integration worktree cleanup"
_GIT_ARG_COMMIT = "commit"
_GIT_ARG_AUTHOR = "--author"
_GIT_ARG_MESSAGE = "-m"


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
    parked_slugs = {parked["slug"] for parked in checkpoint.parked}

    try:
        if slug is not None:
            candidate = _verify_slug_ready(cwd, slug, parked_slugs=parked_slugs)
            candidates = [candidate] if candidate else []
        else:
            candidates = _scan_finalize_ready_candidates(cwd, parked_slugs=parked_slugs, exclude_slug=exclude)
    except CandidateStateReadError as exc:
        return False, _format_error("CANDIDATE_STATE_READ_FAILED", str(exc))

    if not candidates:
        elapsed_ms = int((perf_counter() - started) * 1000)
        _try_release_lease(lease_store, session_id, checkpoint.lease_token)
        if checkpoint.items_processed or checkpoint.parked:
            _emit_lifecycle_event(
                _EVENT_INTEGRATION_DRAIN_COMPLETED,
                {
                    "session_id": session_id,
                    "delivered_count": checkpoint.items_processed,
                    "parked": checkpoint.parked,
                    "completed_at": _now_iso(),
                },
            )
        return False, _format_queue_empty(
            checkpoint.items_processed,
            checkpoint.items_blocked,
            elapsed_ms,
            checkpoint.parked,
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

        return False, _format_commit_decision(
            key.slug,
            key.branch,
            diff_stats,
            branch_log,
            requirements,
            impl_plan,
            worktree=wt,
            pre_merge_head=pre_merge_head or "",
        )
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

        return False, _format_conflict_decision(key.slug, key.branch, conflicted_files, wt)


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

        return False, _format_conflict_decision(key.slug, key.branch, conflicted_files, wt)

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
        return False, _format_commit_decision(
            key.slug,
            key.branch,
            diff_stats,
            branch_log,
            requirements,
            impl_plan,
            worktree=wt,
            pre_merge_head=pre_merge or "",
        )
    else:
        conflicted_files = _get_conflicted_files(wt)
        if not conflicted_files:
            conflict_rc, conflict_stdout, _ = _run_git(list(_GIT_DIFF_UNMERGED_ARGS), cwd=wt)
            staged_rc, _, _ = _run_git(list(_GIT_DIFF_STAGED_QUIET_ARGS), cwd=wt)
            abandoned = (
                conflict_rc == 0
                and not conflict_stdout.strip()
                and staged_rc == 0
                and head_sha is not None
                and pre_merge is not None
                and head_sha == pre_merge
            )
            if abandoned:
                return _park_candidate(
                    checkpoint=checkpoint,
                    checkpoint_path=checkpoint_path,
                    key=key,
                    reason=_TEXTUAL_CONFLICT_PARK_REASON,
                )
        return False, _format_conflict_decision(key.slug, key.branch, conflicted_files, wt)


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

    _changed, fold_error = reassert_delivered_fold(integration_wt, key.slug)
    if fold_error is not None:
        return False, _format_error("RESIDUAL_MARKERS", fold_error)
    gate_error = assert_clean_before_push(integration_wt, key.slug)
    if gate_error is not None:
        return False, _format_error("RESIDUAL_MARKERS", gate_error)

    rc, _, _ = _run_git(["diff", "--cached", "--quiet"], cwd=wt)
    if rc != 0:
        # Deferred: teleclaude.commit_identity pulls in todo_scaffold ->
        # hooks.receiver -> core.todos_db -> core.next_machine.lifecycle ->
        # core.next_machine.git_ops at module load time — a module-level
        # import here would be circular.
        from teleclaude.commit_identity import (  # noqa: PLC0415 - deferred: breaks a circular import through todo_scaffold -> hooks.receiver -> core.todos_db -> core.next_machine.lifecycle -> core.next_machine.git_ops
            CommitIdentityUnresolvable,
            compose_commit_footer,
            resolve_commit_identity,
        )

        # human_involved is False — no agent declares involvement at this call
        # site. A resolution failure is reported via this function's own
        # (bool, error) return convention rather than propagated.
        try:
            git_identity, session_id = resolve_commit_identity()
        except CommitIdentityUnresolvable as exc:
            return False, _format_error("RESIDUAL_MARKERS", str(exc))
        cleanup_message = compose_commit_footer(
            _CLEANUP_COMMIT_SUBJECT_TEMPLATE.format(slug=key.slug), session_id=session_id, human_involved=False
        )
        cleanup_args = [_GIT_ARG_COMMIT]
        if git_identity is not None:
            cleanup_args.extend([_GIT_ARG_AUTHOR, git_identity])
        cleanup_args.extend([_GIT_ARG_MESSAGE, cleanup_message])
        rc_cleanup, _, stderr_cleanup = _run_git(cleanup_args, cwd=wt)
        if rc_cleanup != 0:
            # Fail closed: every staged delivery change must commit before push.
            return False, _format_error(
                "RESIDUAL_MARKERS",
                f"Cleanup commit failed for {key.slug}; refusing to push: {stderr_cleanup.strip()}",
            )

    checkpoint.warnings = warnings

    # --- Push the squash worktree commit to main ---
    # The delivery stamp and dependency cleanup are untracked todos.db writes made
    # only after this push is confirmed (in _step_push_succeeded). Serialize under
    # flock against concurrent integrator pushes.
    with main_branch_lock():
        rc, stdout, stderr = _run_git(["push", "origin", "HEAD:main"], cwd=wt)
    if rc == 0:
        head_sha = _get_head_sha(wt)
        checkpoint.pushed_sha = head_sha
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
            # merge conflict the integrator owns — fixed and re-pushed when
            # groundable, or abandoned and parked on CONTENT_GATE_BLOCKED
            # re-entry when it is not.
            checkpoint.phase = IntegrationPhase.CONTENT_GATE_BLOCKED.value
            checkpoint.error_context = {**(checkpoint.error_context or {}), "rejection_reason": rejection}
            _write_checkpoint(checkpoint_path, checkpoint)
            _emit_lifecycle_event(
                "integration.candidate.blocked",
                {"slug": key.slug, "branch": key.branch, "sha": key.sha, "reason": rejection},
            )
            logger.info("%s slug=%s phase=CONTENT_GATE_BLOCKED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
            return False, _format_content_gate_conflict_or_invariant_error(
                slug=key.slug,
                branch=key.branch,
                rejection_reason=rejection,
                worktree=wt,
                pre_merge_head=checkpoint.pre_merge_head,
            )

        checkpoint.phase = IntegrationPhase.PUSH_REJECTED.value
        checkpoint.error_context = {**(checkpoint.error_context or {}), "rejection_reason": rejection}
        _write_checkpoint(checkpoint_path, checkpoint)

        logger.info("%s slug=%s phase=PUSH_REJECTED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
        return False, _format_push_rejected(rejection, key.slug, wt)


def _regenerate_blueprint_after_delivery(*, cwd: str, baseline_sha: str, source: str) -> str | None:
    """Refresh the Blueprint after confirmed delivery without rolling it back on failure."""
    manifest = regenerate_blueprint(cwd, baseline_sha=baseline_sha)
    logger.info(
        _BLUEPRINT_REGENERATED_LOG,
        extra={"source": source, "baseline_sha": baseline_sha, "status": manifest.status.value},
    )
    if manifest.status is not BlueprintStatus.OK:
        return (
            f"Blueprint regeneration did not complete (status={manifest.status.value}); "
            "blast-radius falls back to manual exploration until the next integrate."
        )
    logger.info("Blueprint regenerated at baseline %s", baseline_sha)
    return None


def _reconcile_confirmed_delivery(
    *, cwd: str, slug: str, confirmed_sha: str
) -> tuple[str | None, MarkerReceipt | None, str | None]:
    receipt = reconcile_lifecycle_markers(Path(cwd), slug, MarkerMoment.DELIVER)
    if not receipt.succeeded:
        return None, None, receipt.reason
    if receipt.outcome is MarkerOutcome.APPLIED:
        with main_branch_lock():
            marker_push_rc, _, marker_push_error = _run_git(["push", "origin", "main"], cwd=cwd)
        if marker_push_rc != 0:
            return None, None, marker_push_error.strip()
        return _get_head_sha(cwd) or confirmed_sha, receipt, None
    return confirmed_sha, receipt, None


def _step_push_succeeded(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    session_id: str,
    cwd: str,
) -> tuple[bool, str]:
    """Confirm delivery, complete maintenance and cleanup, then pause on a non-ready repo root."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "PUSH_SUCCEEDED phase has no candidate key")

    wt = str(_integration_worktree_path(cwd))
    fetch_rc, _, _ = _run_git(["fetch", "origin"], cwd=wt)
    pushed_sha = checkpoint.pushed_sha
    confirmed_sha: str | None = None
    unconfirmed_reason = ""
    if fetch_rc != 0:
        unconfirmed_reason = "re-fetch of origin failed"
    elif not pushed_sha:
        unconfirmed_reason = "no frozen pushed commit recorded in checkpoint"
    else:
        ancestor_rc, _, _ = _run_git(["merge-base", "--is-ancestor", pushed_sha, "origin/main"], cwd=wt)
        if ancestor_rc == 0:
            confirmed_sha = pushed_sha
        else:
            unconfirmed_reason = f"pushed commit {pushed_sha[:8]} not present on origin/main"

    if confirmed_sha is None:
        # Frozen pushed commit not confirmed on origin/main: withhold delivery,
        # route back through normal rejection-recovery. No lifecycle event (no
        # delivery-confirmation event).
        reason = f"Delivery confirmation gate: {unconfirmed_reason}; delivery withheld."
        checkpoint.error_context = {**(checkpoint.error_context or {}), "rejection_reason": reason}
        checkpoint.phase = IntegrationPhase.PUSH_REJECTED.value
        _write_checkpoint(checkpoint_path, checkpoint)
        logger.info("%s slug=%s phase=PUSH_REJECTED (confirmation gate)", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
        return False, _format_push_rejected(reason, key.slug, wt)

    reconciled_sha, receipt, reconciliation_error = _reconcile_confirmed_delivery(
        cwd=cwd,
        slug=key.slug,
        confirmed_sha=confirmed_sha,
    )
    if reconciled_sha is None or receipt is None:
        return False, _format_error("DELIVERY_RECONCILIATION_FAILED", reconciliation_error or "unknown failure")
    confirmed_sha = reconciled_sha

    todos_db = get_todos_db_sync(cwd)
    delivered = todos_db.deliver_sync(
        key.slug,
        reconciliation_receipt=receipt,
        reconciliation_root=Path(cwd),
        commit=confirmed_sha,
    )
    if not delivered:
        if key.slug in todos_db.delivered_slugs_sync():
            logger.info(
                "integration.delivery.already_delivered",
                extra={"slug": key.slug, "commit_sha": confirmed_sha},
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
    warnings = checkpoint.warnings if checkpoint.warnings is not None else []
    repo_root_sync = _synchronize_repo_root(
        cwd=cwd,
        session_id=session_id,
        stage=RepoRootSyncStage.POST_DELIVERY,
    )
    if repo_root_sync.is_ready and repo_root_sync.outcome is RepoRootSyncOutcome.AHEAD_ONLY:
        with main_branch_lock():
            push_rc, _, push_stderr = _run_git(list(_GIT_PUSH_ORIGIN_MAIN_ARGS), cwd=cwd)
        if push_rc == 0:
            logger.info(_REPO_ROOT_BOOKKEEPING_PUSHED_LOG, repo_root_sync.ahead_count)
        else:
            repo_root_sync = _mark_repo_root_sync_failure(
                repo_root_sync,
                outcome=RepoRootSyncOutcome.BOOKKEEPING_PUSH_FAILED,
                failed_operation=_GIT_PUSH_ORIGIN_MAIN_ARGS[0],
                diagnostic=push_stderr,
            )
    checkpoint.warnings = warnings
    if checkpoint.pre_merge_head:
        merge_range = f"{checkpoint.pre_merge_head}{_GIT_RANGE_SEPARATOR}{confirmed_sha}"
        try:
            changed_files = _git_diff_names(cwd, merge_range)
            actions = main_only_action_ids_for_files(changed_files, Path(cwd))
            record_integrator_maintenance_marker(cwd, merge_range, actions)
            logger.info(
                _INTEGRATOR_MAINTENANCE_MARKER_RECORDED_LOG,
                extra={"session_id": repo_root_sync.session_id, "merge_range": merge_range, "actions": actions},
            )
        except OSError:
            msg = _INTEGRATOR_MAINTENANCE_RECORDING_FAILED.format(
                operation="record", target="marker", merge_range=merge_range
            )
            logger.warning(msg, exc_info=True)
            warnings.append(msg)
            checkpoint.warnings = warnings
        except Exception:
            msg = _INTEGRATOR_MAINTENANCE_RECORDING_FAILED.format(
                operation="resolve", target="actions", merge_range=merge_range
            )
            logger.warning(msg, exc_info=True)
            warnings.append(msg)
            checkpoint.warnings = warnings

    if repo_root_sync.is_ready:
        baseline_sha = _get_head_sha(cwd)
        if baseline_sha:
            blueprint_warning = _regenerate_blueprint_after_delivery(
                cwd=cwd,
                baseline_sha=baseline_sha,
                source=_REPO_ROOT_SYNC_SOURCE,
            )
            if blueprint_warning:
                logger.warning(blueprint_warning)
                warnings.append(blueprint_warning)
                checkpoint.warnings = warnings
    else:
        blueprint_warning = _regenerate_blueprint_after_delivery(
            cwd=wt,
            baseline_sha=confirmed_sha,
            source=_INTEGRATION_WORKTREE_SYNC_SOURCE,
        )
        if blueprint_warning:
            logger.warning(blueprint_warning)
            warnings.append(blueprint_warning)
            checkpoint.warnings = warnings

    checkpoint.phase = IntegrationPhase.CLEANUP.value
    _write_checkpoint(checkpoint_path, checkpoint)
    cleanup_continues, cleanup_instruction = _do_cleanup(
        checkpoint=checkpoint,
        checkpoint_path=checkpoint_path,
        key=key,
        cwd=cwd,
    )
    if not repo_root_sync.is_ready:
        return False, _format_repo_root_sync_instruction(repo_root_sync, project_root=cwd)
    return cleanup_continues, cleanup_instruction


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


__all__ = [
    "_do_merge",
    "_step_awaiting_commit",
    "_step_cleanup",
    "_step_committed",
    "_step_delivery_bookkeeping",
    "_step_idle",
    "_step_push_succeeded",
]
