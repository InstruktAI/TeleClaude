"""Integration step functions — git helpers, phase helpers, step implementations.

No imports from state_machine.py (circular-import guard).
Instruction formatters live in formatters.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.capabilities import resolve_capabilities
from teleclaude.constants import (
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_REQUIREMENTS,
)
from teleclaude.core.blueprint import BlueprintStatus, regenerate_blueprint
from teleclaude.core.blueprint._paths import manifest_path
from teleclaude.core.blueprint.generate import blueprint_generation_lock
from teleclaude.core.blueprint.manifest import read_manifest
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
    _format_root_finalization_blocker,
)
from teleclaude.core.integration.git_ops import (
    RepoRootSyncStage,
    _ensure_integration_worktree,
    _get_branch_log,
    _get_conflicted_files,
    _get_diff_stats,
    _get_head_sha,
    _get_remote_main_sha,
    _git_dir,
    _integration_worktree_path,
    _merge_head_exists,
    _publish_repo_root_main,
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
from teleclaude.core.next_machine.delivery import cleanup_delivered_slug
from teleclaude.core.next_machine.git_ops import build_git_hook_env
from teleclaude.core.next_machine.marker_reconciliation import MarkerReceipt
from teleclaude.core.todos_db import get_todos_db_sync
from teleclaude.git_lock import main_branch_lock
from teleclaude.quality.gate import LintGateOutcome, run_lint_gate
from teleclaude.runtime.environment import resolve_runtime_environment

logger = get_logger(__name__)

_INTEGRATION_LEASE_KEY = "integration/main"
_INTEGRATION_LEASE_TTL_SECONDS = 120
_NEXT_INTEGRATE_PHASE_LOG = "NEXT_INTEGRATE_PHASE"
_GIT_DIFF_UNMERGED_ARGS = ("diff", "--name-only", "--diff-filter=U")
_GIT_DIFF_STAGED_QUIET_ARGS = ("diff", "--cached", "--quiet")
_REPO_ROOT_SYNC_SOURCE = "repo_root"
_BLUEPRINT_REGENERATED_LOG = "integration.blueprint.regenerated"
_BLUEPRINT_REGENERATED_AT_LOG = "Blueprint regenerated at baseline %s"
_ORIGIN_MAIN_REVISION_ARGUMENTS = ("rev-parse", "origin/main")
_BLUEPRINT_BASELINE_RESOLUTION_FAILURE = "Blueprint baseline could not be resolved from origin/main."
_FINAL_CONTENT_GATE_FINISHED_EVENT = "integration.final_content_gate.finished"
_QUALITY_ENV_REMOVED_KEYS = frozenset({"VIRTUAL_ENV", "PYTHONPATH", "PYTEST_ADDOPTS"})
_VALIDATION_CHECKOUT_RESET_ARGS = ("reset", "--hard")
_PATH_ENV_KEY: Final = "PATH"
_SHELL_ENV_KEY: Final = "SHELL"
_ROOT_HEAD_UNAVAILABLE_AFTER_RECONCILIATION = "Repository-root HEAD is unavailable after marker reconciliation."
_VALIDATION_CHECKOUT_RESET_FAILURE = "Validation checkout could not reset to root subject {subject_sha}: {stderr}"
_ROOT_HEAD_CHANGED_AFTER_VALIDATION = (
    "Repository-root HEAD changed after final validation; synchronization and validation must restart."
)
_ROOT_PUBLICATION_CONFIRMATION_FAILURE = (
    "Repository-root publication did not confirm source head {final_sha} on origin/main."
)
_NO_CODE_CAPABILITY_REASON = "Code capability is not declared."
_FINAL_GATE_FIELD_SLUG = "slug"
_FINAL_GATE_FIELD_CANDIDATE_SHA = "candidate_sha"
_FINAL_GATE_FIELD_SUBJECT_SHA = "subject_sha"
_FINAL_GATE_FIELD_VALIDATION_ROOT = "validation_root"
_FINAL_GATE_FIELD_OUTCOME = "outcome"
_FINAL_GATE_FIELD_REASON = "reason"


class FinalContentGateOutcome(StrEnum):
    """Closed outcomes of the repository-root final content gate."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class FinalContentGateResult:
    """The finalization gate result retained at the integration boundary."""

    outcome: FinalContentGateOutcome
    reason: str


@dataclass(frozen=True)
class RootFinalizationResult:
    """The root-only receipt and SHA required to persist a delivered todo."""

    final_sha: str | None
    receipt: MarkerReceipt | None
    blocker: str | None


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

    rc, _, merge_stderr = _run_git(["merge", "--squash", key.branch], cwd=wt)

    # Guard: squash merge produced no content changes — candidate already integrated.
    # Catches squash merges where ancestry check (above) doesn't fire because
    # squash commits don't create ancestry links.
    #
    # Only a merge that SUCCEEDED may be read this way. An empty index proves the
    # candidate is already on main solely when the merge ran; a merge that failed
    # for any non-conflict reason also stages nothing, and `_get_conflicted_files`
    # returns an empty list both when there are no conflicts and when its own query
    # fails. Without the success check those two states are indistinguishable, and
    # a failed merge is recorded as a delivery: the fold runs, the candidate is
    # stamped delivered, and its branch is deleted while its content is nowhere on
    # main. Absence of a staged diff is not evidence about main unless the command
    # that would have produced one actually ran.
    empty_rc, _, _ = _run_git(["diff", "--cached", "--quiet"], cwd=wt)
    if empty_rc == 0 and rc == 0:
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

    if empty_rc == 0 and rc != 0 and not _get_conflicted_files(wt):
        # Nothing staged, the merge failed, and no conflict explains it. The
        # candidate's state is unknown, so it is surfaced rather than assumed.
        logger.error(
            "%s slug=%s squash merge failed without conflicts — refusing to infer delivery",
            _NEXT_INTEGRATE_PHASE_LOG,
            key.slug,
        )
        return False, _format_error(
            "MERGE_FAILED_WITHOUT_CONFLICTS",
            f"Squash merge of {key.branch} staged nothing and reported failure, with no conflicted "
            f"paths to explain it. The candidate has not been integrated and no delivery is "
            f"recorded. Inspect the integration worktree at {wt}, resolve the cause, then call "
            f"telec todo integrate again.\ngit stderr: {merge_stderr.strip() or '(empty)'}",
        )

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
    with blueprint_generation_lock(cwd, wait=True):
        rc, stdout, _stderr = _run_git(list(_ORIGIN_MAIN_REVISION_ARGUMENTS), cwd=cwd)
        resolved_baseline = stdout.strip() if rc == 0 else ""
        if not resolved_baseline:
            logger.warning(_BLUEPRINT_BASELINE_RESOLUTION_FAILURE, extra={"final_sha": baseline_sha})
            return _BLUEPRINT_BASELINE_RESOLUTION_FAILURE
        manifest = read_manifest(manifest_path(cwd))
        if manifest is None or manifest.status is not BlueprintStatus.OK or manifest.baseline_sha != resolved_baseline:
            manifest = regenerate_blueprint(cwd, baseline_sha=resolved_baseline)
    logger.info(
        _BLUEPRINT_REGENERATED_LOG,
        extra={
            "source": source,
            "baseline_sha": resolved_baseline,
            "final_sha": baseline_sha,
            "status": manifest.status.value,
        },
    )
    if manifest.status is not BlueprintStatus.OK:
        return (
            f"Blueprint regeneration did not complete (status={manifest.status.value}); "
            "blast-radius falls back to manual exploration until the next integrate."
        )
    logger.info(_BLUEPRINT_REGENERATED_AT_LOG, resolved_baseline)
    return None


def _step_push_succeeded(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    session_id: str,
    cwd: str,
) -> tuple[bool, str]:
    """Finalize the confirmed candidate through the repository-root delivery boundary."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "PUSH_SUCCEEDED phase has no candidate key")

    integration_wt = _integration_worktree_path(cwd)
    wt = str(integration_wt)
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

    finalization = _finalize_confirmed_candidate(
        cwd=cwd,
        session_id=session_id,
        integration_wt=integration_wt,
        slug=key.slug,
        candidate_sha=confirmed_sha,
    )
    if finalization.blocker is not None or finalization.final_sha is None or finalization.receipt is None:
        return False, finalization.blocker or _format_root_finalization_blocker(
            key.slug, "Root finalization produced no receipt."
        )
    final_sha = finalization.final_sha
    receipt = finalization.receipt

    checkpoint.pushed_sha = final_sha

    todos_db = get_todos_db_sync(cwd)
    delivered = todos_db.deliver_sync(
        key.slug,
        reconciliation_receipt=receipt,
        reconciliation_root=Path(cwd),
        commit=final_sha,
    )
    if not delivered:
        if key.slug in todos_db.delivered_slugs_sync():
            logger.info(
                "integration.delivery.already_delivered",
                extra={"slug": key.slug, "commit_sha": final_sha},
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
    checkpoint.warnings = warnings

    blueprint_warning = _regenerate_blueprint_after_delivery(
        cwd=cwd,
        baseline_sha=final_sha,
        source=_REPO_ROOT_SYNC_SOURCE,
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
    return cleanup_continues, cleanup_instruction


def _finalize_confirmed_candidate(
    *,
    cwd: str,
    session_id: str,
    integration_wt: Path,
    slug: str,
    candidate_sha: str,
) -> RootFinalizationResult:
    """Fold, validate, and publish the confirmed candidate from repository root."""
    repo_root_sync = _synchronize_repo_root(cwd=cwd, session_id=session_id, stage=RepoRootSyncStage.POST_DELIVERY)
    if not repo_root_sync.is_ready:
        return RootFinalizationResult(None, None, _format_repo_root_sync_instruction(repo_root_sync, project_root=cwd))

    reconciliation_root = Path(cwd)
    _, receipt, reconciliation_error = reassert_delivered_fold(reconciliation_root, slug)
    if reconciliation_error is not None:
        return RootFinalizationResult(None, None, _format_root_finalization_blocker(slug, reconciliation_error))
    residual_marker_error = assert_clean_before_push(reconciliation_root, slug)
    if residual_marker_error is not None:
        return RootFinalizationResult(None, None, _format_root_finalization_blocker(slug, residual_marker_error))

    subject_sha = _get_head_sha(cwd)
    if subject_sha is None:
        return RootFinalizationResult(
            None,
            None,
            _format_root_finalization_blocker(slug, _ROOT_HEAD_UNAVAILABLE_AFTER_RECONCILIATION),
        )
    reset_rc, _, reset_stderr = _run_git([*_VALIDATION_CHECKOUT_RESET_ARGS, subject_sha], cwd=str(integration_wt))
    if reset_rc != 0 or _get_head_sha(str(integration_wt)) != subject_sha:
        return RootFinalizationResult(
            None,
            None,
            _format_root_finalization_blocker(
                slug,
                _VALIDATION_CHECKOUT_RESET_FAILURE.format(
                    subject_sha=subject_sha,
                    stderr=reset_stderr.strip(),
                ),
            ),
        )

    final_gate = _run_final_content_gate(
        project_root=reconciliation_root,
        execution_root=integration_wt,
        subject_sha=subject_sha,
        slug=slug,
        candidate_sha=candidate_sha,
    )
    if final_gate.outcome is FinalContentGateOutcome.FAILED:
        return RootFinalizationResult(None, None, _format_root_finalization_blocker(slug, final_gate.reason))
    if _get_head_sha(cwd) != subject_sha:
        return RootFinalizationResult(
            None,
            None,
            _format_root_finalization_blocker(
                slug,
                _ROOT_HEAD_CHANGED_AFTER_VALIDATION,
            ),
        )

    publication = _publish_repo_root_main(
        cwd=cwd,
        synchronization=repo_root_sync,
        expected_source_head=subject_sha,
    )
    final_sha = publication.source_head
    if not publication.succeeded or final_sha is None:
        return RootFinalizationResult(
            None,
            None,
            _format_root_finalization_blocker(slug, publication.synchronization.diagnostic),
        )
    if _get_remote_main_sha(cwd) != final_sha:
        return RootFinalizationResult(
            None,
            None,
            _format_root_finalization_blocker(
                slug,
                _ROOT_PUBLICATION_CONFIRMATION_FAILURE.format(final_sha=final_sha),
            ),
        )
    return RootFinalizationResult(final_sha, receipt, None)


def _run_final_content_gate(
    *,
    project_root: Path,
    execution_root: Path,
    subject_sha: str,
    slug: str,
    candidate_sha: str,
) -> FinalContentGateResult:
    """Evaluate the folded repository-root subject in an isolated checkout."""
    if not resolve_capabilities(project_root).code:
        result = FinalContentGateResult(FinalContentGateOutcome.NOT_APPLICABLE, _NO_CODE_CAPABILITY_REASON)
    else:
        base_env = dict(os.environ)  # guard: direct-env-read - allowed: child-process environment construction
        for key in _QUALITY_ENV_REMOVED_KEYS:
            base_env.pop(key, None)
        runtime_env = resolve_runtime_environment(base_env)
        base_env[_PATH_ENV_KEY] = str(runtime_env[_PATH_ENV_KEY])
        shell = runtime_env.get(_SHELL_ENV_KEY)
        if isinstance(shell, str):
            base_env[_SHELL_ENV_KEY] = shell
        child_env = build_git_hook_env(str(project_root), base_env)
        gate_result = run_lint_gate(execution_root, subject_sha, None, False, child_env)
        outcome = (
            FinalContentGateOutcome.PASSED
            if gate_result.outcome is LintGateOutcome.PASSED
            else FinalContentGateOutcome.FAILED
        )
        result = FinalContentGateResult(outcome, gate_result.failure_reason or "")
    _emit_lifecycle_event(
        _FINAL_CONTENT_GATE_FINISHED_EVENT,
        {
            _FINAL_GATE_FIELD_SLUG: slug,
            _FINAL_GATE_FIELD_CANDIDATE_SHA: candidate_sha,
            _FINAL_GATE_FIELD_SUBJECT_SHA: subject_sha,
            _FINAL_GATE_FIELD_VALIDATION_ROOT: str(execution_root),
            _FINAL_GATE_FIELD_OUTCOME: result.outcome.value,
            _FINAL_GATE_FIELD_REASON: result.reason,
        },
    )
    return result


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
