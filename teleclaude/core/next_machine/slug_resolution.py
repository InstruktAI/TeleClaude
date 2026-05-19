"""Slug resolution — find runnable slugs and manage item phase transitions.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from teleclaude.core.next_machine._types import ItemPhase, StateValue
from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    coerce_lifecycle_phase,
    is_ready_for_work,
    lifecycle_phase_index,
)

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb
from teleclaude.core.next_machine.state_io import read_phase_state, write_phase_state
from teleclaude.core.todos_db import get_todos_db_sync


@dataclass(frozen=True)
class HolderChildResolution:
    """Resolved direct children for a holder and the runnable subset."""

    children: tuple[str, ...]
    runnable: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class WorkQueueResolution:
    """Resolved work queue target for no-slug work pickup."""

    slug: str | None
    holder_slug: str | None = None
    child_slugs: tuple[str, ...] = ()
    reason: str = ""


async def resolve_slug_async(
    todos_db: TodosDb,
    slug: str | None,
    ready_only: bool = False,
    dependencies: dict[str, list[str]] | None = None,
) -> tuple[str | None, bool, str]:
    """Resolve slug from argument or roadmap using todos.db.

    Args:
        todos_db: Database instance for state and roadmap queries.
        slug: Optional explicit slug.
        ready_only: If True, only match items with current == 'prepared' (for next_work).
        dependencies: Optional dependency graph for dependency gating.

    Returns:
        Tuple of (slug, is_ready_or_in_progress, description).
    """
    if slug:
        return slug, True, ""

    entries = await todos_db.list_roadmap()
    delivered = await todos_db.delivered_slugs()

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
            if slug_deps and not all(d in delivered for d in slug_deps):
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
    is_in_roadmap = await todos_db.slug_in_roadmap(slug)

    if is_delivered and is_in_roadmap:
        msg = (
            f"Slug '{slug}' found in both delivered and active roadmap. "
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

    if is_in_roadmap:
        return ItemPhase.PENDING.value

    msg = f"Slug '{slug}' has no state in DB, is not delivered, and is not in roadmap. Cannot determine phase."
    raise ValueError(msg)


async def _is_ready_for_work_db(todos_db: TodosDb, slug: str) -> bool:
    """DB-backed wrapper around the canonical readiness gate."""
    state = await todos_db.read_state(slug)
    if state is None:
        return False
    kind_raw = state.get("kind")
    kind = kind_raw if isinstance(kind_raw, str) else "todo"
    lifecycle_phase_raw = state.get("lifecycle_phase")
    lifecycle_phase = lifecycle_phase_raw if isinstance(lifecycle_phase_raw, str) else None
    ready, _ = is_ready_for_work(kind=kind, lifecycle_phase=lifecycle_phase)
    return ready


def _deps_satisfied(dependencies: dict[str, list[str]], delivered: set[str], slug: str) -> bool:
    """Return whether all roadmap dependencies for ``slug`` have delivered."""
    slug_deps = dependencies.get(slug, [])
    return not slug_deps or all(dep in delivered for dep in slug_deps)


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
    """Resolve container/holder child slugs from DB roadmap and state."""
    entries = await todos_db.list_roadmap()
    grouped_children = [e["slug"] for e in entries if e.get("group_slug") == holder_slug]

    state = await todos_db.read_state(holder_slug)
    breakdown_children: list[str] = []
    if state:
        breakdown = state.get("breakdown")
        if isinstance(breakdown, dict):
            raw_children = breakdown.get("todos")
            if isinstance(raw_children, list):
                breakdown_children = [str(child) for child in raw_children if child]

    if not grouped_children and not breakdown_children:
        return []

    ordered = list(grouped_children)
    seen = set(ordered)
    for child in breakdown_children:
        if child not in seen:
            ordered.append(child)
            seen.add(child)
    return ordered


async def resolve_runnable_holder_children_db(
    todos_db: TodosDb,
    holder_slug: str,
    dependencies: dict[str, list[str]],
    *,
    mode: str,
) -> HolderChildResolution:
    """Resolve runnable direct children for a holder in prepare or work mode."""
    if mode not in {"prepare", "work"}:
        raise ValueError(f"unknown holder child resolution mode: {mode!r}")

    children = await resolve_holder_children_db(todos_db, holder_slug)
    if not children:
        return HolderChildResolution(children=(), runnable=(), reason="not_holder")

    entries = await todos_db.list_roadmap()
    active_slugs = {entry["slug"] for entry in entries}
    delivered = await todos_db.delivered_slugs()
    runnable: list[str] = []
    has_children_in_roadmap = False
    has_incomplete_children = False
    has_deps_blocked = False
    has_not_ready = False

    for child in children:
        if child in delivered:
            has_children_in_roadmap = True
            continue
        if child not in active_slugs:
            continue

        has_children_in_roadmap = True
        phase = await _get_item_phase_db(todos_db, child, delivered)
        if phase == ItemPhase.DONE.value:
            continue

        has_incomplete_children = True
        if mode == "prepare":
            state = await todos_db.read_state(child)
            if not _is_prepare_runnable_lifecycle(state):
                has_not_ready = True
                continue
        else:
            is_ready = phase == ItemPhase.IN_PROGRESS.value or await _is_ready_for_work_db(todos_db, child)
            if not is_ready:
                has_not_ready = True
                continue

        if not _deps_satisfied(dependencies, delivered, child):
            has_deps_blocked = True
            continue

        runnable.append(child)

    if runnable:
        return HolderChildResolution(children=tuple(children), runnable=tuple(runnable), reason="ok")
    if not has_children_in_roadmap:
        return HolderChildResolution(children=tuple(children), runnable=(), reason="children_not_in_roadmap")
    if not has_incomplete_children:
        return HolderChildResolution(children=tuple(children), runnable=(), reason="complete")
    if has_deps_blocked:
        return HolderChildResolution(children=tuple(children), runnable=(), reason="deps_unsatisfied")
    if mode == "prepare" and has_not_ready:
        return HolderChildResolution(children=tuple(children), runnable=(), reason="all_prepared")
    return HolderChildResolution(children=tuple(children), runnable=(), reason="item_not_ready")


async def resolve_first_runnable_holder_child_db(
    todos_db: TodosDb,
    holder_slug: str,
    dependencies: dict[str, list[str]],
) -> tuple[str | None, str]:
    """Resolve first runnable child for a holder slug from DB."""
    resolution = await resolve_runnable_holder_children_db(todos_db, holder_slug, dependencies, mode="work")
    if resolution.runnable:
        return resolution.runnable[0], "ok"
    return None, resolution.reason


async def resolve_next_work_queue_db(
    todos_db: TodosDb,
    dependencies: dict[str, list[str]],
) -> WorkQueueResolution:
    """Resolve the next runnable work item, skipping blocked holders."""
    entries = await todos_db.list_roadmap()
    delivered = await todos_db.delivered_slugs()
    saw_deps_blocked = False

    for entry in entries:
        found_slug = entry["slug"]
        holder_resolution = await resolve_runnable_holder_children_db(
            todos_db,
            found_slug,
            dependencies,
            mode="work",
        )
        if holder_resolution.children:
            if holder_resolution.runnable:
                return WorkQueueResolution(
                    slug=None,
                    holder_slug=found_slug,
                    child_slugs=holder_resolution.runnable,
                    reason="holder_children",
                )
            if holder_resolution.reason == "deps_unsatisfied":
                saw_deps_blocked = True
            continue

        phase = await _get_item_phase_db(todos_db, found_slug, delivered)
        if phase == ItemPhase.DONE.value:
            continue

        is_ready = phase == ItemPhase.IN_PROGRESS.value or await _is_ready_for_work_db(todos_db, found_slug)
        if not is_ready:
            continue

        if not _deps_satisfied(dependencies, delivered, found_slug):
            saw_deps_blocked = True
            continue

        return WorkQueueResolution(slug=found_slug, reason="ready")

    reason = "deps_unsatisfied" if saw_deps_blocked else "no_ready_items"
    return WorkQueueResolution(slug=None, reason=reason)


# ── Legacy sync functions (retained for callers not yet migrated) ────────


def get_item_phase(cwd: str, slug: str) -> str:
    """Sync legacy: resolve item phase using todos.db-backed state."""
    todos_db = get_todos_db_sync(cwd)
    delivered = todos_db.delivered_slugs_sync()
    is_delivered = slug in delivered
    is_in_roadmap = todos_db.resolve_id_sync(slug) is not None

    if is_delivered and is_in_roadmap:
        msg = (
            f"Slug '{slug}' found in both delivered and active roadmap. "
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

    if is_in_roadmap:
        return ItemPhase.PENDING.value

    msg = f"Slug '{slug}' has no state in DB, is not delivered, and is not in roadmap. Cannot determine phase."
    raise ValueError(msg)


async def slug_in_roadmap(todos_db: TodosDb, slug: str) -> bool:
    """Compatibility shim for callers/tests that still patch module-level roadmap checks."""
    return await todos_db.slug_in_roadmap(slug)


def set_item_phase(cwd: str, slug: str, phase: str) -> None:
    """Sync legacy: set item phase on filesystem. Use set_item_phase_db for new code."""
    state = read_phase_state(cwd, slug)
    state["phase"] = phase
    write_phase_state(cwd, slug, state)


__all__ = [
    "HolderChildResolution",
    "WorkQueueResolution",
    "_get_item_phase_db",
    "_is_ready_for_work_db",
    "get_item_phase",
    "resolve_first_runnable_holder_child_db",
    "resolve_holder_children_db",
    "resolve_next_work_queue_db",
    "resolve_runnable_holder_children_db",
    "resolve_slug_async",
    "set_item_phase",
    "set_item_phase_db",
    "slug_in_roadmap",
]
