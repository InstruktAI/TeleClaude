"""Lifecycle router consumer: wakes the lifecycle runner when a workflow event may change what it should do.

The router decides nothing about which todo is dispatched; it wakes the runner for the project the
event concerns, or for every local checkout on the minute tick, and the runner decides from todo
state. It acts only on events its own computer emitted.
"""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.config import config
from teleclaude.core.next_machine.lifecycle_runner import (
    default_session_runner,
    project_path_from_event_payload,
    run_lifecycle_runner,
)
from teleclaude.events.consumers import Consumer, Interest
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.events.schemas.sdlc import (
    RoadmapEntryMoved,
    SchedulerTickMinute,
    TodoCreated,
    TodoCreatedData,
    TodoDelivered,
    TodoPhaseAdvanced,
    TodoUpdated,
)
from teleclaude.events.schemas.system import EffectiveConfigUpdated, SessionEnded
from teleclaude.events.type_pattern import TypePattern
from teleclaude.project_root import is_project_checkout

logger = get_logger(__name__)

LIFECYCLE_ROUTER_CONSUMER = "lifecycle-router"

_TODO_CREATED = TodoCreated.type_name()
_SCHEDULER_TICK = SchedulerTickMinute.type_name()
_TRIGGER_TYPES = (
    SchedulerTickMinute,
    TodoCreated,
    TodoDelivered,
    TodoPhaseAdvanced,
    TodoUpdated,
    RoadmapEntryMoved,
    EffectiveConfigUpdated,
    SessionEnded,
)

_PICKUP_NOT_REQUESTED_EVENT = "Todo creation skipped: pickup not requested"
_NOT_A_CHECKOUT_EVENT = "Scheduler lifecycle wake-up skipped: project is not a checkout"
_MISSING_PROJECT_EVENT = "Workflow runner wake-up skipped: missing project identity"


async def _wake_every_local_checkout(trigger: str) -> None:
    """Wake the lifecycle runner for each project checkout on this computer."""
    client = TelecAPIClient(daemon_credential=True)
    await client.connect()
    try:
        projects = await client.list_projects()
    finally:
        await client.close()
    for project in projects:
        if project.computer and project.computer != config.computer.name:
            continue
        if not is_project_checkout(project.path):
            logger.debug(_NOT_A_CHECKOUT_EVENT, project_path=project.path)
            continue
        await run_lifecycle_runner(project.path, trigger=trigger, client_factory=default_session_runner)


async def _route(event: ReceivedEvent) -> None:
    """Wake the lifecycle runner for the project an event concerns; the minute tick wakes every local checkout."""
    if event.type == _SCHEDULER_TICK:
        await _wake_every_local_checkout(event.type)
        return
    if event.type == _TODO_CREATED:
        created = TodoCreatedData.model_validate(event.data)
        if not created.pickup_requested:
            logger.info(_PICKUP_NOT_REQUESTED_EVENT, slug=created.slug)
            return
    project_path = project_path_from_event_payload(event.data)
    if not project_path:
        logger.warning(_MISSING_PROJECT_EVENT, event=event.type)
        return
    await run_lifecycle_runner(project_path, trigger=event.type, client_factory=default_session_runner)


def build_lifecycle_router_consumer() -> Consumer:
    """The consumer that wakes the lifecycle runner on this computer's workflow events."""
    return Consumer(
        name=LIFECYCLE_ROUTER_CONSUMER,
        interest=Interest(
            types=tuple(TypePattern(declared.type_name()) for declared in _TRIGGER_TYPES),
            own_computer_only=True,
        ),
        handler=_route,
    )
