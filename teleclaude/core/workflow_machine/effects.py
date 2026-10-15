"""The effect reconciler: completes what an act committed and has not yet finished.

An act commits its pending effects with its state change (``commit_item_change``), and every write
that changes an item's claim holder commits a claim-changed effect (``with_claim_change``). Effects
run inline after the commit and are completed here at start, at every machine call and on the
periodic tick. Items are addressed by their durable row id and recovered whatever their status, so
an iceboxed or delivered row finishes its effects too. Each effect has a stable id, so repeating one
never raises a second notice.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.core.workflow_store.types import PendingEffectItem
from teleclaude.events.catalog import PlatformEvent
from teleclaude.events.envelope import EventLevel, EventVisibility, occurrence_id
from teleclaude.events.envelope_facts import home_for_project_path
from teleclaude.events.producer import publish_event
from teleclaude.events.references import TodoRef
from teleclaude.events.schemas.sdlc import TodoClaimChanged, TodoClaimChangedData
from teleclaude.events.wire import LegacyFacts
from teleclaude.types.claim_change import HOLDER_PARAM, NO_HOLDER, PRIOR_HOLDER_PARAM, workflow_record_of
from teleclaude.types.workflow_record import EffectKind, EmittedEvent, PendingEffect

logger = get_logger(__name__)

WORKFLOW_PRODUCER: Final = "workflow"
SDLC_DOMAIN: Final = "sdlc"
NONE_LABEL: Final = "none"
CLAIM_CHANGED_DESCRIPTION: Final = "Claim on {slug} moved from {prior} to {holder}"

EFFECT_FAILED_LOG: Final = "workflow effect failed; the reconciler retries it with the same identity"
ITEM_FAILED_LOG: Final = "workflow effect reconciliation failed for an item"
PROJECT_FAILED_LOG: Final = "workflow effect reconciliation failed for a project"
NO_HANDLER_LOG: Final = "workflow effect has no handler"


class EffectContext:
    """What an effect handler needs to act on one item."""

    def __init__(self, project_root: str, item: PendingEffectItem) -> None:
        self.project_root = project_root
        self.item = item


type BuiltEvent = tuple[PlatformEvent[TodoRef, TodoClaimChangedData], str]


def _claim_changed(context: EffectContext, effect: PendingEffect) -> BuiltEvent:
    prior = effect.params.get(PRIOR_HOLDER_PARAM, NO_HOLDER)
    holder = effect.params.get(HOLDER_PARAM, NO_HOLDER)
    event = TodoClaimChanged(
        id=occurrence_id(context.project_root, context.item.todo_id, effect.id),
        subject=TodoRef(context.item.slug),
        home=home_for_project_path(context.project_root),
        data=TodoClaimChangedData(
            slug=context.item.slug,
            project_path=context.project_root,
            prior_holder=prior or None,
            holder=holder or None,
        ),
    )
    description = CLAIM_CHANGED_DESCRIPTION.format(
        slug=context.item.slug, prior=prior or NONE_LABEL, holder=holder or NONE_LABEL
    )
    return event, description


_EVENT_BUILDERS: Final[Mapping[EmittedEvent, Callable[[EffectContext, PendingEffect], BuiltEvent]]] = {
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
            entity=context.item.slug,
            description=description,
        ),
    )


_HANDLERS: Final = {EffectKind.EMIT_EVENT: _emit_event}


async def reconcile_item(store: WorkflowStore, project_root: str, item: PendingEffectItem) -> None:
    """Run every pending effect of one item row to completion, clearing each as it finishes."""
    state = await store.read_state_by_id(item.todo_id)
    if state is None:
        return
    context = EffectContext(project_root, item)
    for effect in workflow_record_of(state).pending_effects:
        handler = _HANDLERS.get(effect.kind)
        if handler is None:
            logger.error(NO_HANDLER_LOG, slug=item.slug, effect=effect.id, kind=effect.kind.value)
            continue
        try:
            await handler(context, effect)
        except Exception:  # supervision boundary: one failed effect must not stop the item's others or the daemon
            logger.exception(EFFECT_FAILED_LOG, slug=item.slug, effect=effect.id, project_root=project_root)
            continue
        await store.clear_pending_effect(item.todo_id, effect.id)


async def reconcile_project(project_root: str) -> None:
    """Complete the pending effects of every item row in a project, whatever its status."""
    store = await get_workflow_store(project_root)
    for item in await store.list_items_with_pending_effects():
        await reconcile_item_supervised(store, project_root, item)


async def reconcile_item_supervised(store: WorkflowStore, project_root: str, item: PendingEffectItem) -> None:
    """Reconcile one item, containing and logging any failure with the item's context."""
    try:
        await reconcile_item(store, project_root, item)
    except Exception:  # supervision boundary: a failing item must not stop the other items or the daemon
        logger.exception(ITEM_FAILED_LOG, slug=item.slug, item=item.todo_id, project_root=project_root)


async def reconcile_project_supervised(project_root: str) -> None:
    """Reconcile one project, containing and logging a failure of the project itself."""
    try:
        await reconcile_project(project_root)
    except Exception:  # supervision boundary: an unavailable project must not starve the others
        logger.exception(PROJECT_FAILED_LOG, project_root=project_root)


async def reconcile_slug_supervised(project_root: str, slug: str) -> None:
    """Reconcile the item a claim-change kick names, found by its slug among the rows with pending effects."""
    try:
        store = await get_workflow_store(project_root)
        for item in await store.list_items_with_pending_effects():
            if item.slug == slug:
                await reconcile_item_supervised(store, project_root, item)
    except Exception:  # supervision boundary: a failed kick is recovered by the next tick
        logger.exception(PROJECT_FAILED_LOG, project_root=project_root, slug=slug)
