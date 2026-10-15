"""The request, result and refusal of one lifecycle act."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from teleclaude.types.workflow_record import Act, Phase


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
    STAMP_IN_FLIGHT = "{act}: another invocation of this stamp is running its gates; repeat to attach"
    NOT_RECORDED = "{act}: the item does not record this invocation; repeat the act"
    WAIT_CHANGED = "{act}: the question {person} was asked changed while the act was being decided; read the item and repeat the act"
    DECISION_OWNER = "{act}: the item waits on {person}, and only that person's own session may decide"


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


@dataclass(frozen=True)
class ActResult:
    """What a performed act reports: its key, the item's phase afterwards and whether every effect finished."""

    act_key: str
    phase: Phase | None
    complete: bool
    finding_key: str = ""
