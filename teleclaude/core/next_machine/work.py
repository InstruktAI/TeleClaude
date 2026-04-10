"""Work stage — Phase B state machine for deterministic builder work.

No imports from core.py (circular-import guard).
"""

# pylint: disable=cyclic-import  # Orchestration module bridges legacy next-machine/service boundaries.

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR, SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.integration_bridge import emit_branch_pushed, emit_deployment_started, emit_review_approved
from teleclaude.core.next_machine._types import (
    _SINGLE_FLIGHT_GUARD,
    NEXT_WORK_PHASE_LOG,
    REVIEW_DIFF_NOTE,
    FinalizeState,
    ItemPhase,
    PhaseName,
    PhaseStatus,
    StateValue,
)
from teleclaude.core.next_machine.build_gates import (
    format_build_gate_failure,
    run_build_gates,
    verify_artifacts,
)
from teleclaude.core.next_machine.git_ops import (
    _has_meaningful_diff,
    _merge_origin_main_into_worktree,
    compose_agent_guidance,
    get_head_commit,
    get_stash_entries,
    has_uncommitted_changes,
)
from teleclaude.core.next_machine.output_formatting import (
    ToolCallRequest,
    format_error,
    format_finalize_handoff_complete,
    format_stash_debt,
    format_tool_call,
    format_uncommitted_changes,
)
from teleclaude.core.next_machine.slug_resolution import (
    _get_item_phase_db,
    resolve_canonical_project_root,
    resolve_slug_async,
    set_item_phase_db,
)
from teleclaude.core.next_machine.state_io import (
    _is_review_round_limit_reached,
    _normalize_finalize_state,
    _review_scope_note,
    mark_phase,
)
from teleclaude.core.next_machine.worktrees import (
    ensure_worktree_with_policy_async,
)
from teleclaude.session_identity import get_session_id

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)

# Single-flight lock registry — one per (canonical_cwd, slug) pair.
# _SINGLE_FLIGHT_GUARD is the threading.Lock protecting mutations; defined in _types.
_SINGLE_FLIGHT_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


def _derive_work_statuses(current: str) -> tuple[str, str]:
    """Derive build and review status from the authoritative current state value."""
    from teleclaude.core.next_machine.work_lifecycle import (  # pylint: disable=import-outside-toplevel
        CURRENT_TO_BUILD_REVIEW,
    )

    return CURRENT_TO_BUILD_REVIEW.get(current, ("pending", "pending"))


@dataclass(frozen=True)
class _DispatchState:
    state: dict[str, StateValue]
    build_status: str
    review_status: str
    finalize_state: FinalizeState


async def _get_slug_single_flight_lock(cwd: str, slug: str) -> asyncio.Lock:
    """Return repo+slug lock keyed by canonical project root for strict isolation."""
    canonical_cwd = await asyncio.to_thread(resolve_canonical_project_root, cwd)
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
        from teleclaude.core.operations import emit_operation_progress  # pylint: disable=import-outside-toplevel

        emit_operation_progress(phase, decision, reason)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.debug("Operation progress emission skipped", exc_info=True)


async def next_work(db: Db, slug: str | None, cwd: str) -> str:  # pylint: disable=too-many-locals
    """Phase B state machine for deterministic builder work.

    Executes the build/review/fix/finalize cycle on prepared work items.
    Only considers items with current "prepared" and satisfied dependencies.

    Args:
        db: Database instance
        slug: Optional explicit slug (resolved from roadmap if not provided)
        cwd: Current working directory (project root)

    Returns:
        Plain text instructions for the orchestrator to execute
    """
    from teleclaude.core.todos_db import get_todos_db  # pylint: disable=import-outside-toplevel

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

    worktree_cwd, ensure_error = await _ensure_worktree_ready(cwd, resolved_slug, phase_slug)
    if ensure_error is not None:
        return ensure_error

    return await _dispatch_next_work(db, todos_db, cwd, worktree_cwd, resolved_slug, phase_slug)


async def _normalize_next_work_cwd(cwd: str) -> str:
    """Normalize the requested cwd to the canonical project root."""
    canonical_cwd = await asyncio.to_thread(resolve_canonical_project_root, cwd)
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

    deps = await todos_db.load_deps()
    found_slug, _, _ = await resolve_slug_async(todos_db, None, True, deps)
    if found_slug:
        _log_next_work_phase(found_slug, "slug_resolution", slug_resolution_started, "run", "resolved")
        return found_slug, None

    has_ready_items, _, _ = await resolve_slug_async(todos_db, None, True)
    if has_ready_items:
        _log_next_work_phase(
            phase_slug, "slug_resolution", slug_resolution_started, "error", "ready_but_deps_unsatisfied"
        )
        return "", format_error(
            "DEPS_UNSATISFIED",
            "Ready items exist but all have unsatisfied dependencies.",
            next_call="Complete dependency items first, or check the roadmap.",
        )

    _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "skip", "no_ready_items")
    return "", format_error(
        "NO_READY_ITEMS",
        "No ready items found in roadmap.",
        next_call="Call telec todo prepare to prepare items first.",
    )


async def _resolve_explicit_work_slug(
    todos_db: TodosDb,
    slug: str,
    phase_slug: str,
    slug_resolution_started: float,
) -> tuple[str, str | None]:
    """Resolve and validate an explicitly requested slug."""
    deps = await todos_db.load_deps()
    is_bug = await todos_db.is_bug_todo(slug)
    if not is_bug and not await todos_db.slug_in_roadmap(slug):
        await todos_db.add_to_roadmap(slug)
        logger.info("AUTO_ROADMAP_ADD slug=%s machine=work", slug)
        deps = await todos_db.load_deps()

    holder_error = None
    if not is_bug:
        slug, holder_error = await _resolve_holder_slug(todos_db, slug, deps, phase_slug, slug_resolution_started)
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
) -> tuple[str, str | None]:
    """Resolve runnable child work for holder todos."""
    from teleclaude.core.next_machine.slug_resolution import (  # pylint: disable=import-outside-toplevel
        resolve_first_runnable_holder_child_db,
    )

    holder_child, holder_reason = await resolve_first_runnable_holder_child_db(todos_db, slug, deps)
    if holder_child:
        return holder_child, None
    if holder_reason == "complete":
        _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "skip", "holder_complete")
        return "", f"COMPLETE: Holder '{slug}' has no remaining child work."
    if holder_reason == "deps_unsatisfied":
        _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "error", "holder_deps_unsatisfied")
        return "", format_error(
            "DEPS_UNSATISFIED",
            f"Holder '{slug}' has children, but none are currently runnable due to unsatisfied dependencies.",
            next_call="Complete dependency items first.",
        )
    if holder_reason == "item_not_ready":
        _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "error", "holder_not_ready")
        return "", format_error(
            "ITEM_NOT_READY",
            f"Holder '{slug}' has children, but none are ready to start work.",
            next_call=f"Call telec todo prepare on the child items for '{slug}' first.",
        )
    if holder_reason == "children_not_in_roadmap":
        _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "error", "holder_children_missing")
        return "", format_error(
            "NOT_PREPARED",
            f"Holder '{slug}' has child todos, but none are in roadmap.",
            next_call="Add child items to roadmap or call telec todo prepare.",
        )
    return slug, None


async def _validate_explicit_slug_readiness(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    todos_db: TodosDb,
    slug: str,
    phase: str,
    deps: dict[str, list[str]],
    phase_slug: str,
    slug_resolution_started: float,
) -> str | None:
    """Validate dispatch concerns only: done check and dependency satisfaction.

    Per-step prerequisites (DOR, artifacts, freshness) are handled by
    on_enter handlers in the lifecycle machine — not here.
    """
    if phase == ItemPhase.DONE.value:
        _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "skip", "item_done")
        return f"COMPLETE: Item '{slug}' is already done."
    delivered = await todos_db.delivered_slugs()
    slug_deps = deps.get(slug, [])
    if slug_deps and not all(d in delivered for d in slug_deps):
        _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "error", "deps_unsatisfied")
        return format_error(
            "DEPS_UNSATISFIED",
            f"Item '{slug}' has unsatisfied dependencies.",
            next_call="Complete dependency items first.",
        )
    return None


async def _validate_work_preconditions(cwd: str, resolved_slug: str) -> str | None:
    """Validate environmental preconditions only: stash debt.

    Per-step prerequisites (artifacts, freshness) are handled by
    on_enter handlers in the lifecycle machine.
    """
    preconditions_started = perf_counter()
    stash_entries = await asyncio.to_thread(get_stash_entries, cwd)
    if stash_entries:
        _log_next_work_phase(resolved_slug, "preconditions", preconditions_started, "error", "stash_debt")
        return format_stash_debt(resolved_slug, len(stash_entries))
    _log_next_work_phase(resolved_slug, "preconditions", preconditions_started, "run", "validated")
    return None


async def _ensure_worktree_ready(cwd: str, resolved_slug: str, phase_slug: str) -> tuple[str, str | None]:
    """Ensure the worktree exists and is prepared under the slug single-flight lock."""
    worktree_cwd = str(Path(cwd) / WORKTREE_DIR / resolved_slug)
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
            ensure_result = await ensure_worktree_with_policy_async(cwd, resolved_slug)
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
    except Exception as exc:  # pylint: disable=broad-exception-caught
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


async def _dispatch_next_work(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    db: Db, todos_db: TodosDb, cwd: str, worktree_cwd: str, resolved_slug: str, phase_slug: str
) -> str:  # pylint: disable=too-many-arguments,too-many-positional-arguments
    """Dispatch the appropriate next-work tool call from worktree-owned state."""
    dispatch_started = perf_counter()
    dispatch_state, state_error = await _prepare_dispatch_state(
        todos_db, cwd, worktree_cwd, resolved_slug, phase_slug, dispatch_started
    )
    if state_error is not None:
        return state_error
    if dispatch_state.review_status == PhaseStatus.APPROVED.value:
        return await _dispatch_review_approved(
            db, todos_db, cwd, worktree_cwd, resolved_slug, phase_slug, dispatch_started, dispatch_state
        )
    return await _dispatch_pre_review(
        db, todos_db, cwd, worktree_cwd, resolved_slug, phase_slug, dispatch_started, dispatch_state
    )


async def _prepare_dispatch_state(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    todos_db: TodosDb,
    cwd: str,
    worktree_cwd: str,
    resolved_slug: str,
    phase_slug: str,
    dispatch_started: float,
) -> tuple[_DispatchState, str | None]:
    """Load worktree phase state, claiming the item and repairing stale transitions."""
    # Merge origin/main BEFORE the uncommitted-changes check so that files
    # deleted on main (e.g. todos/) don't appear as false-positive drift.
    merge_err = await asyncio.to_thread(_merge_origin_main_into_worktree, worktree_cwd, resolved_slug)
    if merge_err:
        _log_next_work_phase(phase_slug, "merge_main", dispatch_started, "error", "merge_main_failed")
        return _DispatchState({}, "", "", {}), format_error("MERGE_MAIN_FAILED", merge_err)

    if has_uncommitted_changes(cwd, resolved_slug):
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "uncommitted_changes")
        return _DispatchState({}, "", "", {}), format_uncommitted_changes(resolved_slug)

    current_phase = await _get_item_phase_db(todos_db, resolved_slug)
    if current_phase == ItemPhase.PENDING.value:
        await set_item_phase_db(todos_db, resolved_slug, ItemPhase.IN_PROGRESS.value)

    state = await todos_db.read_state(resolved_slug)
    current = str(state.get("current", ""))

    # Derive build/review status from authoritative current value
    build_status, review_status = _derive_work_statuses(current)

    finalize_state = _normalize_finalize_state(state.get("finalize"))
    review_status = await _repair_stale_review_approval(
        worktree_cwd, resolved_slug, phase_slug, state, review_status, finalize_state
    )
    return _DispatchState(state, build_status, review_status, finalize_state), None


async def _repair_stale_review_approval(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    worktree_cwd: str,
    resolved_slug: str,
    phase_slug: str,
    state: dict[str, StateValue],
    review_status: str,
    finalize_state: FinalizeState,
) -> str:
    """Reset approved review state when new meaningful commits landed after approval."""
    finalize_status = finalize_state.get("status", "pending")
    if review_status != PhaseStatus.APPROVED.value or finalize_status in ("ready", "handed_off"):
        return review_status

    baseline_raw = state.get("review_baseline_commit")
    baseline = baseline_raw if isinstance(baseline_raw, str) else ""
    head_sha = await asyncio.to_thread(get_head_commit, worktree_cwd)
    if not (baseline and head_sha and baseline != head_sha):
        return review_status
    if not await asyncio.to_thread(_has_meaningful_diff, worktree_cwd, baseline, head_sha):
        return review_status

    repair_started = perf_counter()
    await asyncio.to_thread(mark_phase, worktree_cwd, resolved_slug, "review_pending")
    _log_next_work_phase(phase_slug, "state_repair", repair_started, "run", "review_approval_stale_baseline")
    return PhaseStatus.PENDING.value


async def _dispatch_pre_review(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    db: Db,
    todos_db: TodosDb,
    cwd: str,
    worktree_cwd: str,
    resolved_slug: str,
    phase_slug: str,
    dispatch_started: float,
    dispatch_state: _DispatchState,
) -> str:
    """Dispatch fix-review, build, or review based on the current pre-finalize state."""
    if dispatch_state.review_status == PhaseStatus.CHANGES_REQUESTED.value:
        return await _dispatch_fix_review(db, cwd, resolved_slug, phase_slug, dispatch_started)
    if dispatch_state.build_status != PhaseStatus.COMPLETE.value:
        return await _dispatch_build_phase(db, todos_db, cwd, resolved_slug, phase_slug, dispatch_started)
    return await _dispatch_review_phase(
        db, todos_db, cwd, worktree_cwd, resolved_slug, phase_slug, dispatch_started, dispatch_state.state
    )


async def _dispatch_fix_review(
    db: Db,
    cwd: str,
    resolved_slug: str,
    phase_slug: str,
    dispatch_started: float,
) -> str:
    """Dispatch the fixer loop after review requested changes."""
    try:
        guidance = await compose_agent_guidance(db)
    except RuntimeError as exc:
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
        return format_error("NO_AGENTS", str(exc))
    _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_fix_review")
    return format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_FIX_REVIEW,
            args=resolved_slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
            next_call=f"telec todo work {resolved_slug}",
            note=(
                "PEER CONVERSATION NOTE: If you still have the reviewer session alive from the "
                "previous review dispatch, prefer the direct conversation pattern from "
                "POST_COMPLETION[next-review-build] instead of a fresh fix-review dispatch: "
                "send fixer and reviewer session IDs to each other with --direct to let them "
                "iterate without context-destroying churn. This fallback path is for when the "
                "reviewer session has already ended."
            ),
        )
    )


async def _dispatch_build_phase(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    db: Db,
    todos_db: TodosDb,
    cwd: str,
    resolved_slug: str,
    phase_slug: str,
    dispatch_started: float,
) -> str:
    """Dispatch build or bug-fix work when the build phase is incomplete."""
    try:
        guidance = await compose_agent_guidance(db)
    except RuntimeError as exc:
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
        return format_error("NO_AGENTS", str(exc))

    pre_dispatch = f"telec todo mark-phase {resolved_slug} --phase build --status started"
    is_bug = await todos_db.is_bug_todo(resolved_slug)
    if is_bug:
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_bugs_fix")
        return format_tool_call(
            ToolCallRequest(
                command=SlashCommand.NEXT_BUGS_FIX,
                args=resolved_slug,
                project=cwd,
                guidance=guidance,
                subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
                next_call=f"telec todo work {resolved_slug}",
                pre_dispatch=pre_dispatch,
            )
        )

    _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_build")
    return format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_BUILD,
            args=resolved_slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
            next_call=f"telec todo work {resolved_slug}",
            pre_dispatch=pre_dispatch,
        )
    )


async def _dispatch_review_phase(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    db: Db,
    todos_db: TodosDb,
    cwd: str,
    worktree_cwd: str,
    resolved_slug: str,
    phase_slug: str,
    dispatch_started: float,
    state: dict[str, StateValue],
) -> str:
    """Run build/review gates, then dispatch review when eligible."""
    review_round_raw = state.get("review_round")
    review_round = review_round_raw if isinstance(review_round_raw, int) else 0

    gate_error = await _run_review_gates(todos_db, worktree_cwd, resolved_slug, phase_slug, review_round)
    if gate_error is not None:
        return gate_error

    limit_reached, current_round, max_rounds = _is_review_round_limit_reached(cwd, resolved_slug)
    if limit_reached:
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "review_round_limit")
        return format_error(
            "REVIEW_ROUND_LIMIT",
            (
                f"Review rounds exceeded for {resolved_slug}: "
                f"current={current_round}, max={max_rounds}. "
                f"Manual resolution required.\n\n"
                f"Before acting, load the relevant worker role:\n"
                f"  telec docs index\n"
                f"Then use telec docs get to load the procedure for the role you are assuming."
            ),
            next_call=f"telec todo work {resolved_slug}",
        )

    try:
        guidance = await compose_agent_guidance(db)
    except RuntimeError as exc:
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
        return format_error("NO_AGENTS", str(exc))
    _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_review")
    return format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_REVIEW_BUILD,
            args=resolved_slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
            next_call=f"telec todo work {resolved_slug}",
            note=f"{REVIEW_DIFF_NOTE}\n\n{_review_scope_note(cwd, resolved_slug)}",
        )
    )


async def _run_review_gates(
    todos_db: TodosDb,
    worktree_cwd: str,
    resolved_slug: str,
    phase_slug: str,
    review_round: int,
) -> str | None:
    """Execute build gates and artifact verification before review dispatch."""
    gate_started = perf_counter()
    gates_passed, gate_output = await asyncio.to_thread(run_build_gates, worktree_cwd, resolved_slug)
    if not gates_passed:
        return await _handle_gate_failure(
            worktree_cwd,
            resolved_slug,
            phase_slug,
            review_round,
            gate_started,
            gate_output,
            "build_gates_failed_post_review" if review_round > 0 else "build_gates_failed",
        )
    _log_next_work_phase(phase_slug, "gate_execution", gate_started, "run", "build_gates_passed")

    verify_started = perf_counter()
    is_bug = await todos_db.is_bug_todo(resolved_slug)
    artifacts_passed, artifacts_output = await asyncio.to_thread(
        verify_artifacts, worktree_cwd, resolved_slug, PhaseName.BUILD.value, is_bug=is_bug
    )
    if artifacts_passed:
        _log_next_work_phase(phase_slug, "gate_execution", verify_started, "run", "artifact_verification_passed")
        return None

    return await _handle_gate_failure(
        worktree_cwd,
        resolved_slug,
        phase_slug,
        review_round,
        verify_started,
        artifacts_output,
        "artifact_verification_failed_post_review" if review_round > 0 else "artifact_verification_failed",
    )


async def _handle_gate_failure(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    worktree_cwd: str,
    resolved_slug: str,
    phase_slug: str,
    review_round: int,
    started_at: float,
    gate_output: str,
    log_detail: str,
) -> str:
    """Apply retry-state bookkeeping after a failed build/review gate."""
    _log_next_work_phase(phase_slug, "gate_execution", started_at, "error", log_detail)
    if review_round == 0:
        await asyncio.to_thread(mark_phase, worktree_cwd, resolved_slug, "build_started")
    return format_build_gate_failure(resolved_slug, gate_output, f"telec todo work {resolved_slug}")


async def _dispatch_review_approved(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    db: Db,
    todos_db: TodosDb,
    cwd: str,
    worktree_cwd: str,
    resolved_slug: str,
    phase_slug: str,
    dispatch_started: float,
    dispatch_state: _DispatchState,
) -> str:
    """Handle review-approved states: finalize handoff, deferrals, or finalize dispatch."""
    finalize_status = dispatch_state.finalize_state.get("status")
    if finalize_status == "handed_off":
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "skip", "finalize_already_handed_off")
        return format_error(
            "FINALIZE_ALREADY_HANDED_OFF",
            f"{resolved_slug} has already been handed off to integration. Continue the queue without a slug.",
            next_call="telec todo work",
        )
    if finalize_status == "ready":
        return await _dispatch_finalize_handoff(
            db, worktree_cwd, resolved_slug, phase_slug, dispatch_state.finalize_state
        )
    if await todos_db.has_pending_deferrals(resolved_slug):
        return await _dispatch_deferrals(db, cwd, resolved_slug, phase_slug, dispatch_started)
    return await _dispatch_finalize_prepare(
        db, todos_db, cwd, resolved_slug, phase_slug, dispatch_started, dispatch_state.state
    )


async def _dispatch_finalize_handoff(
    db: Db,
    worktree_cwd: str,
    resolved_slug: str,
    phase_slug: str,
    finalize_state: FinalizeState,
) -> str:
    """Emit finalize handoff events and mark the finalize state as handed off."""
    branch = finalize_state.get("branch", "").strip()
    sha = finalize_state.get("sha", "").strip()
    worker_session_id = finalize_state.get("worker_session_id", "").strip()
    if not branch or not sha:
        _log_next_work_phase(phase_slug, "dispatch_decision", perf_counter(), "error", "finalize_state_invalid")
        return format_error(
            "FINALIZE_STATE_INVALID",
            f"{resolved_slug} finalize state is missing branch or sha; re-run finalize prepare.",
            next_call=f"telec todo work {resolved_slug}",
        )

    session_id = get_session_id() or ""
    handoff_started = perf_counter()
    try:
        await emit_branch_pushed(
            branch=branch,
            sha=sha,
            remote="origin",
            pusher=f"finalizer/{worker_session_id}" if worker_session_id else "",
        )
        await emit_deployment_started(
            slug=resolved_slug,
            branch=branch,
            sha=sha,
            worker_session_id=worker_session_id,
            ready_at=finalize_state.get("ready_at"),
        )
        await asyncio.to_thread(mark_phase, worktree_cwd, resolved_slug, "finalize_handed_off")
    except Exception as exc:  # pylint: disable=broad-exception-caught
        _log_next_work_phase(phase_slug, "dispatch_decision", handoff_started, "error", "finalize_handoff_failed")
        return format_error(
            "FINALIZE_HANDOFF_FAILED",
            f"Failed to emit finalize handoff for {resolved_slug}: {type(exc).__name__}: {exc}",
            next_call=f"telec todo work {resolved_slug}",
        )

    _log_next_work_phase(phase_slug, "dispatch_decision", handoff_started, "run", "finalize_handoff_emitted")
    child_session_ids = await _list_child_session_ids(db, session_id)
    return format_finalize_handoff_complete(resolved_slug, "telec todo work", child_session_ids)


async def _list_child_session_ids(db: Db, session_id: str) -> list[str]:
    """List child sessions spawned by the current orchestrator session."""
    if not session_id:
        return []
    try:
        child_sessions = await db.list_sessions(initiator_session_id=session_id)
        return [session.session_id for session in child_sessions]
    except Exception:  # pylint: disable=broad-exception-caught
        logger.warning("Failed to query child sessions for cleanup", session_id=session_id)
        return []


async def _dispatch_deferrals(
    db: Db,
    cwd: str,
    resolved_slug: str,
    phase_slug: str,
    dispatch_started: float,
) -> str:
    """Dispatch pending deferral handling for a review-approved slug."""
    try:
        guidance = await compose_agent_guidance(db)
    except RuntimeError as exc:
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
        return format_error("NO_AGENTS", str(exc))
    _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_defer")
    return format_tool_call(
        ToolCallRequest(
            command="next-defer",
            args=resolved_slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
            next_call=f"telec todo work {resolved_slug}",
        )
    )


async def _dispatch_finalize_prepare(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    db: Db,
    todos_db: TodosDb,
    cwd: str,
    resolved_slug: str,
    phase_slug: str,
    dispatch_started: float,
    state: dict[str, StateValue],
) -> str:
    """Dispatch finalize preparation after review approval."""
    if has_uncommitted_changes(cwd, resolved_slug):
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "uncommitted_changes")
        return format_uncommitted_changes(resolved_slug)
    try:
        guidance = await compose_agent_guidance(db)
    except RuntimeError as exc:
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
        return format_error("NO_AGENTS", str(exc))

    review_round_val = state.get("review_round")
    review_round = review_round_val if isinstance(review_round_val, int) else 1
    session_id = get_session_id() or ""
    try:
        await emit_review_approved(slug=resolved_slug, reviewer_session_id=session_id, review_round=review_round)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.warning("Failed to emit review.approved event for %s", resolved_slug, exc_info=True)

    is_bug = await todos_db.is_bug_todo(resolved_slug)
    note = "BUG FIX: Skip delivery bookkeeping. Delete todo directory after merge." if is_bug else ""
    _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_finalize")
    return format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_FINALIZE,
            args=resolved_slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
            next_call=f"telec todo work {resolved_slug}",
            note=note,
        )
    )


__all__ = ["next_work"]
