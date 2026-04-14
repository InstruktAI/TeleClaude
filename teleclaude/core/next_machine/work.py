"""Work stage — Phase B state machine for deterministic builder work.

Loop shaped like :func:`teleclaude.core.next_machine.prepare.next_prepare`:
each iteration re-derives :class:`WorkPhase` from state primitives + the
worktree git log + build-gate results, then routes through
:func:`_work_dispatch`. No persistent ``current`` value, no mark-phase calls.

No imports from core.py (circular-import guard).
"""

# pylint: disable=cyclic-import  # Orchestration module bridges legacy next-machine/service boundaries.

from __future__ import annotations

import asyncio
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import (
    _SINGLE_FLIGHT_GUARD,
    _WORK_LOOP_LIMIT,
    NEXT_WORK_PHASE_LOG,
    ItemPhase,
)
from teleclaude.core.next_machine.git_ops import (
    _merge_origin_main_into_worktree,
    get_head_commit,
    get_stash_entries,
)
from teleclaude.core.next_machine.output_formatting import (
    format_error,
    format_stash_debt,
)
from teleclaude.core.next_machine.phase_derivation import derive_work_phase
from teleclaude.core.next_machine.slug_resolution import (
    _get_item_phase_db,
    resolve_canonical_project_root,
    resolve_slug_async,
    set_item_phase_db,
)
from teleclaude.core.next_machine.work_steps import _work_dispatch
from teleclaude.core.next_machine.worktrees import (
    ensure_worktree_with_policy_async,
)

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)

# Single-flight lock registry — one per (canonical_cwd, slug) pair.
# _SINGLE_FLIGHT_GUARD is the threading.Lock protecting mutations; defined in _types.
_SINGLE_FLIGHT_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


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


async def next_work(db: Db, slug: str | None, cwd: str) -> str:  # pylint: disable=too-many-locals,too-many-return-statements
    """Phase B state machine for deterministic builder work.

    Reads durable state from ``todos.db``, derives the current work phase via
    :func:`derive_work_phase`, executes the corresponding step via
    :func:`_work_dispatch`, and loops until a step returns an instruction or
    the loop limit is reached.

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

    # Merge origin/main into the worktree once before the loop so the phase
    # derivation sees a baseline consistent with integrated main.
    merge_started = perf_counter()
    head_before_merge = await asyncio.to_thread(get_head_commit, worktree_cwd)
    merge_err = await asyncio.to_thread(_merge_origin_main_into_worktree, worktree_cwd, resolved_slug)
    if merge_err:
        _log_next_work_phase(phase_slug, "merge_main", merge_started, "error", "merge_main_failed")
        return format_error("MERGE_MAIN_FAILED", merge_err)
    head_after_merge = await asyncio.to_thread(get_head_commit, worktree_cwd)
    _log_next_work_phase(phase_slug, "merge_main", merge_started, "run", "merge_main_applied")

    # Ensure item phase is IN_PROGRESS on first work entry.
    current_phase = await _get_item_phase_db(todos_db, resolved_slug)
    if current_phase == ItemPhase.PENDING.value:
        await set_item_phase_db(todos_db, resolved_slug, ItemPhase.IN_PROGRESS.value)

    # Dispatch loop — each iteration re-derives phase from primitives and dispatches.
    for _iter in range(_WORK_LOOP_LIMIT):
        state = await todos_db.read_state(resolved_slug)
        if state is None:
            return format_error(
                "NO_STATE",
                f"No state record for {resolved_slug}. Run telec todo prepare {resolved_slug} first.",
                next_call=f"telec todo prepare {resolved_slug}",
            )

        phase = derive_work_phase(state, worktree_cwd, resolved_slug)
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
            phase=phase,
            state=state,
            head_before_merge=head_before_merge,
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
    return "", (
        "NO_READY_ITEMS: No ready items found in roadmap.\n\n"
        "Execute:\n\n"
        "telec sessions end self\n\n"
        "The work queue is empty. Call telec todo prepare to prepare items first when new work arrives."
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
    derivation + step handlers in the work loop — not here.
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
    """Validate environmental preconditions only: stash debt."""
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


__all__ = ["next_work"]
