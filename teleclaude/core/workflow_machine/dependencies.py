"""The dependency gates of the entry verbs.

The gates are the dependency graph's own (``local/projects/teleclaude/spec/feature/workflow/dependency-graph``):
a parent that has been prepared clears the preparation of its dependents, and a parent has to be delivered to
clear their work; a task parent has to be delivered for both, and a holder counts through its children. Each
parent's classification comes from the one phase reader: a stored value that the reader maps to preparation
does not clear a dependent's preparation.
"""

from __future__ import annotations

from teleclaude.core.next_machine.kinds import KIND_TASK
from teleclaude.core.next_machine.slug_resolution import effective_delivered_slugs_for_dependencies
from teleclaude.core.workflow_machine.phase_reading import read_phase
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.core.workflow_store.types import WorkItem
from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import Phase

PREPARED_PARENT_PHASES: frozenset[Phase] = frozenset({Phase.PREPARED, Phase.WORK, Phase.READY, Phase.DELIVERED})


def _children_by_holder(entries: list[WorkItem]) -> dict[str, list[str]]:
    slug_by_id = {entry["id"]: entry["slug"] for entry in entries}
    children: dict[str, list[str]] = {}
    for entry in entries:
        holder = slug_by_id.get(entry["group_id"]) if entry["group_id"] else None
        if holder:
            children.setdefault(holder, []).append(entry["slug"])
    return children


def _with_holder_rollup(satisfied: set[str], entries: list[WorkItem]) -> set[str]:
    """Add every holder whose direct children are all satisfied, until nothing more is added."""
    children = _children_by_holder(entries)
    rolled = set(satisfied)
    changed = True
    while changed:
        changed = False
        for holder, held in children.items():
            if holder not in rolled and all(child in rolled for child in held):
                rolled.add(holder)
                changed = True
    return rolled


async def _prepared_parents(store: WorkflowStore, delivered: set[str], entries: list[WorkItem]) -> set[str]:
    """The delivered slugs plus every non-task item the lifecycle reads as prepared or beyond, holders rolled up."""
    prepared = set(delivered)
    for entry in entries:
        slug = entry["slug"]
        raw = await store.read_state(slug)
        if slug in prepared or raw is None:
            continue
        state = TodoState.model_validate(raw)
        if state.kind == KIND_TASK:
            continue
        if read_phase(state, integration_head="", creative_incomplete=False).phase in PREPARED_PARENT_PHASES:
            prepared.add(slug)
    return _with_holder_rollup(prepared, entries)


async def unmet_for_preparation(store: WorkflowStore, item: str) -> list[str]:
    """The dependencies of the item that have not been prepared."""
    delivered = await effective_delivered_slugs_for_dependencies(store)
    entries = await store.list_todo(include_delivered=True, include_holders=True)
    prepared = await _prepared_parents(store, delivered, entries)
    return [dep for dep in (await store.load_deps()).get(item, []) if dep not in prepared]


async def unmet_for_work(store: WorkflowStore, item: str) -> list[str]:
    """The dependencies of the item that have not been delivered."""
    delivered = await effective_delivered_slugs_for_dependencies(store)
    return [dep for dep in (await store.load_deps()).get(item, []) if dep not in delivered]
