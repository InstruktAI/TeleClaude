"""The effect reconciler: completes what an act committed and has not yet finished.

An act commits its pending effects with its state change (``commit_item_change``), and every write
that changes an item's claim holder commits a claim-changed effect (``with_claim_change``). Effects
run inline after the commit and are completed here at start, at every machine call and on the
periodic tick. Items are addressed by their durable row id and recovered whatever their status, so
an iceboxed or delivered row finishes its effects too. Each effect has a stable id, so repeating one
never raises a second notice.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any, Final

from instrukt_ai_logging import get_logger

from teleclaude.constants import SYSTEM_DAEMON_PRINCIPAL
from teleclaude.core.command_dispatch import dispatch_command
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.next_machine.worktrees import ensure_worktree_with_policy_async
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.core.workflow_store.types import PendingEffectItem
from teleclaude.events.catalog import PlatformEvent
from teleclaude.events.envelope import EventLevel, EventVisibility, occurrence_id
from teleclaude.events.envelope_facts import home_for_project_path
from teleclaude.events.producer import publish_event
from teleclaude.events.references import TodoRef
from teleclaude.events.schemas.sdlc import (
    TodoClaimChanged,
    TodoClaimChangedData,
    TodoDriverRequestData,
    TodoHeadAdvanced,
    TodoHeadAdvancedData,
    TodoPreparationRequested,
    TodoReady,
    TodoReadyData,
    TodoWaiting,
    TodoWaitingData,
    TodoWorkRequested,
)
from teleclaude.events.wire import LegacyFacts
from teleclaude.types.claim_change import HOLDER_PARAM, NO_HOLDER, PRIOR_HOLDER_PARAM, workflow_record_of
from teleclaude.types.commands import CloseSessionCommand
from teleclaude.types.workflow_record import EffectKind, EmittedEvent, PendingEffect, WaitedPhase

logger = get_logger(__name__)

WORKFLOW_PRODUCER: Final = "workflow"
SDLC_DOMAIN: Final = "sdlc"
NONE_LABEL: Final = "none"
CLAIM_CHANGED_DESCRIPTION: Final = "Claim on {slug} moved from {prior} to {holder}"
WAITING_DESCRIPTION: Final = "{slug} waits on {person}"
READY_DESCRIPTION: Final = "{slug} is ready at {sha}"
HEAD_DESCRIPTION: Final = "{slug} advanced to {sha}"
BRANCH_PARAM: Final = "branch"
WAIT_PARAM: Final = "wait"
SHA_PARAM: Final = "sha"
READY_AT_PARAM: Final = "ready_at"
REQUEST_DESCRIPTION: Final = "A driver is requested for {slug}"
PERSON_PARAM: Final = "person"
WAITED_PHASE_PARAM: Final = "waited_phase"
RESERVATION_PARAM: Final = "reservation_key"
REQUESTED_BY_PARAM: Final = "requested_by"
SESSION_PARAM: Final = "session_id"

EFFECT_FAILED_LOG: Final = "workflow effect failed; the reconciler retries it with the same identity"
ITEM_FAILED_LOG: Final = "workflow effect reconciliation failed for an item"
PROJECT_FAILED_LOG: Final = "workflow effect reconciliation failed for a project"
NO_HANDLER_LOG: Final = "workflow effect has no handler"
NOT_FINISHED_LOG: Final = "workflow effect not finished yet; it stays pending and later effects of the item wait"
CLOSE_WAIT_SECONDS: Final = 10.0
CLOSE_POLL_SECONDS: Final = 0.25


class EffectNotFinished(Exception):
    """An effect has not reached its terminal outcome; it stays pending and is retried."""


class EffectContext:
    """What an effect handler needs to act on one item."""

    def __init__(self, store: WorkflowStore, project_root: str, item: PendingEffectItem) -> None:
        self.store = store
        self.project_root = project_root
        self.item = item


type BuiltEvent = tuple[PlatformEvent[Any, Any], str]


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


def _waiting(context: EffectContext, effect: PendingEffect) -> BuiltEvent:
    person = effect.params[PERSON_PARAM]
    event = TodoWaiting(
        id=occurrence_id(context.project_root, context.item.todo_id, effect.id),
        subject=TodoRef(context.item.slug),
        home=home_for_project_path(context.project_root),
        data=TodoWaitingData(
            slug=context.item.slug,
            project_path=context.project_root,
            person=person,
            waited_phase=WaitedPhase(effect.params[WAITED_PHASE_PARAM]),
            wait=effect.params[WAIT_PARAM],
        ),
    )
    return event, WAITING_DESCRIPTION.format(slug=context.item.slug, person=person)


def _head_advanced(context: EffectContext, effect: PendingEffect) -> BuiltEvent:
    event = TodoHeadAdvanced(
        id=occurrence_id(context.project_root, context.item.todo_id, effect.id),
        subject=TodoRef(context.item.slug),
        home=home_for_project_path(context.project_root),
        data=TodoHeadAdvancedData(
            slug=context.item.slug,
            project_path=context.project_root,
            branch=effect.params[BRANCH_PARAM],
            sha=effect.params[SHA_PARAM],
        ),
    )
    return event, HEAD_DESCRIPTION.format(slug=context.item.slug, sha=effect.params[SHA_PARAM])


def _ready(context: EffectContext, effect: PendingEffect) -> BuiltEvent:
    event = TodoReady(
        id=occurrence_id(context.project_root, context.item.todo_id, effect.id),
        subject=TodoRef(context.item.slug),
        home=home_for_project_path(context.project_root),
        data=TodoReadyData(
            slug=context.item.slug,
            project_path=context.project_root,
            branch=context.item.slug,
            sha=effect.params[SHA_PARAM],
            ready_at=effect.params[READY_AT_PARAM],
            driver_session_id=effect.params[SESSION_PARAM],
        ),
    )
    return event, READY_DESCRIPTION.format(slug=context.item.slug, sha=effect.params[SHA_PARAM])


def _build_request(
    event_type: type[PlatformEvent[TodoRef, TodoDriverRequestData]], context: EffectContext, effect: PendingEffect
) -> BuiltEvent:
    event = event_type(
        id=occurrence_id(context.project_root, context.item.todo_id, effect.id),
        subject=TodoRef(context.item.slug),
        home=home_for_project_path(context.project_root),
        data=TodoDriverRequestData(
            slug=context.item.slug,
            project_path=context.project_root,
            requested_by=effect.params.get(REQUESTED_BY_PARAM, NO_HOLDER),
            reservation_key=effect.params[RESERVATION_PARAM],
        ),
    )
    return event, REQUEST_DESCRIPTION.format(slug=context.item.slug)


def _preparation_requested(context: EffectContext, effect: PendingEffect) -> BuiltEvent:
    return _build_request(TodoPreparationRequested, context, effect)


def _work_requested(context: EffectContext, effect: PendingEffect) -> BuiltEvent:
    return _build_request(TodoWorkRequested, context, effect)


_EVENT_BUILDERS: Final[Mapping[EmittedEvent, Callable[[EffectContext, PendingEffect], BuiltEvent]]] = {
    EmittedEvent.CLAIM_CHANGED: _claim_changed,
    EmittedEvent.WAITING: _waiting,
    EmittedEvent.READY: _ready,
    EmittedEvent.HEAD_ADVANCED: _head_advanced,
    EmittedEvent.PREPARATION_REQUESTED: _preparation_requested,
    EmittedEvent.WORK_REQUESTED: _work_requested,
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


async def _release_claim(context: EffectContext, effect: PendingEffect) -> None:
    await context.store.release_claim_by_id(context.item.todo_id, effect.params[SESSION_PARAM])


async def _session_is_closed(session_id: str) -> bool:
    session = await db.get_session(session_id)
    return session is None or session.closed_at is not None


async def _await_closed(session_id: str) -> bool:
    """Wait, within a bound, for the session to reach its terminal state."""
    deadline = asyncio.get_running_loop().time() + CLOSE_WAIT_SECONDS
    while True:
        if await _session_is_closed(session_id):
            return True
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(CLOSE_POLL_SECONDS)


async def _end_session(context: EffectContext, effect: PendingEffect) -> None:
    """End the session and acknowledge only once the session lifecycle shows it closed.

    A close another path already has in flight returns without closing; the effect then stays pending and
    is retried until the terminal state is observed.
    """
    session_id = effect.params[SESSION_PARAM]
    if await _session_is_closed(session_id):
        return
    await dispatch_command(
        get_command_service().client, CloseSessionCommand(session_id=session_id), principal=SYSTEM_DAEMON_PRINCIPAL
    )
    if not await _await_closed(session_id):
        raise EffectNotFinished(effect.id)


async def _ensure_worktree(context: EffectContext, effect: PendingEffect) -> None:
    """Create the item's worktree and branch, deriving both names from the item identity; repeating it is safe."""
    await ensure_worktree_with_policy_async(context.project_root, context.item.slug)


_HANDLERS: Final = {
    EffectKind.ENSURE_WORKTREE: _ensure_worktree,
    EffectKind.EMIT_EVENT: _emit_event,
    EffectKind.RELEASE_CLAIM: _release_claim,
    EffectKind.END_SESSION: _end_session,
}


async def reconcile_item(
    store: WorkflowStore,
    project_root: str,
    item: PendingEffectItem,
    selected: Callable[[PendingEffect], bool] | None = None,
) -> None:
    """Run the pending effects of one item row to completion, clearing each as it finishes.

    All of them, in order, unless ``selected`` names the ones to run; the others are left exactly as they are.
    """
    state = await store.read_state_by_id(item.todo_id)
    if state is None:
        return
    context = EffectContext(store, project_root, item)
    for effect in workflow_record_of(state).pending_effects:
        if selected is not None and not selected(effect):
            continue
        handler = _HANDLERS.get(effect.kind)
        if handler is None:
            logger.error(NO_HANDLER_LOG, slug=item.slug, effect=effect.id, kind=effect.kind.value)
            continue
        try:
            await handler(context, effect)
        except EffectNotFinished:
            logger.info(NOT_FINISHED_LOG, slug=item.slug, effect=effect.id, project_root=project_root)
            break
        except Exception:  # supervision boundary: a failed effect must not stop the daemon; later effects wait for it
            logger.exception(EFFECT_FAILED_LOG, slug=item.slug, effect=effect.id, project_root=project_root)
            break
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


def _is_head_notice(effect: PendingEffect) -> bool:
    return effect.kind is EffectKind.EMIT_EVENT and effect.event is EmittedEvent.HEAD_ADVANCED


async def reconcile_head_notices_supervised(project_root: str, slug: str) -> None:
    """Send the pending head notices of an item and nothing else.

    A head notice is independent of the item's acts: an earlier act whose worktree or session effect is slow or
    failing neither delays it nor is run by it, and the acts' own effects keep their order and their release last.
    """
    try:
        store = await get_workflow_store(project_root)
        for item in await store.list_items_with_pending_effects():
            if item.slug == slug:
                try:
                    await reconcile_item(store, project_root, item, _is_head_notice)
                except Exception:  # supervision boundary: a failing notice must not stop the observation pass
                    logger.exception(ITEM_FAILED_LOG, slug=item.slug, item=item.todo_id, project_root=project_root)
    except Exception:  # supervision boundary: the reconciler consumer completes it on its next tick
        logger.exception(PROJECT_FAILED_LOG, project_root=project_root, slug=slug)


async def reconcile_slug_supervised(project_root: str, slug: str) -> None:
    """Reconcile the item a claim-change kick names, found by its slug among the rows with pending effects."""
    try:
        store = await get_workflow_store(project_root)
        for item in await store.list_items_with_pending_effects():
            if item.slug == slug:
                await reconcile_item_supervised(store, project_root, item)
    except Exception:  # supervision boundary: a failed kick is recovered by the next tick
        logger.exception(PROJECT_FAILED_LOG, project_root=project_root, slug=slug)
