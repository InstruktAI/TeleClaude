"""Work stage — Phase B dispatcher.

Reads the canonical ``lifecycle_phase`` from persisted state and dispatches the
current work step. The only local mutation it owns is the transparent
``prepared`` to ``build_started`` handoff on first work entry.

Review fix loops preserve the peer-conversation contract: "send fixer and
reviewer session IDs to each other with --direct to let them iterate without
context-destroying churn."
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR, SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import (
    _SINGLE_FLIGHT_GUARD,
    _WORK_LOOP_LIMIT,
    NEXT_WORK_PHASE_LOG,
    ItemPhase,
    StateValue,
    WorkPhase,
)
from teleclaude.core.next_machine.artifacts import read_artifact_write_timestamps
from teleclaude.core.next_machine.git_ops import (
    DRIFT_PENDING,
    DRIFT_SUBSTANTIVE,
    ArtifactDriftStatus,
    WorktreeMergeOutcome,
    WorktreeMergeResult,
    _merge_origin_main_into_worktree,
    get_head_commit,
    get_stash_entries,
)
from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    apply_authoritative_signal,
    collapse_drift,
    derive_lifecycle_drift,
    is_work_lifecycle_phase,
    require_lifecycle_phase,
)
from teleclaude.core.next_machine.output_formatting import (
    MISSING_ACTIVE_TODO_MESSAGE_TEMPLATE,
    TERMINAL_DEPARTURE_DIRECTIVE,
    format_error,
    format_orchestration_watch_instruction,
    format_pending_classes_for_dispatch,
    format_send_command,
    format_stash_debt,
    format_work_entry_drift_bounce,
    format_work_returned_to_preparation,
)
from teleclaude.core.next_machine.runtime.sessions import find_live_session_for_slug
from teleclaude.core.next_machine.slug_resolution import (
    HolderResolutionMode,
    HolderResolutionReason,
    _get_item_phase_db,
    effective_delivered_slugs_for_dependencies,
    resolve_runnable_holder_children_db,
    set_item_phase_db,
)
from teleclaude.core.next_machine.state_io import ensure_quality_checklist
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.next_machine.work_lane_release import WorkLaneReturnReason, work_lane_return_follow_through
from teleclaude.core.next_machine.work_steps import _work_dispatch
from teleclaude.core.next_machine.worktrees import ensure_worktree_with_policy_async
from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root
from teleclaude.session_identity import get_session_id
from teleclaude.snippet_validation import snippet_body_digest_for

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

from teleclaude.core.operation_follow_through import defer_follow_through
from teleclaude.core.operation_progress import emit_operation_progress
from teleclaude.core.todos_db import get_todos_db
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

_NO_CURRENT_WORK_SCRIPT = (
    "NO_CURRENT_WORK_SLUG: Work orchestrator sessions are scoped to a single slug.\n\n"
    "Execute:\n\n"
    "telec sessions end\n\n"
    f"{TERMINAL_DEPARTURE_DIRECTIVE}\n\n"
    "No work-stage action is required. Daemon-runner pickup owns selecting future work."
)

logger = get_logger(__name__)

# Single-flight lock registry — one per (canonical_cwd, slug) pair.
# _SINGLE_FLIGHT_GUARD is the threading.Lock protecting mutations; defined in _types.
_SINGLE_FLIGHT_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}
_WORK_ENTRY_ACCEPTED_EVENT = "todo_work_entry_accepted"
_WORK_ENTRY_ROUTED_EVENT = "todo_work_entry_routed"
_WORK_ENTRY_ACCEPTED_MESSAGE = "todo work entry accepted"
_WORK_ENTRY_ROUTED_MESSAGE = "todo work entry routed"
_PREPARE_HANDOFF_OUTCOME = "prepare_handoff"
_NO_CALLER_SESSION_MESSAGE = "work entry returned the todo to preparation without a calling session to end"
_RESOURCE_ACTION_PRESERVE = "preserve"
_EMPTY_TEXT = ""
_WORK_ENTRY_MERGE_DECIDED_EVENT = "todo_work_entry_merge_decided"
_WORK_ENTRY_MERGE_DECIDED_MESSAGE = "todo work entry merge decided"
_WORKTREE_STATE_MISSING_CODE = "NO_STATE"
_BUILD_START_BASE_SHA_FIELD = "build_start_base_sha"
_WORKTREE_STATE_MISSING_MESSAGE_TEMPLATE = "No state record for {slug}; cannot resolve its build-start commit."
_WORKTREE_STATE_MISSING_NEXT_CALL_TEMPLATE = "Inspect todo state for {slug}, then retry work."
_GIT_STATUS_PORCELAIN = "--porcelain"
_GIT_STATUS_NUL_TERMINATED = "-z"
_GIT_STATUS_UNTRACKED_ALL = "--untracked-files=all"
_GIT_HEAD_REF = "HEAD"
_GIT_STATUS_ENTRY_SEPARATOR = b"\0"
_FINGERPRINT_SEPARATOR = b"\0"
_FINGERPRINT_UNTRACKED_PREFIX = b"?? "
_FINGERPRINT_FILE_KIND = b"file\0"
_FINGERPRINT_SYMLINK_KIND = b"symlink\0"
_FINALIZE_CLAIM_READY_STATUS = "ready"
_WORKTREE_FINGERPRINT_FAILED_MESSAGE = "Unable to fingerprint worktree at %s: %s"


async def _get_slug_single_flight_lock(cwd: str, slug: str) -> asyncio.Lock:
    """Return repo+slug lock keyed by canonical project root for strict isolation."""
    canonical_cwd = str(await asyncio.to_thread(resolve_project_root, cwd))
    key = (canonical_cwd, slug)
    with _SINGLE_FLIGHT_GUARD:
        lock = _SINGLE_FLIGHT_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _SINGLE_FLIGHT_LOCKS[key] = lock
    return lock


def _log_next_work_phase(slug: str, phase: str, started_at: float, decision: str, reason: str) -> None:
    """Emit grep-friendly phase timing logs for /todos/work."""
    elapsed_ms = int((perf_counter() - started_at) * 1000)
    phase_slug = slug or "<auto>"
    logger.info(
        "%s slug=%s phase=%s decision=%s reason=%s duration_ms=%d",
        NEXT_WORK_PHASE_LOG,
        phase_slug,
        phase,
        decision,
        reason,
        elapsed_ms,
    )
    try:
        emit_operation_progress(phase, decision, reason)
    except Exception:
        logger.debug("Operation progress emission skipped", exc_info=True)


def _worktree_fingerprint(worktree_cwd: str) -> str | None:
    """Hash tracked changes and non-ignored untracked contents for merge observation."""
    try:
        repo = Repo(worktree_cwd)
        status = repo.git.status(
            _GIT_STATUS_PORCELAIN,
            _GIT_STATUS_NUL_TERMINATED,
            _GIT_STATUS_UNTRACKED_ALL,
            stdout_as_string=False,
        )
        if not status:
            return _EMPTY_TEXT
        diff = repo.git.diff(_GIT_HEAD_REF, stdout_as_string=False)
        fingerprint = hashlib.sha256()
        fingerprint.update(status)
        fingerprint.update(_FINGERPRINT_SEPARATOR)
        fingerprint.update(diff)
        untracked_paths = sorted(
            entry[3:]
            for entry in status.split(_GIT_STATUS_ENTRY_SEPARATOR)
            if entry.startswith(_FINGERPRINT_UNTRACKED_PREFIX)
        )
        for path_bytes in untracked_paths:
            path = Path(worktree_cwd, os.fsdecode(path_bytes))
            if path.is_symlink():
                content = os.fsencode(os.readlink(path))
                kind = _FINGERPRINT_SYMLINK_KIND
            else:
                content = path.read_bytes()
                kind = _FINGERPRINT_FILE_KIND
            fingerprint.update(path_bytes)
            fingerprint.update(_FINGERPRINT_SEPARATOR)
            fingerprint.update(kind)
            fingerprint.update(hashlib.sha256(content).digest())
        return fingerprint.hexdigest()
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError) as exc:
        logger.warning(_WORKTREE_FINGERPRINT_FAILED_MESSAGE, worktree_cwd, str(exc))
        return None


def _format_holder_work_commands(holder_slug: str, child_slugs: tuple[str, ...]) -> str:
    """Format child work commands for a holder entrypoint."""
    commands = "\n".join(f"telec todo work {child}" for child in child_slugs)
    return (
        f"HOLDER_WORK: Holder '{holder_slug}' has runnable child work.\n\n"
        "Execute these child work commands. They may be run in parallel:\n\n"
        f"{commands}\n\n"
        f"Do not dispatch build/review/fix/finalize for holder '{holder_slug}' itself."
    )


def _format_no_current_work_slug() -> str:
    """Format the terminal no-slug response for per-slug work orchestration."""
    return _NO_CURRENT_WORK_SCRIPT


async def next_work(db: Db, slug: str | None, cwd: str) -> str:
    """Phase B state machine for deterministic builder work.

    Reads durable state from ``.teleclaude/todos.db``, dispatches the current stored work
    phase via :func:`_work_dispatch`, and loops only when a handler performs an
    explicit state mutation that still requires another local dispatch.

    Args:
        db: Database instance
        slug: Optional explicit slug (resolved from todo list if not provided)
        cwd: Current working directory (project root)

    Returns:
        Plain text instructions for the orchestrator to execute
    """
    cwd = await _normalize_next_work_cwd(cwd)
    todos_db = await get_todos_db(cwd)

    phase_slug = slug or "<auto>"
    resolved_slug, slug_error = await _resolve_work_slug(todos_db, slug, phase_slug)
    if slug_error is not None:
        return slug_error

    phase_slug = resolved_slug
    precondition_error = await _validate_work_preconditions(cwd, resolved_slug)
    if precondition_error is not None:
        return precondition_error

    _log_work_entry_accepted(resolved_slug)
    kickback_handoff = await _check_work_entry_kickback(db, todos_db, resolved_slug, cwd)
    if kickback_handoff is not None:
        return kickback_handoff

    drift_error = await _check_work_entry_drift(db, todos_db, resolved_slug, cwd, phase_slug)
    if drift_error is not None:
        return drift_error

    worktree_cwd, ensure_error = await _ensure_worktree_ready(cwd, resolved_slug, phase_slug, todos_db)
    if ensure_error is not None:
        return ensure_error

    # Preserve a published finalize candidate; otherwise sync before dispatch.
    merge_started = perf_counter()
    merge_state = await todos_db.read_state(resolved_slug)
    finalize_raw = merge_state.get("finalize") if merge_state is not None else None
    finalize_state = finalize_raw if isinstance(finalize_raw, dict) else {}
    finalize_status = finalize_state.get("status")
    lifecycle_phase = merge_state.get("lifecycle_phase") if merge_state is not None else None
    finalize_claimed = (
        finalize_status == _FINALIZE_CLAIM_READY_STATUS or lifecycle_phase == LifecyclePhase.FINALIZE_READY.value
    )
    worktree_fingerprint_before = await asyncio.to_thread(_worktree_fingerprint, worktree_cwd)
    if finalize_claimed:
        head_before = await asyncio.to_thread(get_head_commit, worktree_cwd)
        merge_result = WorktreeMergeResult(
            WorktreeMergeOutcome.DEFERRED_FINALIZE_CLAIM,
            head_before,
            head_before,
            _EMPTY_TEXT,
        )
    else:
        merge_result = await asyncio.to_thread(_merge_origin_main_into_worktree, worktree_cwd, resolved_slug)
    worktree_fingerprint_after = await asyncio.to_thread(_worktree_fingerprint, worktree_cwd)
    logger.info(
        _WORK_ENTRY_MERGE_DECIDED_MESSAGE,
        event=_WORK_ENTRY_MERGE_DECIDED_EVENT,
        slug=resolved_slug,
        outcome=merge_result.outcome,
        head_before=merge_result.head_before,
        head_after=merge_result.head_after,
        caller_session_id=get_session_id() or _EMPTY_TEXT,
        worktree_fingerprint_before=worktree_fingerprint_before,
        worktree_fingerprint_after=worktree_fingerprint_after,
    )
    if merge_result.outcome == WorktreeMergeOutcome.CONFLICT:
        _log_next_work_phase(phase_slug, "merge_main", merge_started, "error", "merge_main_failed")
        state = await todos_db.read_state(resolved_slug)
        phase_raw = state.get("lifecycle_phase") if state is not None else ""
        lifecycle_phase = phase_raw if isinstance(phase_raw, str) else ""
        return await _format_merge_main_recovery(
            db,
            resolved_slug,
            merge_result.message,
            lifecycle_phase=lifecycle_phase,
        )
    head_after_merge = merge_result.head_after
    _log_next_work_phase(phase_slug, "merge_main", merge_started, "run", merge_result.outcome.value)

    # Ensure item phase is IN_PROGRESS on first work entry.
    current_phase = await _get_item_phase_db(todos_db, resolved_slug)
    if current_phase == ItemPhase.PENDING.value:
        await set_item_phase_db(todos_db, resolved_slug, ItemPhase.IN_PROGRESS.value)

    # Dispatch loop — each iteration reads the authoritative lifecycle pointer and dispatches.
    for _iter in range(_WORK_LOOP_LIMIT):
        state = await todos_db.read_state(resolved_slug)
        if state is None:
            return format_error(
                "NO_STATE",
                f"No state record for {resolved_slug}. Run telec todo prepare {resolved_slug} first.",
                next_call=f"telec todo prepare {resolved_slug}",
            )

        writer = StateWriter(state)
        current_phase = require_lifecycle_phase(writer.state.lifecycle_phase, context=f"next_work({resolved_slug})")
        if current_phase == LifecyclePhase.PREPARED:
            phase_started = perf_counter()
            await _advance_prepared_to_build_started(todos_db, resolved_slug, state, worktree_cwd)
            _log_next_work_phase(
                phase_slug,
                "prepared_handoff",
                phase_started,
                "run",
                LifecyclePhase.BUILD_STARTED.value,
            )
            continue
        else:
            try:
                phase = WorkPhase(current_phase.value)
            except ValueError:
                return format_error(
                    "NOT_PREPARED",
                    f"{resolved_slug} is still in prepare phase '{current_phase.value}'. Run telec todo prepare first.",
                    next_call=f"telec todo prepare {resolved_slug}",
                )
        logger.info(
            "NEXT_WORK_PHASE slug=%s phase=%s iter=%d",
            resolved_slug,
            phase.value,
            _iter,
        )

        dispatch_started = perf_counter()
        keep_going, instruction = await _work_dispatch(
            db=db,
            todos_db=todos_db,
            slug=resolved_slug,
            cwd=cwd,
            worktree_cwd=worktree_cwd,
            phase=WorkPhase(phase.value),
            state=state,
            head_after_merge=head_after_merge,
        )
        _log_next_work_phase(
            phase_slug,
            "dispatch_decision",
            dispatch_started,
            "run" if keep_going else "dispatch",
            phase.value,
        )
        if not keep_going:
            return instruction

    return (
        f"LOOP_LIMIT: work state machine for {resolved_slug} exceeded "
        f"{_WORK_LOOP_LIMIT} internal transitions. "
        f"Inspect state for {resolved_slug} for stuck state."
    )


async def _advance_prepared_to_build_started(
    todos_db: TodosDb,
    slug: str,
    state: dict[str, StateValue],
    worktree_cwd: str,
) -> None:
    """Persist the work-entry transition."""
    await ensure_quality_checklist(todos_db, slug)
    writer = StateWriter(state)
    artifact_write_timestamps = await read_artifact_write_timestamps(todos_db, slug)
    apply_authoritative_signal(
        writer.state, "build_started", worktree_cwd=worktree_cwd, artifact_write_timestamps=artifact_write_timestamps
    )
    await writer.commit(todos_db, slug)


async def _format_merge_main_recovery(db: Db, slug: str, merge_error: str, *, lifecycle_phase: str) -> str:
    """Format orchestrator recovery instructions for work-entry main-sync conflicts."""
    builder_id = await find_live_session_for_slug(db, slug, f"/{SlashCommand.BUILD.value}")
    if builder_id is None:
        return format_error(
            "MERGE_MAIN_FAILED",
            (
                f"{merge_error}\n\n"
                f"`telec todo work {slug}` hit a pre-dispatch merge failure, but no live builder "
                "session exists for the orchestrator to route recovery to."
            ),
            next_call=f"telec todo work {slug}",
        )

    completion_clause = _merge_main_recovery_completion_clause(slug, lifecycle_phase)
    wait_clause = _merge_main_recovery_wait_clause(slug, lifecycle_phase)
    message = (
        f"The orchestrator hit a merge failure while running `telec todo work {slug}` against your worktree. "
        "You did not encounter this directly; the orchestrator is routing the work-entry failure back to you.\n\n"
        "Recover the worktree: preserve accepted origin/main behavior as the leading baseline, reapply this todo's "
        "prepared intent from implementation-plan and PRD/input on top, resolve the conflicts, run relevant focused "
        f"tests plus telec code test and telec code lint, commit the resolution, then {completion_clause}\n\n"
        f"Work-entry merge failure:\n{merge_error}"
    )
    return (
        f"MERGE MAIN RECOVERY REQUIRED: {slug}\n\n"
        "Work entry hit a recoverable worktree merge failure before it could continue.\n\n"
        "Execute in order:\n\n"
        f"{format_send_command(builder_id, message)}\n\n"
        f"{format_orchestration_watch_instruction(slug=slug, restart_cadence=True)}\n"
        f"{wait_clause}"
    )


def _merge_main_recovery_completion_clause(slug: str, lifecycle_phase: str) -> str:
    """Return phase-appropriate worker completion guidance for main-sync recovery."""
    if lifecycle_phase in (LifecyclePhase.BUILD_STARTED.value, LifecyclePhase.REVIEW_CHANGES_REQUESTED.value):
        return f"run `telec todo stamp {slug} --build-complete` and report completion."
    if lifecycle_phase == LifecyclePhase.BUILD_COMPLETE.value:
        return (
            "report MERGE RECOVERY COMPLETE. "
            "The orchestrator will re-enter `telec todo work` to dispatch review from the recovered HEAD."
        )
    if lifecycle_phase == LifecyclePhase.REVIEW_APPROVED.value:
        return (
            "report MERGE RECOVERY COMPLETE. "
            "The orchestrator will re-enter `telec todo work` to continue finalize from the recovered HEAD."
        )
    if lifecycle_phase == LifecyclePhase.FINALIZE_READY.value:
        return (
            "report MERGE RECOVERY COMPLETE. "
            "The orchestrator will re-enter `telec todo work` to validate the finalize-ready handoff."
        )
    return (
        "report MERGE RECOVERY COMPLETE and name the lifecycle phase you observed. "
        "The orchestrator will re-enter `telec todo work` to choose the next lifecycle action."
    )


def _merge_main_recovery_wait_clause(slug: str, lifecycle_phase: str) -> str:
    """Return the orchestrator wait instruction after sending merge recovery guidance."""
    if lifecycle_phase in (LifecyclePhase.BUILD_STARTED.value, LifecyclePhase.REVIEW_CHANGES_REQUESTED.value):
        return f"When the builder reports idle after re-stamping, call telec todo work {slug}."
    return f"When the builder reports idle after MERGE RECOVERY COMPLETE, call telec todo work {slug}."


async def _check_work_entry_drift(
    db: Db, todos_db: TodosDb, resolved_slug: str, cwd: str, phase_slug: str
) -> str | None:
    """Own the work-entry drift path before any worktree setup can run.

    Re-derives drift, then branches three ways on the collapsed verdict: a
    ``pending`` artifact dispatches the drift analyzer and re-enters work once it
    idles; a ``substantive`` artifact returns the todo to preparation through the
    lifecycle runner (the platform releases the claim and ends this work lane, and
    the runner dispatches a fresh prepare orchestrator); ``cosmetic`` and ``fresh``
    are non-blocking and proceed to worktree creation. The work orchestrator never
    enters the prepare machine itself.
    """
    drift_started = perf_counter()
    state = await todos_db.read_state(resolved_slug)
    if state is None:
        _log_next_work_phase(phase_slug, "drift_check", drift_started, "bounce", "missing_state")
        return format_error(
            "NO_STATE",
            f"No state record for {resolved_slug}. Run telec todo prepare {resolved_slug} first.",
            next_call=f"telec todo prepare {resolved_slug}",
        )
    writer = StateWriter(state)
    current_phase = require_lifecycle_phase(
        writer.state.lifecycle_phase,
        context=f"work_entry_drift({resolved_slug})",
    )
    drift_result = await derive_lifecycle_drift(
        resolved_slug,
        writer.state,
        repo_root=cwd,
        todos_db=todos_db,
        snippet_digest_fn=snippet_body_digest_for(cwd),
        writer=writer,
    )
    await writer.commit(todos_db, resolved_slug)
    drift = collapse_drift(drift_result)
    verdict = _work_entry_drift_verdict(drift, current_phase)
    if verdict is None:
        _log_next_work_phase(phase_slug, "drift_check", drift_started, "proceed", "fresh")
        return None
    reason = _work_entry_drift_reason(drift, current_phase)
    if verdict == DRIFT_PENDING:
        _log_next_work_phase(phase_slug, "drift_check", drift_started, "bounce", reason)
        return format_work_entry_drift_bounce(
            slug=resolved_slug,
            project_root=cwd,
            pending_classes=format_pending_classes_for_dispatch(drift_result),
        )
    _log_work_entry_routed(writer, resolved_slug, WorkLaneReturnReason.SUBSTANTIVE_DRIFT)
    _log_next_work_phase(phase_slug, "drift_check", drift_started, "handoff", reason)
    return _return_to_preparation(db, cwd, resolved_slug, WorkLaneReturnReason.SUBSTANTIVE_DRIFT)


async def _check_work_entry_kickback(db: Db, todos_db: TodosDb, resolved_slug: str, cwd: str) -> str | None:
    """Recognize a kickback on work re-entry and return the todo to preparation.

    A kickback (``telec todo stamp <slug> --kickback``) invalidates the implementation-plan
    by marking ``plan_review.cleared_by_substantive_drift``. After a *work* call the stored
    ``lifecycle_phase`` is still a work phase, so the cleared flag is the durable signal — and
    it is unique to a kickback here (drift-analyze substantive verdicts occur only in the
    prepare lane, where the plan is re-approved and the flag self-clears before work resumes).

    The worktree, branch, workspace, and build commits are preserved. The claiming work
    orchestrator and the sessions it started are ended by the platform, not by any agent.
    """
    kickback_started = perf_counter()
    state = await todos_db.read_state(resolved_slug)
    if state is None:
        return None
    writer = StateWriter(state)
    if not writer.state.plan_review.cleared_by_substantive_drift:
        return None

    _log_work_entry_routed(writer, resolved_slug, WorkLaneReturnReason.KICKBACK)
    _log_next_work_phase(resolved_slug, "kickback_handoff", kickback_started, "handoff", WorkLaneReturnReason.KICKBACK)
    return _return_to_preparation(db, cwd, resolved_slug, WorkLaneReturnReason.KICKBACK)


def _return_to_preparation(db: Db, cwd: str, slug: str, reason: WorkLaneReturnReason) -> str:
    """Defer the work-lane release until this work entry has answered, and say so.

    The calling session is the work orchestrator the operator door bound to the slug.
    The release runs after the operation's result is recorded and delivered, so every
    session of the lane ends only after the machine has answered its call.
    """
    orchestrator_session_id = get_session_id()
    if orchestrator_session_id is None:
        raise RuntimeError(_NO_CALLER_SESSION_MESSAGE)
    defer_follow_through(
        work_lane_return_follow_through(
            db,
            slug=slug,
            project_root=cwd,
            orchestrator_session_id=orchestrator_session_id,
            reason=reason,
        )
    )
    return format_work_returned_to_preparation(slug, reason.value)


def _log_work_entry_accepted(slug: str) -> None:
    logger.info(
        _WORK_ENTRY_ACCEPTED_MESSAGE,
        event=_WORK_ENTRY_ACCEPTED_EVENT,
        slug=slug,
        caller_session_id=get_session_id() or _EMPTY_TEXT,
    )


def _log_work_entry_routed(writer: StateWriter, slug: str, reason: WorkLaneReturnReason) -> None:
    logger.info(
        _WORK_ENTRY_ROUTED_MESSAGE,
        event=_WORK_ENTRY_ROUTED_EVENT,
        outcome=_PREPARE_HANDOFF_OUTCOME,
        reason=reason.value,
        slug=slug,
        caller_session_id=get_session_id() or _EMPTY_TEXT,
        build_residue_present=bool(writer.state.build_start_base_sha),
        old_plan_digest=writer.state.build_plan_digest,
        current_plan_digest=writer.state.artifacts.implementation_plan.digest,
        resource_action=_RESOURCE_ACTION_PRESERVE,
    )


def _work_entry_drift_verdict(
    drift: dict[str, ArtifactDriftStatus], phase: LifecyclePhase
) -> ArtifactDriftStatus | None:
    """Collapse per-artifact drift into the single actionable work-entry verdict.

    ``pending`` takes precedence over ``substantive``: any unreviewed artifact
    must be analyzed before the claim-holder is promoted, so the analyzer runs
    first and the substantive promotion happens on a later re-entry once every
    artifact carries a verdict. ``cosmetic`` and ``fresh`` are non-blocking and
    collapse to ``None``. Phase gates which statuses are actionable — at a work
    phase only ``substantive`` blocks, so ``pending`` mid-build proceeds.
    """
    blocking = _work_entry_blocking_statuses(phase)
    statuses = set(drift.values())
    if DRIFT_PENDING in blocking and DRIFT_PENDING in statuses:
        return DRIFT_PENDING
    if DRIFT_SUBSTANTIVE in blocking and DRIFT_SUBSTANTIVE in statuses:
        return DRIFT_SUBSTANTIVE
    return None


def _work_entry_drift_reason(drift: dict[str, ArtifactDriftStatus], phase: LifecyclePhase) -> str:
    blocking_statuses = _work_entry_blocking_statuses(phase)
    blocking = {artifact: status for artifact, status in drift.items() if status in blocking_statuses}
    return ",".join(f"{artifact}:{status}" for artifact, status in sorted(blocking.items()))


def _work_entry_blocking_statuses(phase: LifecyclePhase) -> tuple[ArtifactDriftStatus, ...]:
    if is_work_lifecycle_phase(phase):
        return (DRIFT_SUBSTANTIVE,)
    return (DRIFT_PENDING, DRIFT_SUBSTANTIVE)


async def _normalize_next_work_cwd(cwd: str) -> str:
    """Normalize the requested cwd to the canonical project root."""
    canonical_cwd = str(await asyncio.to_thread(resolve_project_root, cwd))
    if canonical_cwd != cwd:
        logger.debug(
            "next_work normalized cwd to canonical project root", requested_cwd=cwd, canonical_cwd=canonical_cwd
        )
    return canonical_cwd


async def _resolve_work_slug(todos_db: TodosDb, slug: str | None, phase_slug: str) -> tuple[str, str | None]:
    """Resolve the target slug or return a formatted early-exit message."""
    slug_resolution_started = perf_counter()
    if slug is not None:
        resolved_slug, error = await _resolve_explicit_work_slug(todos_db, slug, phase_slug, slug_resolution_started)
        if error is not None:
            return "", error
        _log_next_work_phase(resolved_slug, "slug_resolution", slug_resolution_started, "run", "resolved")
        return resolved_slug, None

    _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "skip", "no_current_slug")
    return "", _format_no_current_work_slug()


async def _resolve_explicit_work_slug(
    todos_db: TodosDb,
    slug: str,
    phase_slug: str,
    slug_resolution_started: float,
) -> tuple[str, str | None]:
    """Resolve and validate an explicitly requested slug."""
    deps = await todos_db.load_deps()
    is_bug = await todos_db.is_bug_todo(slug)
    # Holder status resolves before the lifecycle-membership guard: a holder
    # slug never matches slug_in_todo (active/icebox only), so checking
    # membership first would reject it as not-found before the holder
    # resolver below ever runs.
    is_holder_slug = not is_bug and await todos_db.is_holder(slug)
    delivered = set()
    if not is_bug:
        delivered = await todos_db.delivered_slugs()
    if not is_bug and not is_holder_slug and slug not in delivered and not await todos_db.slug_in_todo(slug):
        return "", format_error(
            "TODO_NOT_FOUND",
            MISSING_ACTIVE_TODO_MESSAGE_TEMPLATE.format(slug=slug),
        )

    holder_error = None
    if not is_bug:
        slug, holder_error = await _resolve_holder_slug(
            todos_db, slug, deps, phase_slug, slug_resolution_started, is_holder_slug=is_holder_slug
        )
        if holder_error is not None:
            return "", holder_error

    phase = await _get_item_phase_db(todos_db, slug)
    readiness_error = await _validate_explicit_slug_readiness(
        todos_db, slug, phase, deps, phase_slug, slug_resolution_started
    )
    if readiness_error is not None:
        return "", readiness_error
    return slug, None


async def _resolve_holder_slug(
    todos_db: TodosDb,
    slug: str,
    deps: dict[str, list[str]],
    phase_slug: str,
    slug_resolution_started: float,
    *,
    is_holder_slug: bool,
) -> tuple[str, str | None]:
    """Resolve runnable child work for holder todos.

    ``is_holder_slug`` is the row's own status, read before this resolver
    runs. A row that is genuinely a holder but currently has no live
    children resolves as an ended group, never as an ordinary not-found —
    the row is outside the todo lifecycle for good, not merely empty today.
    """
    holder_resolution = await resolve_runnable_holder_children_db(todos_db, slug, deps, mode=HolderResolutionMode.WORK)
    holder_reason = holder_resolution.reason
    if holder_resolution.runnable:
        return "", _format_holder_work_commands(slug, holder_resolution.runnable)
    if holder_reason is HolderResolutionReason.NOT_HOLDER:
        if is_holder_slug:
            _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "skip", "holder_ended_group")
            return "", (
                f"ENDED: Holder '{slug}' has no children — its group has ended. "
                "It is outside the todo lifecycle; nothing further runs against it."
            )
        return slug, None
    if holder_reason is HolderResolutionReason.COMPLETE:
        _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "skip", "holder_complete")
        return "", f"COMPLETE: Holder '{slug}' has no remaining child work."
    if holder_reason is HolderResolutionReason.DEPS_UNSATISFIED:
        _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "error", "holder_deps_unsatisfied")
        return "", format_error(
            "DEPS_UNSATISFIED",
            f"Holder '{slug}' has children, but none are currently runnable due to unsatisfied dependencies.",
            next_call="Complete dependency items first.",
        )
    if holder_reason is HolderResolutionReason.ITEM_NOT_READY:
        _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "error", "holder_not_ready")
        return "", format_error(
            "ITEM_NOT_READY",
            f"Holder '{slug}' has children, but none are ready to start work.",
            next_call=f"Call telec todo prepare on the child items for '{slug}' first.",
        )
    if holder_reason is HolderResolutionReason.CHILDREN_NOT_IN_TODO:
        _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "error", "holder_children_missing")
        return "", format_error(
            "NOT_PREPARED",
            f"Holder '{slug}' has child todos, but none are in the todo list.",
            next_call="Add child items to the todo list or call telec todo prepare.",
        )
    return slug, None


async def _validate_explicit_slug_readiness(
    todos_db: TodosDb,
    slug: str,
    phase: str,
    deps: dict[str, list[str]],
    phase_slug: str,
    slug_resolution_started: float,
) -> str | None:
    """Validate dispatch concerns only: done check and dependency satisfaction.

    Per-step prerequisites (DOR, artifacts, freshness) are handled by
    derivation + step handlers in the work loop — not here.
    """
    if phase == ItemPhase.DONE.value:
        _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "skip", "item_done")
        return f"COMPLETE: Item '{slug}' is already done."
    delivered = await todos_db.delivered_slugs()
    dependency_delivered = await effective_delivered_slugs_for_dependencies(todos_db, delivered)
    slug_deps = deps.get(slug, [])
    if slug_deps and not all(dep in dependency_delivered for dep in slug_deps):
        _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "error", "deps_unsatisfied")
        return format_error(
            "DEPS_UNSATISFIED",
            f"Item '{slug}' has unsatisfied dependencies.",
            next_call="Complete dependency items first.",
        )
    return None


async def _validate_work_preconditions(cwd: str, resolved_slug: str) -> str | None:
    """Validate environmental preconditions only: stash debt."""
    preconditions_started = perf_counter()
    stash_entries = await asyncio.to_thread(get_stash_entries, cwd)
    if stash_entries:
        _log_next_work_phase(resolved_slug, "preconditions", preconditions_started, "error", "stash_debt")
        return format_stash_debt(resolved_slug, len(stash_entries))
    _log_next_work_phase(resolved_slug, "preconditions", preconditions_started, "run", "validated")
    return None


async def _ensure_worktree_ready(
    cwd: str, resolved_slug: str, phase_slug: str, todos_db: TodosDb
) -> tuple[str, str | None]:
    """Ensure the worktree exists and is prepared under the slug single-flight lock."""
    worktree_cwd = str(Path(cwd) / WORKTREE_DIR / resolved_slug)
    todo_state = await todos_db.read_state(resolved_slug)
    if todo_state is None:
        return worktree_cwd, format_error(
            _WORKTREE_STATE_MISSING_CODE,
            _WORKTREE_STATE_MISSING_MESSAGE_TEMPLATE.format(slug=resolved_slug),
            next_call=_WORKTREE_STATE_MISSING_NEXT_CALL_TEMPLATE.format(slug=resolved_slug),
        )
    build_start_sha_raw = todo_state.get(_BUILD_START_BASE_SHA_FIELD, _EMPTY_TEXT)
    build_start_sha = build_start_sha_raw if isinstance(build_start_sha_raw, str) else _EMPTY_TEXT
    ensure_started = perf_counter()
    slug_lock = await _get_slug_single_flight_lock(cwd, resolved_slug)
    if slug_lock.locked():
        logger.info(
            "%s slug=%s phase=ensure_prepare decision=wait reason=single_flight_in_progress duration_ms=0",
            NEXT_WORK_PHASE_LOG,
            phase_slug,
        )

    try:
        async with slug_lock:
            logger.info(
                "next_work entering ensure boundary slug=%s cwd=%s worktree_path=%s", resolved_slug, cwd, worktree_cwd
            )
            ensure_result = await ensure_worktree_with_policy_async(cwd, resolved_slug, build_start_sha=build_start_sha)
            if ensure_result.created:
                logger.info("Created new worktree for %s", resolved_slug)
            ensure_decision = "run" if ensure_result.prepared else "skip"
            _log_next_work_phase(
                phase_slug, "ensure_prepare", ensure_started, ensure_decision, ensure_result.prep_reason
            )
    except RuntimeError as exc:
        logger.error(
            "next_work worktree preparation failed for slug=%s cwd=%s worktree_path=%s: %s",
            resolved_slug,
            cwd,
            worktree_cwd,
            exc,
            exc_info=True,
        )
        _log_next_work_phase(phase_slug, "ensure_prepare", ensure_started, "error", "prep_failed")
        return worktree_cwd, format_error(
            "WORKTREE_PREP_FAILED",
            str(exc),
            next_call="Add tools/worktree-prepare.sh or fix its execution, then retry.",
        )
    except Exception as exc:
        logger.error(
            "next_work worktree setup failed for slug=%s cwd=%s worktree_path=%s: %s",
            resolved_slug,
            cwd,
            worktree_cwd,
            exc,
            exc_info=True,
        )
        _log_next_work_phase(phase_slug, "ensure_prepare", ensure_started, "error", f"unexpected_{type(exc).__name__}")
        return worktree_cwd, format_error(
            "WORKTREE_SETUP_FAILED",
            f"Unexpected error while ensuring worktree for {resolved_slug}: {type(exc).__name__}: {exc}",
            next_call="Inspect daemon logs for worktree setup failure, fix the repository or branch state, then retry.",
        )
    return worktree_cwd, None


__all__ = ["next_work"]
