"""The door a refusal names: the first row of the contract's table that matches the item's state.

``local/projects/teleclaude/spec/feature/workflow/item-lifecycle`` (Acts only the previous machine knew). The previous-machine
acts and the creative capabilities both name their door through this one table.
"""

from __future__ import annotations

from typing import Final

from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import Phase

DOOR_HELD: Final = "the holding session {holder}"
DOOR_HELD_KICKBACK: Final = "the holding session {holder}, whose `telec todo act {item} kickback` returns the item"
DOOR_START: Final = "the driver start in progress (reservation {reservation}, requested by {requester}); {starting}"
STARTING_SESSION: Final = "the session it is starting, {session}, claims it"
STARTING_NO_SESSION: Final = "no session is open for it yet; the session it starts claims it"
DOOR_ADMITTED: Final = (
    "the integrator's admission at {sha}; the integrator delivers or parks it, and a parked item is then reachable "
    "by the ready or work row"
)
DOOR_WAITING: Final = (
    "{person}'s decision (`telec todo act {item} decision`), which starts the waited phase's driver; from work, "
    "that driver may kick back"
)
DOOR_READY: Final = "`telec todo work {item} --reason <text>`"
DOOR_WORK: Final = "`telec todo work {item}`, whose driver may kick back"
DOOR_PREPARATION: Final = "none needed: the item is in preparation, which `telec todo prepare {item}` drives"
DOOR_DESIGN: Final = (
    "the creative lane, `telec todo design {item}`; the item reaches preparation when its design completes"
)
UNKNOWN_REQUESTER: Final = "the lifecycle runner or a person at a terminal"


def door_for(state: TodoState, phase: Phase, item: str, *, started_session: str = "") -> str:
    """The door the first matching row of the contract's table names for the item's state."""
    holder = state.active_runner
    if holder:
        template = DOOR_HELD_KICKBACK if phase in (Phase.WORK, Phase.READY) else DOOR_HELD
        return template.format(holder=holder, item=item)
    launch = state.workflow.launch
    if launch is not None:
        starting = STARTING_SESSION.format(session=started_session) if started_session else STARTING_NO_SESSION
        return DOOR_START.format(
            reservation=launch.key[:8], requester=launch.requested_by or UNKNOWN_REQUESTER, starting=starting
        )
    admitted = state.workflow.admitted
    if admitted is not None:
        return DOOR_ADMITTED.format(sha=admitted.sha[:8])
    waiting = state.workflow.waiting
    if phase is Phase.WAITING and waiting is not None:
        return DOOR_WAITING.format(person=waiting.person, item=item)
    doors = {
        Phase.READY: DOOR_READY,
        Phase.WORK: DOOR_WORK,
        Phase.PREPARED: DOOR_WORK,
        Phase.PREPARATION: DOOR_PREPARATION,
        Phase.DESIGN: DOOR_DESIGN,
    }
    return doors.get(phase, DOOR_PREPARATION).format(item=item)
