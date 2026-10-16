"""Observing the integration head: publish intents, their completion and the periodic reading.

``local/projects/teleclaude/spec/feature/workflow/work-review-cycle`` is the contract. A notice names a
commit that was observed on the integration ref, never one inferred from a later state of it. The sealed
commit registers an intent before it pushes one explicit commit as a compare-and-swap update and completes
the intent with the push's own result; only a completed intent whose swap succeeded raises the notice for
its commit. The platform's own reading raises the notice for the commit the ref carries when it reads.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.core.roles import RoleName
from teleclaude.core.workflow_machine.caller import in_claiming_group, load_caller
from teleclaude.core.workflow_machine.effects import reconcile_head_notices_supervised
from teleclaude.core.workflow_machine.stamp import NO_HEAD, RemoteReadFailed, integration_head
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.core.workflow_store.types import ItemChange
from teleclaude.events.envelope import occurrence_id
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY, workflow_record_of
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import LIFECYCLE_PHASE_STATE_KEY, TodoState
from teleclaude.types.workflow_record import (
    EffectKind,
    EmittedEvent,
    ObservedHead,
    PendingEffect,
    PublishIntent,
    WorkflowRecord,
)

logger = get_logger(__name__)


class IntentRefusal(StrEnum):
    """Why a publish report is not accepted."""

    UNKNOWN_ITEM = "no item {item} in this project"
    NOT_WRITER = "{session} may not report a publish for {item}"
    UNKNOWN_INTENT = "{item} has no publish intent {key}"
    NOT_IN_WORK = "{item} is not in work"


class IntentRefused(Exception):
    """A publish report was not accepted; nothing was written."""


HEAD_EFFECT_ID_TEMPLATE: Final = "head:{sha}"
SHA_PARAM: Final = "sha"
BRANCH_PARAM: Final = "branch"
NO_ACT_KEY: Final = ""
DISCOVERY_FAILED_LOG: Final = "head discovery failed for an item"
DISCOVERY_PROJECT_FAILED_LOG: Final = "head discovery failed for a project"
DISCOVERY_ITEM_TIMEOUT_SECONDS: Final = 20
DISCOVERY_CONCURRENCY: Final = 8
PASS_SETUP_TIMEOUT_SECONDS: Final = 10
HEAD_READ_FAILED_LOG: Final = "integration head could not be read for a phase reading"
HEAD_COMPARED_PHASES: Final = frozenset(
    {LifecyclePhase.READY, LifecyclePhase.REVIEW_APPROVED, LifecyclePhase.FINALIZE_READY}
)


@dataclass(frozen=True)
class IntentRequest:
    """A session's report that it is about to push one explicit commit as a swap of the integration ref."""

    project_root: str
    item: str
    sha: str
    expected_tip: str
    caller_session_id: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _head_effect(sha: str, branch: str) -> PendingEffect:
    return PendingEffect(
        id=HEAD_EFFECT_ID_TEMPLATE.format(sha=sha),
        act_key=NO_ACT_KEY,
        kind=EffectKind.EMIT_EVENT,
        event=EmittedEvent.HEAD_ADVANCED,
        params={SHA_PARAM: sha, BRANCH_PARAM: branch},
    )


def _observe(record: WorkflowRecord, sha: str, branch: str) -> WorkflowRecord:
    """The record with the commit observed and its notice committed as an effect; unchanged when already observed."""
    if any(head.sha == sha for head in record.observed_heads):
        return record
    updated = record.model_copy(deep=True)
    updated.observed_heads.append(ObservedHead(branch=branch, sha=sha, at=_now()))
    updated.pending_effects.append(_head_effect(sha, branch))
    return updated


async def _may_report(store: WorkflowStore, request: IntentRequest, state: TodoState) -> bool:
    holder = state.active_runner or None
    if holder is None:
        return False
    caller = await load_caller(request.caller_session_id)
    if caller is None:
        return False
    return await in_claiming_group(caller.session_id, holder, state.workflow.remote_members) and (
        caller.session_id == holder or caller.role == RoleName.BUILDER
    )


@dataclass(frozen=True)
class HeadObservation:
    """What one read of the integration head found: the commit, empty when the ref is absent or the read failed.

    ``unreadable`` tells the two empty answers apart: an absent ref is a known state, a failed read is not.
    """

    head: str = NO_HEAD
    unreadable: bool = False


async def observed_head(project_root: str, item: str) -> HeadObservation:
    """The integration head for a phase reading, with the failure logged when it cannot be read."""
    try:
        return HeadObservation(head=await integration_head(project_root, item))
    except RemoteReadFailed:
        logger.exception(HEAD_READ_FAILED_LOG, slug=item, project_root=project_root)
        return HeadObservation(unreadable=True)


async def reading_head(project_root: str, item: str, state: TodoState) -> HeadObservation:
    """The integration head a phase reading needs: read only for the phases whose reading compares it."""
    if state.lifecycle_phase not in HEAD_COMPARED_PHASES:
        return HeadObservation()
    return await observed_head(project_root, item)


async def register_publish_intent(request: IntentRequest) -> str:
    """Record the intent to push one commit as a swap of the integration ref, and return its key."""
    store = await get_workflow_store(request.project_root)
    raw = await store.read_state(request.item)
    item_id = store.resolve_store_address_sync(request.item)
    if raw is None or item_id is None:
        raise IntentRefused(IntentRefusal.UNKNOWN_ITEM.value.format(item=request.item))
    state = TodoState.model_validate(raw)
    if not await _may_report(store, request, state):
        raise IntentRefused(IntentRefusal.NOT_WRITER.value.format(session=request.caller_session_id, item=request.item))
    key = occurrence_id(str(store.project_root), item_id, request.sha, request.expected_tip, _now())

    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None:
            raise IntentRefused(IntentRefusal.UNKNOWN_ITEM.value.format(item=request.item))
        record = workflow_record_of(current).model_copy(deep=True)
        record.publish_intents.append(
            PublishIntent(
                key=key,
                branch=request.item,
                sha=request.sha,
                expected_tip=request.expected_tip,
                session_id=request.caller_session_id,
            )
        )
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: record.to_state()})

    await store.commit_item_change(request.item, expect_digests={}, mutate=mutate, updated_by=request.caller_session_id)
    return key


async def complete_publish_intent(project_root: str, item: str, key: str, session_id: str, swapped: bool) -> None:
    """Complete an intent with the push's own result; a successful swap raises the notice for its commit."""
    store = await get_workflow_store(project_root)

    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None:
            raise IntentRefused(IntentRefusal.UNKNOWN_ITEM.value.format(item=item))
        record = workflow_record_of(current)
        intents = [intent for intent in record.publish_intents if intent.key == key and intent.session_id == session_id]
        if not intents:
            raise IntentRefused(IntentRefusal.UNKNOWN_INTENT.value.format(item=item, key=key))
        intent = intents[0]
        if intent.completed:
            return None
        updated = record.model_copy(deep=True)
        updated.publish_intents = [
            PublishIntent(
                key=candidate.key,
                branch=candidate.branch,
                sha=candidate.sha,
                expected_tip=candidate.expected_tip,
                session_id=candidate.session_id,
                completed=True,
                swapped=swapped,
            )
            if candidate.key == key
            else candidate
            for candidate in updated.publish_intents
        ]
        if swapped:
            updated = _observe(updated, intent.sha, intent.branch)
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: updated.to_state()})

    await store.commit_item_change(item, expect_digests={}, mutate=mutate, updated_by=session_id)
    await reconcile_head_notices_supervised(str(store.project_root), item)


async def discover_item_head(project_root: str, item: str) -> None:
    """Raise the notice for the commit the item's integration ref carries now, when none was raised for it."""
    store = await get_workflow_store(project_root)
    raw = await store.read_state(item)
    if raw is None or raw.get(LIFECYCLE_PHASE_STATE_KEY) != LifecyclePhase.WORK.value:
        return
    root = str(store.project_root)
    record = workflow_record_of(raw)
    if any(effect.event is EmittedEvent.HEAD_ADVANCED for effect in record.pending_effects):
        await reconcile_head_notices_supervised(root, item)
    tip = await integration_head(root, item)
    if not tip or any(head.sha == tip for head in record.observed_heads):
        return

    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None or current.get(LIFECYCLE_PHASE_STATE_KEY) != LifecyclePhase.WORK.value:
            return None
        record = workflow_record_of(current)
        updated = _observe(record, tip, item)
        if updated is record:
            return None
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: updated.to_state()})

    await store.commit_item_change(item, expect_digests={}, mutate=mutate, updated_by=None)
    await reconcile_head_notices_supervised(root, item)


async def _discover_bounded(project_root: str, item: str, gate: asyncio.Semaphore) -> None:
    """One item's discovery under the concurrency and time bounds, contained so no item stops the others."""
    async with gate:
        try:
            await asyncio.wait_for(discover_item_head(project_root, item), DISCOVERY_ITEM_TIMEOUT_SECONDS)
        except Exception:  # supervision boundary: one unreadable or slow item must not stop the others or the daemon
            logger.exception(DISCOVERY_FAILED_LOG, slug=item, project_root=project_root)


async def observe_item_supervised(project_root: str, item: str) -> None:
    """Read one item's integration head when a machine call touches it; a failure is logged and never fails the call."""
    try:
        await asyncio.wait_for(discover_item_head(project_root, item), DISCOVERY_ITEM_TIMEOUT_SECONDS)
    except Exception:  # supervision boundary: observation must never fail the call that triggered it
        logger.exception(DISCOVERY_FAILED_LOG, slug=item, project_root=project_root)


async def _items_in_work(store: WorkflowStore) -> list[str]:
    """The slugs of the project's items that are in work, read from local state; only these are read on the remote."""
    slugs: list[str] = []
    for entry in await store.list_todo():
        raw = await store.read_state(entry["slug"])
        if raw is not None and raw.get(LIFECYCLE_PHASE_STATE_KEY) == LifecyclePhase.WORK.value:
            slugs.append(entry["slug"])
    return slugs


async def _scheduled_items(project_root: str) -> list[str]:
    store = await get_workflow_store(project_root)
    return await _items_in_work(store)


async def discover_project_heads(project_root: str) -> None:
    """Read the integration head of every item in work, concurrently and each within its bound.

    Finding the items in work is local but not free; it has a bound of its own, outside the items' limits.
    """
    scheduled = await asyncio.wait_for(_scheduled_items(project_root), PASS_SETUP_TIMEOUT_SECONDS)
    gate = asyncio.Semaphore(DISCOVERY_CONCURRENCY)
    await asyncio.gather(*(_discover_bounded(project_root, slug, gate) for slug in scheduled))


async def discover_project_heads_supervised(project_root: str) -> None:
    """Discovery for one project, contained so a broken project stops neither the others nor its own reconciliation."""
    try:
        await discover_project_heads(project_root)
    except Exception:  # supervision boundary: one broken project must not starve the others
        logger.exception(DISCOVERY_PROJECT_FAILED_LOG, project_root=project_root)
