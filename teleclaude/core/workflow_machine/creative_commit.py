"""The commits of the creative capabilities: the episode opens in the same row transaction as the write it belongs to."""

from __future__ import annotations

from collections.abc import Callable

from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.workflow_machine.creative import CreativeCapability, open_episode
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.core.workflow_store.types import ItemChange


def episode_mutation(
    item: str,
    capability: CreativeCapability,
    caller_session_id: str,
    apply: Callable[[dict[str, StateValue]], dict[str, StateValue]] | None = None,
) -> Callable[[dict[str, StateValue] | None], ItemChange | None]:
    """The change that decides the capability against the row it reads, opens the episode and applies the write's state.

    ``apply`` carries the stamp's own state change onto the opened state. A refusal raises before anything is written;
    None means the capability changes no state.
    """

    def mutate(current: dict[str, StateValue] | None) -> ItemChange | None:
        opening = open_episode(item, current, capability=capability, caller_session_id=caller_session_id)
        state = apply(opening.state) if apply is not None else opening.state
        if state is current:
            return None
        return ItemChange(state=state)

    return mutate


async def open_creative_episode(
    store: WorkflowStore, item: str, capability: CreativeCapability, caller_session_id: str
) -> None:
    """Open the item's creative episode for a capability that has no artifact or stamp of its own."""
    mutate = episode_mutation(item, capability, caller_session_id)

    await store.commit_item_change(
        item,
        expect_digests={},
        mutate=lambda current, _digests: mutate(current),
        updated_by=caller_session_id or None,
    )
