"""The durable record of what a driver start's reservation replaced on the item, and giving it back.

A start reserves the driver link before its session exists. A manual start also clears the operator's hold, and a task
start moves the phase to ``task_running``. Until the start is accepted (the session row exists) those are the
reservation's to give back; once it is accepted they are the start's own. The prior values are recorded on the row
itself, in the hold audit the reservation leaves behind, so a daemon that dies between the reservation and the session
can still give them back when it clears the dead link. The mark names the reserved session id, which no other writer
produces: an operator's own hold or release leaves a different audit, and then nothing here is restored.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict

from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.todos import HoldAuditState

START_RESERVED_REASON: Final = "driver start reserved"
_REASON_SEPARATOR: Final = ":"


class ReservedPrior(BaseModel):
    """The hold, hold audit and phase a reservation replaced."""

    model_config = ConfigDict(frozen=True)

    hold: bool
    audit: HoldAuditState
    phase: str = ""


def reservation_mark(session_id: str, prior: ReservedPrior) -> HoldAuditState:
    """The hold audit a reservation leaves, carrying what it replaced."""
    return HoldAuditState(
        set_by_session_id=session_id,
        reason=f"{START_RESERVED_REASON}{_REASON_SEPARATOR}{prior.model_dump_json()}",
    )


def reserved_prior_of(audit: HoldAuditState, session_id: str) -> ReservedPrior | None:
    """What the reservation for this session replaced, when the audit is still that reservation\'s mark."""
    head, separator, body = audit.reason.partition(_REASON_SEPARATOR)
    if head != START_RESERVED_REASON or not separator or audit.set_by_session_id != session_id:
        return None
    return ReservedPrior.model_validate_json(body)


def record_reservation(writer: StateWriter, session_id: str, *, clears_hold: bool, task_run: bool) -> None:
    """Reserve on the row: clear the hold when asked, move a task to running, and leave the mark when either happened.

    The same mutation records the prior values, so the reservation and its undo are one write.
    """
    state = writer.state
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
