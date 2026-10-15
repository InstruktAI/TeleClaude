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
from teleclaude.types.workflow_record import ActStatus, LaunchReservation

logger = get_logger(__name__)


class ActivateProcedureCommandPayload(BaseModel):
    """The two fields of a persisted procedure activation that name its recipient."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    procedure_id: str
    home: str


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


async def has_terminal_evidence(project_root: str, item: str, item_id: str, launch: LaunchReservation) -> bool:
    """Whether the reservation's request can no longer produce a driver, by the platform's durable records of it.

    The request event is one event with one id. The activation consumer's handled record says it has finished
    submitting everything that event causes; the operations it accepted for that event, found by the event's
    own id, are exactly the recipients, whatever the published headers say now. Every one of them must be
    terminal, and none may have an open session bound to this item for its procedure and home. Anything not
    yet recorded, or no longer recorded, is unknown and leaves the reservation in place.
    """
    event_id = occurrence_id(project_root, item_id, launch.effect_id)
    event_db = await get_event_db()
    if not await event_db.has_handled_event(PROCEDURE_ACTIVATION_CONSUMER, event_id):
        return False
    operations = await db.list_operations_for_event(kind=OperationKind.PROCEDURE_ACTIVATION.value, event_id=event_id)
    if any(operation.state not in TERMINAL_OPERATION_STATES for operation in operations):
        return False
    for operation in operations:
        command = ActivateProcedureCommandPayload.model_validate_json(operation.payload_json)
        if await _has_open_bound_session(item, command.procedure_id, command.home):
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
