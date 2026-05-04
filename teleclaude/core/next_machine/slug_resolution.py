"""Slug resolution — find runnable slugs and manage item phase transitions.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.core.next_machine._types import ItemPhase
from teleclaude.core.next_machine.lifecycle import is_ready_for_work
from teleclaude.project_root import resolve_main_repo_root

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb
from teleclaude.core.next_machine.state_io import read_phase_state, write_phase_state
from teleclaude.core.todos_db import get_todos_db_sync


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


async def resolve_first_runnable_holder_child_db(
    todos_db: TodosDb,
    holder_slug: str,
    dependencies: dict[str, list[str]],
) -> tuple[str | None, str]:
    """Resolve first runnable child for a holder slug from DB."""
    children = await resolve_holder_children_db(todos_db, holder_slug)
    reason = "not_holder"
    if not children:
        return None, reason

    delivered = await todos_db.delivered_slugs()
    has_children_in_roadmap = False
    has_incomplete_children = False
    has_deps_blocked = False
    has_not_ready = False

    for child in children:
        if not await todos_db.slug_in_roadmap(child):
            continue

        has_children_in_roadmap = True
        phase = await _get_item_phase_db(todos_db, child, delivered)
        if phase == ItemPhase.DONE.value:
            continue

        has_incomplete_children = True
        is_ready = phase == ItemPhase.IN_PROGRESS.value or await _is_ready_for_work_db(todos_db, child)
        if not is_ready:
            has_not_ready = True
            continue

        child_deps = dependencies.get(child, [])
        if child_deps and not all(d in delivered for d in child_deps):
            has_deps_blocked = True
            continue

        return child, "ok"

    if has_children_in_roadmap:
        reason = "complete" if not has_incomplete_children else "item_not_ready"
        if has_deps_blocked:
            reason = "deps_unsatisfied"
        elif has_not_ready:
            reason = "item_not_ready"
    else:
        reason = "children_not_in_roadmap"
    return None, reason


def resolve_canonical_project_root(cwd: str) -> str:
    """Resolve canonical repository root from cwd.

    Accepts either the project root or a path inside a git worktree. Falls back
    to the provided cwd when git metadata is unavailable.
    """
    return str(resolve_main_repo_root(cwd))


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
    "_get_item_phase_db",
    "_is_ready_for_work_db",
    "get_item_phase",
    "resolve_canonical_project_root",
    "resolve_first_runnable_holder_child_db",
    "resolve_holder_children_db",
    "resolve_slug_async",
    "set_item_phase",
    "set_item_phase_db",
    "slug_in_roadmap",
]
