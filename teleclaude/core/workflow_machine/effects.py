"""The effect reconciler: completes what an act committed and has not yet finished.

An act commits its pending effects with its state change (``commit_item_change``), and every write
that changes an item's claim holder commits a claim-changed effect (``with_claim_change``). Effects
run inline after the commit and are completed here at start, at every machine call and on the
periodic tick. Each effect has a stable id, so repeating one never raises a second notice.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.core.workflow_store.types import ItemChange
from teleclaude.events.catalog import PlatformEvent
from teleclaude.events.envelope import EventLevel, EventVisibility, occurrence_id
from teleclaude.events.envelope_facts import home_for_project_path
from teleclaude.events.producer import publish_event
from teleclaude.events.references import TodoRef
from teleclaude.events.schemas.sdlc import TodoClaimChanged, TodoClaimChangedData
from teleclaude.events.wire import LegacyFacts
from teleclaude.types.claim_change import HOLDER_PARAM, NO_HOLDER, PRIOR_HOLDER_PARAM, WORKFLOW_STATE_KEY
from teleclaude.types.state_value import StateValue
from teleclaude.types.workflow_record import EffectKind, EmittedEvent, PendingEffect, WorkflowRecord

logger = get_logger(__name__)

WORKFLOW_PRODUCER: Final = "workflow"
SDLC_DOMAIN: Final = "sdlc"
NONE_LABEL: Final = "none"
CLAIM_CHANGED_DESCRIPTION: Final = "Claim on {slug} moved from {prior} to {holder}"

EFFECT_FAILED_LOG: Final = "workflow effect failed; the reconciler retries it with the same identity"
RECONCILE_FAILED_LOG: Final = "workflow effect reconciliation failed for an item"
NO_HANDLER_LOG: Final = "workflow effect has no handler"


class EffectContext:
    """What an effect handler needs to act on one item."""

    def __init__(self, store: WorkflowStore, project_root: str, slug: str, item_id: str) -> None:
        self.store = store
        self.project_root = project_root
        self.slug = slug
        self.item_id = item_id


def _claim_changed(
    context: EffectContext, effect: PendingEffect
) -> tuple[PlatformEvent[TodoRef, TodoClaimChangedData], str]:
    prior = effect.params.get(PRIOR_HOLDER_PARAM, NO_HOLDER)
    holder = effect.params.get(HOLDER_PARAM, NO_HOLDER)
    event = TodoClaimChanged(
        id=occurrence_id(context.project_root, context.item_id, effect.id),
        subject=TodoRef(context.slug),
        home=home_for_project_path(context.project_root),
        data=TodoClaimChangedData(
            slug=context.slug,
            project_path=context.project_root,
            prior_holder=prior or None,
            holder=holder or None,
        ),
    )
    description = CLAIM_CHANGED_DESCRIPTION.format(
        slug=context.slug, prior=prior or NONE_LABEL, holder=holder or NONE_LABEL
    )
    return event, description


_EVENT_BUILDERS: Final[
    Mapping[
        EmittedEvent, Callable[[EffectContext, PendingEffect], tuple[PlatformEvent[TodoRef, TodoClaimChangedData], str]]
    ]
] = {
    EmittedEvent.CLAIM_CHANGED: _claim_changed,
}


async def _emit_event(context: EffectContext, effect: PendingEffect) -> None:
    if effect.event is None:
        raise ValueError(effect.id)
    event, description = _EVENT_BUILDERS[effect.event](context, effect)
    await publish_event(
        event,
        LegacyFacts(
            producer=WORKFLOW_PRODUCER,
            level=EventLevel.WORKFLOW,
            domain=SDLC_DOMAIN,
            visibility=EventVisibility.LOCAL,
            entity=context.slug,
            description=description,
        ),
    )


_HANDLERS: Final = {EffectKind.EMIT_EVENT: _emit_event}


def _without_effect(effect_id: str) -> Callable[[dict[str, StateValue] | None, Mapping[str, str]], ItemChange]:
    def mutate(state: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange:
        current = dict(state or {})
        raw = current.get(WORKFLOW_STATE_KEY)
        record = WorkflowRecord.model_validate(raw if isinstance(raw, dict) else {})
        remaining = [effect for effect in record.pending_effects if effect.id != effect_id]
        updated = record.model_copy(update={"pending_effects": remaining})
        current[WORKFLOW_STATE_KEY] = updated.model_dump(mode="json")
        return ItemChange(state=current)

    return mutate


async def reconcile_item(project_root: str, slug: str) -> None:
    """Run every pending effect of one item to completion, clearing each as it finishes."""
    store = await get_workflow_store(project_root)
    state = await store.read_state(slug)
    if state is None:
        return
    raw = state.get(WORKFLOW_STATE_KEY)
    record = WorkflowRecord.model_validate(raw if isinstance(raw, dict) else {})
    if not record.pending_effects:
        return
    item_id = store.resolve_store_address_sync(slug)
    if item_id is None:
        return
    context = EffectContext(store, project_root, slug, item_id)
    for effect in record.pending_effects:
        handler = _HANDLERS.get(effect.kind)
        if handler is None:
            logger.error(NO_HANDLER_LOG, slug=slug, effect=effect.id, kind=effect.kind.value)
            continue
        try:
            await handler(context, effect)
        except Exception:  # supervision boundary: one failed effect must not stop the item's others or the daemon
            logger.exception(EFFECT_FAILED_LOG, slug=slug, effect=effect.id, project_root=project_root)
            continue
        await store.commit_item_change(slug, expect_digests={}, mutate=_without_effect(effect.id), updated_by=None)


async def reconcile_project(project_root: str) -> None:
    """Complete the pending effects of every active item in a project."""
    store = await get_workflow_store(project_root)
    for item in await store.list_todo():
        await reconcile_supervised(project_root, item["slug"])


async def reconcile_supervised(project_root: str, slug: str) -> None:
    """Reconcile one item, containing and logging any failure with the item's context."""
    try:
        await reconcile_item(project_root, slug)
    except Exception:  # supervision boundary: a failing item must not stop the other items or the daemon
        logger.exception(RECONCILE_FAILED_LOG, slug=slug, project_root=project_root)
