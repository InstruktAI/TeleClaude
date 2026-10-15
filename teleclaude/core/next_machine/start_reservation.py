"""The durable record of what a driver start's reservation replaced on the item, and giving it back.

A start reserves the driver link before its session exists. A manual start also clears the operator's hold, and a task
start moves the phase to ``task_running``. Until the start is accepted (the session row exists) those are the
reservation's to give back; once it is accepted they are the start's own. The prior values are recorded on the row
itself, in the hold audit the reservation leaves behind, so a daemon that dies between the reservation and the session
can still give them back when it clears the dead link. The mark names the reserved session id, which no other writer
produces: an operator's own hold or release leaves a different audit, and then nothing here is restored.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError

from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.todos import HoldAuditSource, HoldAuditState


class ReservedPrior(BaseModel):
    """The hold, hold audit and phase a reservation replaced."""

    model_config = ConfigDict(frozen=True)

    hold: bool
    audit: HoldAuditState
    phase: str = ""


def reservation_mark(session_id: str, prior: ReservedPrior) -> HoldAuditState:
    """The hold audit a reservation leaves, carrying what it replaced."""
    return HoldAuditState(
        source=HoldAuditSource.START_RESERVATION,
        set_by_session_id=session_id,
        reason=prior.model_dump_json(),
    )


def _prior_in_mark(audit: HoldAuditState) -> ReservedPrior | None:
    """The prior values a reservation\'s mark carries, recognized by its own source and never by its reason prose.

    An operator\'s hold reason is free text; only the reservation writes the ``start_reservation`` source, so no reason
    an operator types can be read as rollback data.
    """
    if audit.source != HoldAuditSource.START_RESERVATION:
        return None
    try:
        return ReservedPrior.model_validate_json(audit.reason)
    except ValidationError:
        return None


def reserved_prior_of(audit: HoldAuditState, session_id: str) -> ReservedPrior | None:
    """What the reservation for this session replaced, when the audit is still that reservation\'s mark."""
    return _prior_in_mark(audit) if audit.set_by_session_id == session_id else None


def mark_session_id(audit: HoldAuditState) -> str:
    """The session id a reservation mark in the audit names; empty when the audit is not a reservation mark."""
    return audit.set_by_session_id if _prior_in_mark(audit) is not None else ""


def record_reservation(
    writer: StateWriter, session_id: str, *, clears_hold: bool, task_run: bool, left_over_accepted: bool
) -> None:
    """Reserve on the row: clear the hold when asked, move a task to running, and leave the mark when either happened.

    The same mutation records the prior values, so the reservation and its undo are one write. A mark an earlier start
    left behind is settled first, as that start ended: ``left_over_accepted`` says whether its session came to exist, so
    an accepted start keeps what it did and one that never began gives back what it replaced. The new reservation then
    records the row as that settlement left it.
    """
    state = writer.state
    left_over = mark_session_id(state.hold_audit)
    if left_over:
        give_back(writer, left_over, accepted=left_over_accepted)
    prior = ReservedPrior(
        hold=state.hold,
        audit=state.hold_audit.model_copy(deep=True),
        phase=state.lifecycle_phase.value if task_run else "",
    )
    restorable = (clears_hold and (state.hold or state.hold_audit != HoldAuditState())) or task_run
    if clears_hold:
        state.hold = False
        if not restorable:
            state.hold_audit = HoldAuditState()
    if task_run:
        state.lifecycle_phase = LifecyclePhase.TASK_RUNNING
    if restorable:
        state.hold_audit = reservation_mark(session_id, prior)


def give_back(writer: StateWriter, session_id: str, *, accepted: bool) -> None:
    """Settle the reservation\'s mark: an accepted start keeps what it did, an unaccepted one restores what it replaced.

    Nothing happens unless the audit is still this reservation\'s mark.
    """
    state = writer.state
    prior = reserved_prior_of(state.hold_audit, session_id)
    if prior is None:
        return
    if accepted:
        state.hold_audit = prior.audit if state.hold else HoldAuditState()
        return
    state.hold = prior.hold
    state.hold_audit = prior.audit
    if prior.phase and state.lifecycle_phase is LifecyclePhase.TASK_RUNNING:
        state.lifecycle_phase = LifecyclePhase(prior.phase)


async def settle_mark_on_any_row(todos_db: WorkflowStore, slug: str, session_id: str) -> None:
    """Settle an accepted start\'s mark on the item\'s row whatever its status, by the row\'s durable id.

    The live-row path cannot address a row that was removed or delivered while its start was being accepted; the mark
    must still be settled there, or a later reservation would read it as an unaccepted start.
    """
    for row in await todos_db.list_todo(include_icebox=True, include_delivered=True, include_removed=True):
        if row["slug"] != slug:
            continue
        state = await todos_db.read_state_by_id(row["id"])
        if state is None:
            continue
        writer = StateWriter(state)
        before = writer.state.hold_audit.model_copy(deep=True)
        give_back(writer, session_id, accepted=True)
        if writer.state.hold_audit != before:
            await writer.commit_by_id(todos_db, row["id"])
