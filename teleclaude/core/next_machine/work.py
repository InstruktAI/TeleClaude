"""Work entry responses outside the item machine: explicit slugs and structural holders."""

from __future__ import annotations

import asyncio
from time import perf_counter

from instrukt_ai_logging import get_logger

from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import NEXT_WORK_PHASE_LOG, ItemPhase
from teleclaude.core.next_machine.output_formatting import (
    MISSING_ACTIVE_TODO_MESSAGE_TEMPLATE,
    TERMINAL_DEPARTURE_DIRECTIVE,
    format_error,
)
from teleclaude.core.next_machine.slug_resolution import (
    HolderResolutionMode,
    HolderResolutionReason,
    _get_item_phase_db,
    effective_delivered_slugs_for_dependencies,
    resolve_runnable_holder_children_db,
)
from teleclaude.core.operation_progress import emit_operation_progress
from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store

_NO_CURRENT_WORK_SCRIPT = (
    "NO_CURRENT_WORK_SLUG: Work orchestrator sessions are scoped to a single slug.\n\n"
    "Execute:\n\n"
    "telec sessions end\n\n"
    f"{TERMINAL_DEPARTURE_DIRECTIVE}\n\n"
    "No work-stage action is required. Daemon-runner pickup owns selecting future work."
)


logger = get_logger(__name__)
_TASK_WORK_ERROR_CODE = "NOT_PREPARED"
_TASK_WORK_MESSAGE_TEMPLATE = "Todo '{slug}' is in the task lane; use its task-runner session."
_AUTO_SLUG = "<auto>"


async def next_work(db: Db, slug: str | None, cwd: str) -> str:
    """Answer structural and no-item requests; ordinary items use the workflow entry verb."""
    _ = db
    cwd = await _normalize_next_work_cwd(cwd)
    todos_db = await get_workflow_store(cwd)
    resolved_slug, error = await _resolve_work_slug(todos_db, slug, slug or _AUTO_SLUG)
    if error is not None:
        return error
    return format_error(_TASK_WORK_ERROR_CODE, _TASK_WORK_MESSAGE_TEMPLATE.format(slug=resolved_slug))


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


async def _normalize_next_work_cwd(cwd: str) -> str:
    """Normalize the requested cwd to the canonical project root."""
    canonical_cwd = str(await asyncio.to_thread(resolve_project_root, cwd))
    if canonical_cwd != cwd:
        logger.debug(
            "next_work normalized cwd to canonical project root", requested_cwd=cwd, canonical_cwd=canonical_cwd
        )
    return canonical_cwd


async def _resolve_work_slug(todos_db: WorkflowStore, slug: str | None, phase_slug: str) -> tuple[str, str | None]:
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
    todos_db: WorkflowStore,
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
    is_holder_slug = not is_bug and await todos_db.is_structural_group_holder(slug)
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
    todos_db: WorkflowStore,
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
    todos_db: WorkflowStore,
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
