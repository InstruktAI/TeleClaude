"""The request, result and refusal of one lifecycle act."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from teleclaude.core.workflow_machine.phase_reading import LaneFacts
from teleclaude.types.workflow_record import Act, Phase

BOUND_SEPARATOR: Final = ":"


class Refusal(StrEnum):
    """The reasons an act is refused; each names the act and what it requires."""

    PERFORMER = "{act} requires {performer}"
    UNKNOWN_ITEM = "{act}: no item {item} in this project"
    UNKNOWN_CALLER = "{act}: the calling session is unknown"
    WRONG_PHASE = "{act} cannot be performed while the item is in {phase}"
    MISSING_ARGUMENT = "{act} requires {argument}"
    NO_AUTHORITY = "{act}: {person} holds no authority over this project"
    UNKNOWN_FINDING = "{act}: no finding {finding} on this item"
    HOLDER_CHANGED = "{act}: the item's holder changed while the act was being decided; repeat the act"
    NOT_PERFORMED_HERE = "{act} is not performed through the act command"
    REVISION_MOVED = "{act}: the {artifact} is at {actual}, not at the {expected} the act names"
    CREATIVE_CHANGED = "{act}: its creative state changed while the act ran; repeat the act"
    TASK_LANE = "{act} does not apply to a todo of the task lane, which the task procedures drive"
    STAMP_IN_FLIGHT = "{act}: another stamp is running its gates on this item; repeat once it has settled"
    STAMP_SLOT_LOST = "{act}: this invocation no longer owns the stamp slot; repeat the act"
    WAIT_REQUIRED = "{act}: name the wait this answers with --wait; the waiting act reported its key"
    NOT_RECORDED = "{act}: the item does not record this invocation; repeat the act"
    WAIT_CHANGED = "{act}: the question {person} was asked changed while the act was being decided; read the item and repeat the act"
    DECISION_OWNER = "{act}: the item waits on {person}, and only that person's own session may decide"


class LaneNotResolved(Exception):
    """A phase was read before the act resolved the creative lane and the integration head."""


class ActRefused(Exception):
    """An act was refused; nothing was written."""


@dataclass(frozen=True)
class ActRequest:
    """One act as the sealed command receives it. Role and session come from the authenticated session."""

    project_root: str
    item: str
    act: Act
    caller_session_id: str
    text: str = ""
    sha: str = ""
    revision: str = ""
    person: str = ""
    finding_key: str = ""
    wait: str = ""
    lane: LaneFacts | None = None
    creative_snapshot: str = ""

    @property
    def resolved_lane(self) -> LaneFacts:
        """The lane facts the act resolved before it decided; reading them earlier is a defect."""
        if self.lane is None:
            raise LaneNotResolved(self.item)
        return self.lane


@dataclass(frozen=True)
class ActResult:
    """What a performed act reports: its key, the item's phase afterwards and whether every effect finished."""

    act_key: str
    phase: Phase | None
    complete: bool
    finding_key: str = ""
