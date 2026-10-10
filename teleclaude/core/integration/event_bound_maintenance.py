"""Event-bound maintenance: a project's own maintenance actions, performed on this computer for its events.

A project binds event types to maintenance actions in its own declaration. This consumer is handed every
project-origin event on this computer; it selects the bindings of the project the event belongs to, records
the owed actions as an event activation in that project's canonical checkout, and starts the drain that
performs them through the commit-boundary executor. Selection reads only the event's type and origin.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import load_checkpoint_model
from teleclaude.constants import CheckpointEventBinding
from teleclaude.core.integration.post_commit_maintenance import record_event_activation, start_drain_contender
from teleclaude.events.consumers import Consumer, Interest
from teleclaude.events.envelope import EventHomeKind, EventHomeRef, ReceivedEvent
from teleclaude.events.type_pattern import ANY_TYPE
from teleclaude.paths import ConfigFileName
from teleclaude.services.project_catalog.service import get_project_catalog_service

logger = get_logger(__name__)

EVENT_BOUND_MAINTENANCE_CONSUMER = "event-bound-maintenance"

_DECISION_EVENT = "event_bound_maintenance_decision"
_SKIPPED_OUTCOME = "skipped_ineligible_location"
_RECORDED_OUTCOME = "recorded"
_DRAIN_LAUNCH_FAILED = "the drain for event {event_id} of project {project} could not be launched"


class DrainLaunchError(RuntimeError):
    """The activation is recorded but no drain was started, so the event must not be acknowledged as handled."""


@dataclass(frozen=True)
class _DeclarationStamp:
    """What identifies one state of a project's declaration file without reading it."""

    modified_ns: int
    size: int


@dataclass(frozen=True)
class _ReadBindings:
    """The event bindings read from a declaration, with the stamp of the declaration they came from."""

    stamp: _DeclarationStamp | None
    bindings: tuple[CheckpointEventBinding, ...]


class _ProjectEventBindings:
    """Event bindings per project root, re-read only when the project's declaration file changed.

    The consumer is handed every project-origin event on the computer, so a project's declaration
    is read once per change, not once per event.
    """

    def __init__(self) -> None:
        self._read: dict[Path, _ReadBindings] = {}

    def action_ids(self, root: Path, event_type: str) -> tuple[str, ...]:
        """The action ids bound to the event type, in declared order and without repeats."""
        selected = [binding for binding in self._bindings(root) if binding.selects(event_type)]
        return tuple(dict.fromkeys(action_id for binding in selected for action_id in binding.actions))

    def _bindings(self, root: Path) -> tuple[CheckpointEventBinding, ...]:
        stamp = _declaration_stamp(root)
        known = self._read.get(root)
        if known is not None and known.stamp == stamp:
            return known.bindings
        read = _ReadBindings(stamp=stamp, bindings=load_checkpoint_model(str(root)).event_bindings)
        self._read[root] = read
        return read.bindings


def _declaration_stamp(root: Path) -> _DeclarationStamp | None:
    """The declaration file's modification stamp, or ``None`` when the root carries none."""
    try:
        status = (root / ConfigFileName.OVERLAY).stat()
    except FileNotFoundError:
        return None
    return _DeclarationStamp(modified_ns=status.st_mtime_ns, size=status.st_size)


def build_event_bound_maintenance_consumer() -> Consumer:
    """The consumer that performs, on this computer, the maintenance a project bound to an event about itself."""
    bindings = _ProjectEventBindings()

    def owed(origin: EventHomeRef, event_type: str) -> tuple[Path, tuple[str, ...]] | None:
        """The registered root of the origin project and the actions its bindings owe the event type."""
        project = get_project_catalog_service().get_by_slug(origin.instance)
        if project is None:
            return None
        action_ids = bindings.action_ids(project.root, event_type)
        return (project.root, action_ids) if action_ids else None

    async def handle(event: ReceivedEvent) -> None:
        origin = event.home
        if not isinstance(origin, EventHomeRef):
            return
        selected = await asyncio.to_thread(owed, origin, event.type)
        if selected is None:
            return
        root, action_ids = selected
        recorded = await asyncio.to_thread(record_event_activation, root, event, action_ids)
        logger.info(
            _DECISION_EVENT,
            project=origin.instance,
            event_id=event.id,
            event_type=event.type,
            action_ids=action_ids,
            outcome=_RECORDED_OUTCOME if recorded else _SKIPPED_OUTCOME,
        )
        if recorded and not await asyncio.to_thread(start_drain_contender, root):
            raise DrainLaunchError(_DRAIN_LAUNCH_FAILED.format(event_id=event.id, project=origin.instance))

    return Consumer(
        name=EVENT_BOUND_MAINTENANCE_CONSUMER,
        interest=Interest(
            types=(ANY_TYPE,),
            own_computer_only=False,
            origin_kinds=frozenset({EventHomeKind.PROJECT}),
        ),
        handler=handle,
    )
