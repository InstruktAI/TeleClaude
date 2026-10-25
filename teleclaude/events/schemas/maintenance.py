"""Maintenance event declarations: one lifecycle family whose subject is the activated tip of a canonical checkout.

An activation settles once every action it owes has a terminal outcome. The type carries the state, so a
reader routes on the type alone: ``failed`` names the actions that stayed failed and the command that replays
each, ``succeeded`` names none. The subject is the commit identified by ``<project slug>/<sha>``, because commit
maintenance runs for projects that declare no remote repository and the project slug is the repository identity
every such checkout has.
"""

from __future__ import annotations

from teleclaude.events.catalog import DeclaredEvent, EventData, LifecycleState, PlatformEvent
from teleclaude.events.envelope import EventHomeKind
from teleclaude.events.references import CommitRef

MAINTENANCE_ACTIVATION_FAMILY = "teleclaude.maintenance.activation"


class FailedMaintenanceAction(EventData):
    """One owed action that stayed failed, with the command that replays it for the same activation."""

    action_id: str
    replay_command: str


class MaintenanceActivationData(EventData):
    """The facts of one settled activation: its range and the actions that stayed failed."""

    project: str
    before_revision: str | None
    after_revision: str
    failed_actions: list[FailedMaintenanceAction]


class MaintenanceActivationSucceeded(PlatformEvent[CommitRef, MaintenanceActivationData]):
    FAMILY = MAINTENANCE_ACTIVATION_FAMILY
    STATE = LifecycleState.SUCCEEDED
    DESCRIPTION = "A canonical-main commit activation settled with every owed maintenance action completed"
    HOME_KINDS = (EventHomeKind.PROJECT,)


class MaintenanceActivationFailed(PlatformEvent[CommitRef, MaintenanceActivationData]):
    FAMILY = MAINTENANCE_ACTIVATION_FAMILY
    STATE = LifecycleState.FAILED
    DESCRIPTION = "A canonical-main commit activation settled with an owed maintenance action failed"
    HOME_KINDS = (EventHomeKind.PROJECT,)


DECLARED: tuple[DeclaredEvent, ...] = (MaintenanceActivationSucceeded, MaintenanceActivationFailed)
