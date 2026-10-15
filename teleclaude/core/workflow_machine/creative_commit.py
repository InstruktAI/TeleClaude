"""The commits of the creative capabilities: the episode opens in the same row transaction as the write it belongs to."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.workflow_machine.creative import CreativeCapability, open_episode
from teleclaude.core.workflow_machine.effects import reconcile_slug_supervised
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.core.workflow_store.types import ConversionPath, ItemChange
from teleclaude.events.envelope import occurrence_id
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY
from teleclaude.types.todos import ACTIVE_RUNNER_STATE_KEY, TodoState
from teleclaude.types.workflow_record import ActStatus, EffectKind, PendingEffect

HANDOFF_ACT: Final = "creative-handoff"
EFFECT_SWEEP: Final = "sweep-helpers"
EFFECT_RELEASE: Final = "release"
EFFECT_DISPATCH: Final = "creative-dispatch"
INSTRUCTION_PARAM: Final = "instruction"
PHASE_PARAM: Final = "creative_phase"
EFFECT_ID_TEMPLATE: Final = "{key}:{name}"
SESSION_PARAM: Final = "session_id"
WORKFLOW_PROJECT: Final = "workflow"


def _closing_state(
    item: str, state: dict[str, StateValue], holder: str, instruction: str, creative_phase: str
) -> dict[str, StateValue]:
    """The state with the claim marked closing and the sweep, the dispatch and the release recorded as pending effects.

    The dispatch is the durable intent: the instruction the creative lane gives is part of the commit, and the dispatch
    effect completes only after the sweep found nothing, with the release of the claim last.
    """
    record = TodoState.model_validate(state).workflow.model_copy(deep=True)
    if record.closing:
        return state
    key = occurrence_id(WORKFLOW_PROJECT, item, HANDOFF_ACT, str(record.claim_epoch))
    steps = (
        (EFFECT_SWEEP, EffectKind.SWEEP_HELPERS, {SESSION_PARAM: holder}),
        (
            EFFECT_DISPATCH,
            EffectKind.CREATIVE_DISPATCH,
            {SESSION_PARAM: holder, INSTRUCTION_PARAM: instruction, PHASE_PARAM: creative_phase},
        ),
        (EFFECT_RELEASE, EffectKind.RELEASE_CLAIM, {SESSION_PARAM: holder}),
    )
    for name, kind, params in steps:
        record.pending_effects.append(
            PendingEffect(id=EFFECT_ID_TEMPLATE.format(key=key, name=name), act_key=key, kind=kind, params=params)
        )
    record.act_status[key] = ActStatus.IN_PROGRESS
    record.closing = True
    closed = dict(state)
    closed[WORKFLOW_STATE_KEY] = record.to_state()
    return closed


def episode_mutation(
    item: str,
    capability: CreativeCapability,
    caller_session_id: str,
    apply: Callable[[dict[str, StateValue]], dict[str, StateValue]] | None = None,
    *,
    dispatch: tuple[str, str] | None = None,
) -> Callable[[dict[str, StateValue] | None], ItemChange | None]:
    """The change that decides the capability against the row it reads, opens the episode and applies the write's state.

    ``apply`` carries the stamp's own state change onto the opened state. A refusal raises before anything is written;
    None means the capability changes no state.
    """

    def mutate(current: dict[str, StateValue] | None) -> ItemChange | None:
        opening = open_episode(item, current, capability=capability, caller_session_id=caller_session_id)
        state = apply(opening.state) if apply is not None else opening.state
        if dispatch is not None and caller_session_id and state.get(ACTIVE_RUNNER_STATE_KEY) == caller_session_id:
            state = _closing_state(item, state, caller_session_id, *dispatch)
        if state is current:
            return None
        return ItemChange(
            state=state, converted_from=opening.converted_from, conversion_path=ConversionPath.CAPABILITY.value
        )

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


async def hand_off_to_creative(
    store: WorkflowStore, item: str, holder: str, instruction: str, creative_phase: str
) -> str | None:
    """The holder's creative handoff: one commit, then the sweep, the dispatch and the release in that order.

    The commit opens the episode, converts a legacy phase, records the dispatch as a durable intent and marks the claim
    closing. The instruction returned is the dispatch's committed outcome, read from the item; None while an effect
    cannot finish yet, and repeating the call after the sweep has settled completes the same handoff.
    """
    mutate = episode_mutation(item, CreativeCapability.DESIGN, holder, dispatch=(instruction, creative_phase))
    await store.commit_item_change(
        item, expect_digests={}, mutate=lambda current, _digests: mutate(current), updated_by=holder
    )
    await reconcile_slug_supervised(str(store.project_root), item)
    raw = await store.read_state(item)
    if raw is None:
        return None
    state = TodoState.model_validate(raw)
    owed = {EffectKind.SWEEP_HELPERS, EffectKind.CREATIVE_DISPATCH, EffectKind.RELEASE_CLAIM}
    finished = state.active_runner != holder and not any(
        effect.kind in owed for effect in state.workflow.pending_effects
    )
    if not finished or not state.workflow.dispatched:
        return None
    return list(state.workflow.dispatched.values())[-1]
