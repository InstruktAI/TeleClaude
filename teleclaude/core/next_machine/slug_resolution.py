"""Slug resolution — find runnable slugs and manage item phase transitions.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from teleclaude.core.next_machine._types import ItemPhase, StateValue
from teleclaude.core.next_machine.kinds import KIND_FEATURE, KIND_TASK
from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    coerce_lifecycle_phase,
    is_ready_for_work,
    is_work_lifecycle_phase,
    lifecycle_phase_index,
)

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb
from teleclaude.core.next_machine.state_io import read_phase_state, write_phase_state
from teleclaude.core.todos_db import get_todos_db_sync
from teleclaude.core.todos_db._rows import TodoRow


class HolderResolutionMode(StrEnum):
    """Valid holder child resolution modes."""

    PREPARE = "prepare"
    WORK = "work"


class HolderResolutionReason(StrEnum):
    """Reason codes for holder child resolution outcomes."""

    NOT_HOLDER = "not_holder"
    OK = "ok"
    CHILDREN_NOT_IN_TODO = "children_not_in_todo"
    COMPLETE = "complete"
    DEPS_UNSATISFIED = "deps_unsatisfied"
    ALL_PREPARED = "all_prepared"
    ITEM_NOT_READY = "item_not_ready"


@dataclass(frozen=True)
class HolderChildResolution:
    """Resolved direct children for a holder and the runnable subset."""

    children: tuple[str, ...]
    runnable: tuple[str, ...]
    reason: HolderResolutionReason


async def resolve_slug_async(
    todos_db: TodosDb,
    slug: str | None,
    ready_only: bool = False,
    dependencies: dict[str, list[str]] | None = None,
) -> tuple[str | None, bool, str]:
    """Resolve slug from argument or todo list using todos.db.

    Args:
        todos_db: Database instance for state and todo list queries.
        slug: Optional explicit slug.
        ready_only: If True, only match items with current == 'prepared' (for next_work).
        dependencies: Optional dependency graph for dependency gating.

    Returns:
        Tuple of (slug, is_ready_or_in_progress, description).
    """
    if slug:
        return slug, True, ""

    entries = await todos_db.list_todo()
    delivered = await todos_db.delivered_slugs()
    dependency_delivered = (
        await effective_delivered_slugs_for_dependencies(todos_db, delivered) if dependencies is not None else delivered
    )

    for entry in entries:
        found_slug = entry["slug"]
        phase = await _get_item_phase_db(todos_db, found_slug, delivered)

        if phase == ItemPhase.DONE.value:
            continue

        is_ready = phase == ItemPhase.IN_PROGRESS.value or await _is_ready_for_work_db(todos_db, found_slug)

        if ready_only and not is_ready:
            continue

        if ready_only and dependencies is not None:
            slug_deps = dependencies.get(found_slug, [])
            if slug_deps and not all(d in dependency_delivered for d in slug_deps):
                continue

        return found_slug, is_ready, entry.get("description") or ""

    return None, False, ""


async def _get_item_phase_db(
    todos_db: TodosDb,
    slug: str,
    delivered: set[str] | None = None,
) -> str:
    """Get current phase for a work item from todos.db."""
    if delivered is None:
        delivered = await todos_db.delivered_slugs()
    is_delivered = slug in delivered
    is_in_todo = await todos_db.slug_in_todo(slug)

    if is_delivered and is_in_todo:
        msg = (
            f"Slug '{slug}' found in both delivered and the active todo list. "
            f"This is a data integrity issue — escalate to the user to resolve."
        )
        raise ValueError(msg)
    if is_delivered:
        return ItemPhase.DONE.value

    state = await todos_db.read_state(slug)
    if state is not None:
        phase = state.get("phase")
        if isinstance(phase, str):
            return phase

    if is_in_todo:
        return ItemPhase.PENDING.value

    msg = f"Slug '{slug}' has no state in DB, is not delivered, and is not in the todo list. Cannot determine phase."
    raise ValueError(msg)


async def _is_ready_for_work_db(todos_db: TodosDb, slug: str) -> bool:
    """DB-backed wrapper around the canonical readiness gate."""
    state = await todos_db.read_state(slug)
    if state is None:
        return False
    kind_raw = state.get("kind")
    kind = kind_raw if isinstance(kind_raw, str) else KIND_FEATURE
    lifecycle_phase_raw = state.get("lifecycle_phase")
    lifecycle_phase = lifecycle_phase_raw if isinstance(lifecycle_phase_raw, str) else None
    ready, _ = is_ready_for_work(kind=kind, lifecycle_phase=lifecycle_phase)
    return ready


def deps_satisfied(dependencies: dict[str, list[str]], satisfied_set: set[str], slug: str) -> bool:
    """Return whether all todo dependencies for ``slug`` are in ``satisfied_set``."""
    slug_deps = dependencies.get(slug, [])
    return not slug_deps or all(dep in satisfied_set for dep in slug_deps)


def _children_by_group(entries: list[TodoRow]) -> dict[str, list[str]]:
    """Index group_slug children from todo rows."""
    children: dict[str, list[str]] = {}
    for entry in entries:
        group_slug = entry.get("group_slug")
        if group_slug:
            children.setdefault(group_slug, []).append(entry["slug"])
    for grouped in children.values():
        grouped.sort()
    return children


async def _resolve_holder_children_from_entries(
    _todos_db: TodosDb,
    holder_slug: str,
    grouped_children: dict[str, list[str]],
) -> list[str]:
    """Resolve holder children from preloaded todo grouping rows."""
    return list(grouped_children.get(holder_slug, []))


async def effective_delivered_slugs_for_dependencies(
    todos_db: TodosDb,
    delivered: set[str] | None = None,
) -> set[str]:
    """Return raw delivered slugs plus holders whose children are all delivered.

    Holder rows do not carry their own lifecycle status. For dependency gating,
    a holder dependency is satisfied when every direct child has delivered; this
    mirrors the todo list projection without mutating the holder row itself.
    """
    effective = set(delivered if delivered is not None else await todos_db.delivered_slugs())
    entries = await todos_db.list_todo(include_delivered=True)
    grouped_children = _children_by_group(entries)
    candidates = {entry["slug"] for entry in entries}

    changed = True
    while changed:
        changed = False
        for slug in candidates - effective:
            children = await _resolve_holder_children_from_entries(todos_db, slug, grouped_children)
            if children and all(child in effective for child in children):
                effective.add(slug)
                changed = True

    return effective


def _state_counts_as_dependency_prepared(state: dict[str, StateValue] | None) -> bool:
    """Return True when a todo has crossed the prepare dependency gate."""
    if state is None:
        return False
    if state.get("kind") == KIND_TASK:
        # A task's deliverable is a run product: its PREPARED phase records only
        # that the task-plan is drafted, not that anything was produced. A task
        # dependency is satisfied solely through the delivered set, never here.
        return False
    approvals = state.get("approvals")
    if isinstance(approvals, dict):
        prd_approval = approvals.get("prd_approved")
        if isinstance(prd_approval, dict) and prd_approval.get("approved") is True:
            return True
    phase = coerce_lifecycle_phase(state.get("lifecycle_phase"))
    return phase == LifecyclePhase.PREPARED or (phase is not None and is_work_lifecycle_phase(phase))


async def effective_prepared_slugs_for_dependencies(
    todos_db: TodosDb,
    delivered: set[str] | None = None,
) -> set[str]:
    """Return delivered/prepared slugs plus holders whose children are all prepared."""
    effective = set(delivered if delivered is not None else await todos_db.delivered_slugs())
    entries = await todos_db.list_todo(include_delivered=True)
    for entry in entries:
        slug = entry["slug"]
        if slug in effective:
            continue
        if _state_counts_as_dependency_prepared(await todos_db.read_state(slug)):
            effective.add(slug)

    grouped_children = _children_by_group(entries)
    candidates = {entry["slug"] for entry in entries}

    changed = True
    while changed:
        changed = False
        for slug in candidates - effective:
            children = await _resolve_holder_children_from_entries(todos_db, slug, grouped_children)
            if children and all(child in effective for child in children):
                effective.add(slug)
                changed = True

    return effective


def _is_prepare_runnable_lifecycle(state: dict[str, StateValue] | None) -> bool:
    """Return True when a child still needs prepare and can be targeted by prepare."""
    if state is None:
        return False
    phase = coerce_lifecycle_phase(state.get("lifecycle_phase"))
    if phase is None:
        return False
    return lifecycle_phase_index(phase) < lifecycle_phase_index(LifecyclePhase.PREPARED)


async def set_item_phase_db(todos_db: TodosDb, slug: str, phase: str) -> None:
    """Set phase for a work item in todos.db."""
    state = await todos_db.read_state(slug)
    if state is None:
        state = {}
    state["phase"] = phase
    await todos_db.write_state(slug, state)


async def resolve_holder_children_db(todos_db: TodosDb, holder_slug: str) -> list[str]:
    """Resolve container/holder child slugs from DB todo grouping."""
    entries = await todos_db.list_todo(include_delivered=True)
    return await _resolve_holder_children_from_entries(todos_db, holder_slug, _children_by_group(entries))


async def resolve_runnable_holder_children_db(
    todos_db: TodosDb,
    holder_slug: str,
    dependencies: dict[str, list[str]],
    *,
    mode: HolderResolutionMode,
) -> HolderChildResolution:
    """Resolve runnable direct children for a holder in prepare or work mode."""
    children = await resolve_holder_children_db(todos_db, holder_slug)
    if not children:
        return HolderChildResolution(children=(), runnable=(), reason=HolderResolutionReason.NOT_HOLDER)

    entries = await todos_db.list_todo()
    active_slugs = {entry["slug"] for entry in entries}
    delivered = await todos_db.delivered_slugs()
    dependency_satisfied = (
        await effective_prepared_slugs_for_dependencies(todos_db, delivered)
        if mode is HolderResolutionMode.PREPARE
        else await effective_delivered_slugs_for_dependencies(todos_db, delivered)
    )
    runnable: list[str] = []
    has_children_in_todo = False
    has_incomplete_children = False
    has_deps_blocked = False
    has_not_ready = False

    for child in children:
        if child in delivered:
            has_children_in_todo = True
            continue
        if child not in active_slugs:
            continue

        has_children_in_todo = True
        phase = await _get_item_phase_db(todos_db, child, delivered)
        if phase == ItemPhase.DONE.value:
            continue

        has_incomplete_children = True
        if mode is HolderResolutionMode.PREPARE:
            state = await todos_db.read_state(child)
            if not _is_prepare_runnable_lifecycle(state):
                has_not_ready = True
                continue
        else:
            is_ready = phase == ItemPhase.IN_PROGRESS.value or await _is_ready_for_work_db(todos_db, child)
            if not is_ready:
                has_not_ready = True
                continue

        if not deps_satisfied(dependencies, dependency_satisfied, child):
            has_deps_blocked = True
            continue

        runnable.append(child)

    if runnable:
        return HolderChildResolution(
            children=tuple(children), runnable=tuple(runnable), reason=HolderResolutionReason.OK
        )
    if not has_children_in_todo:
        return HolderChildResolution(
            children=tuple(children), runnable=(), reason=HolderResolutionReason.CHILDREN_NOT_IN_TODO
        )
    if not has_incomplete_children:
        return HolderChildResolution(children=tuple(children), runnable=(), reason=HolderResolutionReason.COMPLETE)
    if has_deps_blocked:
        return HolderChildResolution(
            children=tuple(children), runnable=(), reason=HolderResolutionReason.DEPS_UNSATISFIED
        )
    if mode is HolderResolutionMode.PREPARE and has_not_ready:
        return HolderChildResolution(children=tuple(children), runnable=(), reason=HolderResolutionReason.ALL_PREPARED)
    return HolderChildResolution(children=tuple(children), runnable=(), reason=HolderResolutionReason.ITEM_NOT_READY)


# ── Legacy sync functions (retained for callers not yet migrated) ────────


def get_item_phase(cwd: str, slug: str) -> str:
    """Sync legacy: resolve item phase using todos.db-backed state."""
    todos_db = get_todos_db_sync(cwd)
    delivered = todos_db.delivered_slugs_sync()
    is_delivered = slug in delivered
    is_in_todo = todos_db.resolve_id_sync(slug) is not None

    if is_delivered and is_in_todo:
        msg = (
            f"Slug '{slug}' found in both delivered and the active todo list. "
            f"This is a data integrity issue — escalate to the user to resolve."
        )
        raise ValueError(msg)
    if is_delivered:
        return ItemPhase.DONE.value

    state = todos_db.read_state_sync(slug)
    if state is not None:
        phase = state.get("phase")
        if isinstance(phase, str) and phase:
            return phase

    if is_in_todo:
        return ItemPhase.PENDING.value

    msg = f"Slug '{slug}' has no state in DB, is not delivered, and is not in the todo list. Cannot determine phase."
    raise ValueError(msg)


async def slug_in_todo(todos_db: TodosDb, slug: str) -> bool:
    """Compatibility shim for callers/tests that still patch module-level todo checks."""
    return await todos_db.slug_in_todo(slug)


def set_item_phase(cwd: str, slug: str, phase: str) -> None:
    """Sync legacy: set item phase on filesystem. Use set_item_phase_db for new code."""
    state = read_phase_state(cwd, slug)
    state["phase"] = phase
    write_phase_state(cwd, slug, state)


__all__ = [
    "HolderChildResolution",
    "HolderResolutionMode",
    "HolderResolutionReason",
    "_get_item_phase_db",
    "_is_ready_for_work_db",
    "deps_satisfied",
    "effective_delivered_slugs_for_dependencies",
    "effective_prepared_slugs_for_dependencies",
    "get_item_phase",
    "resolve_holder_children_db",
    "resolve_runnable_holder_children_db",
    "resolve_slug_async",
    "set_item_phase",
    "set_item_phase_db",
    "slug_in_todo",
]
