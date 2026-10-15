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

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Final

from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.core.db import db
from teleclaude.core.operations._kinds import OperationKind
from teleclaude.core.operations.service import TERMINAL_OPERATION_STATES
from teleclaude.core.procedure_routing import PROCEDURE_ACTIVATION_CONSUMER
from teleclaude.core.session_status import is_session_terminal
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.core.workflow_store.types import ItemChange
from teleclaude.events.db import get_event_db
from teleclaude.events.envelope import occurrence_id
from teleclaude.events.references import TodoRef
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY, workflow_record_of
from teleclaude.types.procedure_delivery import BINDING_SECTION, BindingField
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import ACTIVE_RUNNER_STATE_KEY
from teleclaude.types.workflow_record import ActStatus, LaunchRecipient, LaunchReservation

logger = get_logger(__name__)


class ActivateProcedureCommandPayload(BaseModel):
    """The two fields of a persisted procedure activation that name its recipient."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    procedure_id: str
    home: str


OBSERVATION_WINDOW_SECONDS: Final = 3 * 24 * 3600
RECIPIENTS_FIELD: Final = "recipients"
RECOVERY_FAILED_LOG: Final = "launch recovery failed for an item"
RECOVERED_LOG: Final = "launch reservation released on terminal evidence"
RECOVERY_NOTE: Final = (
    "\n### {at} — platform · launch released\n\nThe driver start requested for {item} reached its end without a "
    "claim: every activation it caused is terminal and no session for it is open. The request was released.\n"
)


async def _has_open_bound_session(item: str, procedure_id: str, home: str) -> bool:
    """Whether an open session is bound to this item for exactly this procedure and home."""
    subject = TodoRef(item).to_ref().to_token()
    for session in await db.get_sessions_by_origin_metadata(BINDING_SECTION, BindingField.SUBJECT, subject):
        if is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
            continue
        binding = (session.origin_metadata or {}).get(BINDING_SECTION)
        if (
            isinstance(binding, dict)
            and binding.get(BindingField.PROCEDURE.value) == procedure_id
            and binding.get(BindingField.HOME.value) == home
        ):
            return True
    return False


async def _observe_recipients(
    store: WorkflowStore, project_root: str, item: str, item_id: str, launch: LaunchReservation
) -> tuple[LaunchRecipient, ...] | None:
    """The activations the request caused, recorded on the reservation the first time they can be observed.

    Observation happens while the platform still holds the receipts, and is refused for a reservation older
    than the observation window, so a receipt that retention has already begun to delete can never be read as
    'nothing matched'. None means not observable yet or no longer reliably so.
    """
    if launch.recipients is not None:
        return launch.recipients
    age = (datetime.now(UTC) - datetime.fromisoformat(launch.requested_at)).total_seconds()
    if age >= OBSERVATION_WINDOW_SECONDS:
        return None
    event_id = occurrence_id(project_root, item_id, launch.effect_id)
    event_db = await get_event_db()
    if not await event_db.has_handled_event(PROCEDURE_ACTIVATION_CONSUMER, event_id):
        return None
    operations = await db.list_operations_for_event(kind=OperationKind.PROCEDURE_ACTIVATION.value, event_id=event_id)
    recipients = tuple(
        LaunchRecipient(
            operation_id=operation.operation_id,
            procedure_id=command.procedure_id,
            home=command.home,
        )
        for operation in operations
        for command in (ActivateProcedureCommandPayload.model_validate_json(operation.payload_json),)
    )
    await store.commit_item_change(
        item, expect_digests={}, mutate=_record_recipients(launch.key, recipients), updated_by=None
    )
    return recipients


def _record_recipients(key: str, recipients: tuple[LaunchRecipient, ...]) -> Callable[..., ItemChange | None]:
    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None:
            return None
        record = workflow_record_of(current)
        if record.launch is None or record.launch.key != key or record.launch.recipients is not None:
            return None
        updated = record.model_copy(deep=True)
        updated.launch = record.launch.model_copy(update={RECIPIENTS_FIELD: recipients})
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: updated.to_state()})

    return mutate


async def has_terminal_evidence(
    store: WorkflowStore, project_root: str, item: str, item_id: str, launch: LaunchReservation
) -> bool:
    """Whether the reservation's request can no longer produce a driver, by what the platform durably recorded.

    The recipients are the activations the request event caused, as recorded on the reservation, whatever the
    published headers say now. Each must be terminal (a receipt retention has already deleted was terminal,
    because only terminal receipts are deleted), and none may have an open session bound to this item for its
    procedure and home. Recipients not yet observed are unknown and leave the reservation in place.
    """
    recipients = await _observe_recipients(store, project_root, item, item_id, launch)
    if recipients is None:
        return False
    for recipient in recipients:
        operation = await db.get_operation(recipient.operation_id)
        if operation is not None and operation.state not in TERMINAL_OPERATION_STATES:
            return False
    for recipient in recipients:
        if await _has_open_bound_session(item, recipient.procedure_id, recipient.home):
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
    if not await has_terminal_evidence(store, project_root, item, item_id, launch):
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
