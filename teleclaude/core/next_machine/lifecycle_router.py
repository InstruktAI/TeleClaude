"""Lifecycle router consumer: wakes the lifecycle runner when a workflow event may change what it should do.

The router decides nothing about which todo is dispatched; it wakes the runner for the project the
event concerns, or for every local checkout on the minute tick, and the runner decides from todo
state. It acts only on events its own computer emitted. A session ending of any kind reaches it; it
wakes the runner only when the session worked in a project checkout.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.next_machine.lifecycle_runner import (
    default_session_runner,
    project_path_from_event_payload,
    run_lifecycle_runner,
)
from teleclaude.core.shutdown_drain import get_shutdown_drain
from teleclaude.events.consumers import Consumer, Interest
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.events.renames import RETIRED_SESSION_ENDED_TYPE
from teleclaude.events.schemas.sdlc import (
    RoadmapEntryMoved,
    SchedulerTickMinute,
    TodoCreated,
    TodoCreatedData,
    TodoDelivered,
    TodoPhaseAdvanced,
    TodoUpdated,
)
from teleclaude.events.schemas.system import SESSION_ENDED_PREFIX, EffectiveConfigUpdated
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
)
# Every kind of session ending, and the retired single type an ending queued before the upgrade may still carry.
_SESSION_ENDED_PATTERNS = (TypePattern.below(SESSION_ENDED_PREFIX), TypePattern(RETIRED_SESSION_ENDED_TYPE))

_PICKUP_NOT_REQUESTED_EVENT = "Todo creation skipped: pickup not requested"
_NOT_A_CHECKOUT_EVENT = "Scheduler lifecycle wake-up skipped: project is not a checkout"
_MISSING_PROJECT_EVENT = "Workflow runner wake-up skipped: missing project identity"
_ENDED_OUTSIDE_CHECKOUT_EVENT = "Session-ended wake-up skipped: the session did not work in a project checkout"


async def _wake_every_local_checkout(trigger: str, discover_projects: Callable[[], list[str]]) -> None:
    """Wake the lifecycle runner for each project checkout on this computer.

    The registered projects come from the discovery the router was built with; the runner is woken for each
    one that is a project checkout.
    """
    for project_path in await asyncio.to_thread(discover_projects):
        if not is_project_checkout(project_path):
            logger.debug(_NOT_A_CHECKOUT_EVENT, project_path=project_path)
            continue
        await run_lifecycle_runner(project_path, trigger=trigger, client_factory=default_session_runner)


def _checkout_of_ended_session(project_path: str | None) -> str | None:
    """The resolved project checkout a session ending concerns, or ``None`` when the session worked elsewhere."""
    if not project_path:
        return None
    resolved = str(Path(project_path).resolve())
    return resolved if is_project_checkout(resolved) else None


async def _route(event: ReceivedEvent, *, discover_projects: Callable[[], list[str]]) -> None:
    """Wake the lifecycle runner for the project an event concerns; the minute tick wakes every local checkout."""
    if not get_shutdown_drain().is_open:
        # Waking the runner starts new work; the next process's minute tick wakes it again.
        logger.debug("lifecycle runner wake-up paused while draining", event=event.type)
        return
    if event.type == _SCHEDULER_TICK:
        await _wake_every_local_checkout(event.type, discover_projects)
        return
    if event.type == _TODO_CREATED:
        created = TodoCreatedData.model_validate(event.data)
        if not created.pickup_requested:
            logger.info(_PICKUP_NOT_REQUESTED_EVENT, slug=created.slug)
            return
    project_path = project_path_from_event_payload(event.data)
    if any(pattern.matches(event.type) for pattern in _SESSION_ENDED_PATTERNS):
        project_path = _checkout_of_ended_session(project_path)
        if project_path is None:
            logger.debug(_ENDED_OUTSIDE_CHECKOUT_EVENT, event=event.type)
            return
    if not project_path:
        logger.warning(_MISSING_PROJECT_EVENT, event=event.type)
        return
    await run_lifecycle_runner(project_path, trigger=event.type, client_factory=default_session_runner)


def build_lifecycle_router_consumer(discover_projects: Callable[[], list[str]]) -> Consumer:
    """The consumer that wakes the lifecycle runner on this computer's workflow events.

    ``discover_projects`` enumerates this computer's registered project roots for the minute tick.
    """
    return Consumer(
        name=LIFECYCLE_ROUTER_CONSUMER,
        interest=Interest(
            types=(*(TypePattern(declared.type_name()) for declared in _TRIGGER_TYPES), *_SESSION_ENDED_PATTERNS),
            own_computer_only=True,
        ),
        handler=partial(_route, discover_projects=discover_projects),
    )
