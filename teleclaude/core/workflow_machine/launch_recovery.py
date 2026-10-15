"""Recovery of a driver start that never reached a claim.

A launch reservation says a driver was requested for an item and has not claimed it. It is cleared when the
driver claims. When the start fails, or the driver ends without claiming, it would otherwise stand forever and
every later entry would wait for a driver that does not exist. It is released only on the platform's own
terminal evidence for exactly this request: the request event went out, every procedure activation it caused
has reached a terminal outcome, and no open session bound to this item for the procedure and home it concerned
is left that could still claim. A clock decides nothing here. A driver started for the released request is
refused at its claim, because a claim must present the reservation it was started for.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.core.db import db
from teleclaude.core.operations._kinds import OperationKind
from teleclaude.core.operations.service import TERMINAL_OPERATION_STATES
from teleclaude.core.procedure_routing import activation_request_id
from teleclaude.core.session_status import is_session_terminal
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.core.workflow_store.types import ItemChange
from teleclaude.docs_subscriptions import SubscriptionEntry, SubscriptionHomeKind, published_procedure_subscriptions
from teleclaude.events.envelope import EventHomeRef, occurrence_id
from teleclaude.events.envelope_facts import home_for_project_path
from teleclaude.events.references import TodoRef
from teleclaude.events.schemas.sdlc import TodoPreparationRequested, TodoWorkRequested
from teleclaude.types.activation_home import ActivationHome
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY, workflow_record_of
from teleclaude.types.procedure_delivery import BINDING_SECTION, BindingField
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import ACTIVE_RUNNER_STATE_KEY
from teleclaude.types.workflow_record import ActStatus, LaunchReservation, Phase

logger = get_logger(__name__)

RECOVERY_FAILED_LOG: Final = "launch recovery failed for an item"
RECOVERED_LOG: Final = "launch reservation released on terminal evidence"
RECOVERY_NOTE: Final = (
    "\n### {at} — platform · launch released\n\nThe driver start requested for {item} reached its end without a "
    "claim: every activation it caused is terminal and no session for it is open. The request was released.\n"
)
_WORK_PHASES: Final = frozenset({Phase.PREPARED, Phase.WORK})


def _request_event_type(phase: Phase) -> str:
    return TodoWorkRequested.type_name() if phase in _WORK_PHASES else TodoPreparationRequested.type_name()


def _event_home(project_root: str) -> ActivationHome | None:
    home = home_for_project_path(project_root)
    if isinstance(home, EventHomeRef):
        return ActivationHome(SubscriptionHomeKind(home.kind.value), home.instance)
    return None


async def _is_activation_terminal(request_id: str) -> bool:
    operation = await db.get_operation_by_request(
        kind=OperationKind.PROCEDURE_ACTIVATION.value, caller_session_id=None, client_request_id=request_id
    )
    return operation is not None and operation.state in TERMINAL_OPERATION_STATES


async def _has_open_bound_session(item: str, entry: SubscriptionEntry, home: ActivationHome) -> bool:
    """Whether an open session is bound to this item for exactly this procedure and home."""
    subject = TodoRef(item).to_ref().to_token()
    for session in await db.get_sessions_by_origin_metadata(BINDING_SECTION, BindingField.SUBJECT, subject):
        if is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
            continue
        binding = (session.origin_metadata or {}).get(BINDING_SECTION)
        if (
            isinstance(binding, dict)
            and binding.get(BindingField.PROCEDURE.value) == entry.procedure_id
            and binding.get(BindingField.HOME.value) == home.to_token()
        ):
            return True
    return False


async def has_terminal_evidence(project_root: str, item: str, item_id: str, launch: LaunchReservation) -> bool:
    """Whether the reservation's request can no longer produce a driver, by the platform's durable outcomes.

    Unknown is not terminal: an unreadable subscription set, an activation not yet recorded or one still
    queued or running all leave the reservation in place.
    """
    home = _event_home(project_root)
    if home is None:
        return False
    publication = await asyncio.to_thread(published_procedure_subscriptions)
    event_id = occurrence_id(project_root, item_id, launch.effect_id)
    matched = [
        entry
        for entry in publication.entries
        if entry.matches_type(_request_event_type(launch.phase)) and entry.reaches(home.kind, home.slug)
    ]
    for entry in matched:
        if not await _is_activation_terminal(activation_request_id(event_id, entry.procedure_id, home)):
            return False
    for entry in matched:
        if await _has_open_bound_session(item, entry, home):
            return False
    return True


def _release(item: str, key: str, now: datetime) -> Callable[..., ItemChange | None]:
    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None or current.get(ACTIVE_RUNNER_STATE_KEY):
            return None
        record = workflow_record_of(current)
        if record.launch is None or record.launch.key != key:
            return None
        if any(effect.act_key == key for effect in record.pending_effects):
            return None
        updated = record.model_copy(deep=True)
        updated.launch = None
        updated.act_status[key] = ActStatus.COMPLETE
        return ItemChange(
            state={**current, WORKFLOW_STATE_KEY: updated.to_state()},
            log_entry=RECOVERY_NOTE.format(at=now.isoformat(), item=item),
        )

    return mutate


async def _recover_item(store: WorkflowStore, project_root: str, item: str) -> None:
    raw = await store.read_state(item)
    if raw is None or raw.get(ACTIVE_RUNNER_STATE_KEY):
        return
    record = workflow_record_of(raw)
    launch = record.launch
    item_id = store.resolve_store_address_sync(item)
    if launch is None or item_id is None:
        return
    if any(effect.id == launch.effect_id for effect in record.pending_effects):
        return
    if not await has_terminal_evidence(project_root, item, item_id, launch):
        return
    await store.commit_item_change(
        item, expect_digests={}, mutate=_release(item, launch.key, datetime.now(UTC)), updated_by=None
    )
    logger.info(RECOVERED_LOG, slug=item, project_root=project_root, reservation=launch.key)


async def recover_stale_launches_supervised(project_root: str) -> None:
    """Release the launch reservations of a project that have terminal evidence; failures are contained per item."""
    try:
        store = await get_workflow_store(project_root)
        for entry in await store.list_todo():
            try:
                await _recover_item(store, project_root, entry["slug"])
            except Exception:  # supervision boundary: one unreadable item must not stop the others
                logger.exception(RECOVERY_FAILED_LOG, slug=entry["slug"], project_root=project_root)
    except Exception:  # supervision boundary: one broken project must not starve the others
        logger.exception(RECOVERY_FAILED_LOG, project_root=project_root)
