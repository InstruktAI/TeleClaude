"""Who may perform each act of the item lifecycle.

The phases and acts themselves are the closed types in ``teleclaude.types.workflow_record``;
the contract that owns them is ``local/projects/teleclaude/spec/feature/workflow/item-lifecycle``.
This module owns the performer table, the one place that decides which session may perform an act.
"""

from __future__ import annotations

from enum import StrEnum

from teleclaude.types.workflow_record import Act, Phase


class Performer(StrEnum):
    """Who an act requires of the session performing it."""

    ANY_WRITER = "any session with todo write"
    CLAIMING_DRIVER = "the driver session the entry verb started"
    HOLDER_OR_PLATFORM = "the holder, or the platform on session end"
    HOLDER_OR_GROUP = "the holder or a session in its claiming group"
    HOLDER = "the holding driver"
    BUILDER_IN_GROUP = "a builder in the holder's claiming group"
    OWNER_SESSION = "the session of the person the item waits on"
    INTEGRATOR = "the integrator under its lease"


ACT_PERFORMERS: dict[Act, Performer] = {
    Act.CREATE: Performer.ANY_WRITER,
    Act.CLAIM: Performer.CLAIMING_DRIVER,
    Act.RELEASE: Performer.HOLDER_OR_PLATFORM,
    Act.NOTE: Performer.ANY_WRITER,
    Act.INTENT_EDIT: Performer.HOLDER_OR_GROUP,
    Act.REVIEWED: Performer.HOLDER,
    Act.FINDING: Performer.HOLDER,
    Act.REPLY: Performer.BUILDER_IN_GROUP,
    Act.PREPARED: Performer.HOLDER,
    Act.WAITING: Performer.HOLDER,
    Act.STAMP: Performer.HOLDER,
    Act.KICKBACK: Performer.HOLDER,
    Act.DECISION: Performer.OWNER_SESSION,
    Act.DELIVERED: Performer.INTEGRATOR,
}

HOLDER_CHECKED_ACTS: frozenset[Act] = frozenset(
    {
        Act.INTENT_EDIT,
        Act.REVIEWED,
        Act.FINDING,
        Act.REPLY,
        Act.PREPARED,
        Act.WAITING,
        Act.STAMP,
        Act.KICKBACK,
        Act.RELEASE,
    }
)

DRIVEN_PHASES: frozenset[Phase] = frozenset({Phase.PREPARATION, Phase.PREPARED, Phase.WORK, Phase.WAITING})
"""The phases a v2 procedure drives; the others belong to the creative machine and the integrator."""

REFUSAL_TEMPLATE = "{act} requires {performer}"
