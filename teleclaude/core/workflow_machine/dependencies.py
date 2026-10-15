"""The dependency gates of the entry verbs.

The gates are the dependency graph's own (``local/projects/teleclaude/spec/feature/workflow/dependency-graph``):
a parent that has been prepared clears the preparation of its dependents, and a parent has to be delivered to
clear their work; a task parent has to be delivered for both, and a holder counts through its children. The
item lifecycle's phases are read through the one phase reader.
"""

from __future__ import annotations

from teleclaude.core.next_machine.kinds import KIND_TASK
from teleclaude.core.next_machine.slug_resolution import (
    effective_delivered_slugs_for_dependencies,
    effective_prepared_slugs_for_dependencies,
)
from teleclaude.core.workflow_machine.phase_reading import read_phase
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import Phase

PREPARED_PARENT_PHASES: frozenset[Phase] = frozenset({Phase.PREPARED, Phase.WORK, Phase.READY, Phase.DELIVERED})


async def _prepared_in_the_lifecycle(store: WorkflowStore, delivered: set[str]) -> set[str]:
    """The delivered slugs plus every non-task item the lifecycle reads as prepared or beyond."""
    prepared = set(delivered)
    for entry in await store.list_todo(include_delivered=True, include_holders=True):
        slug = entry["slug"]
        raw = await store.read_state(slug)
        if slug in prepared or raw is None:
            continue
        state = TodoState.model_validate(raw)
        if state.kind == KIND_TASK:
            continue
        if read_phase(state, integration_head="", creative_incomplete=False).phase in PREPARED_PARENT_PHASES:
            prepared.add(slug)
    return prepared


async def unmet_for_preparation(store: WorkflowStore, item: str) -> list[str]:
    """The dependencies of the item that have not been prepared."""
    delivered = await effective_delivered_slugs_for_dependencies(store)
    prepared = await effective_prepared_slugs_for_dependencies(
        store, await _prepared_in_the_lifecycle(store, delivered)
    )
    return [dep for dep in (await store.load_deps()).get(item, []) if dep not in prepared]


async def unmet_for_work(store: WorkflowStore, item: str) -> list[str]:
    """The dependencies of the item that have not been delivered."""
    delivered = await effective_delivered_slugs_for_dependencies(store)
    return [dep for dep in (await store.load_deps()).get(item, []) if dep not in delivered]
