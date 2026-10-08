"""Integration trigger consumer: spawns the integrator when a todo becomes finalize-ready.

Stateless: it reacts to the finalize-ready event by ensuring the project's integrator session
exists. The integrator's own state machine scans worktree state to find candidates, so nothing
accumulates here. Repeats of one transition share the event's id, so the platform hands the
consumer a transition once.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from instrukt_ai_logging import get_logger

from teleclaude.events.consumers import Consumer, Interest
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.events.schemas.sdlc import TodoFinalizeReady, TodoFinalizeReadyData
from teleclaude.events.type_pattern import TypePattern

logger = get_logger(__name__)

INTEGRATION_TRIGGER_CONSUMER = "integration-trigger"

IntegratorSpawnCallback = Callable[[str, str, str, str, str], Awaitable[object]]

_MISSING_PROJECT_PATH_ERROR = "Cannot spawn integrator for {slug}: missing project_path"
_PROCESSING_EVENT = "Integration trigger processing finalize-ready event"
_SPAWNING_EVENT = "Spawning integrator"
_SPAWN_COMPLETED_EVENT = "Integrator spawn callback completed"
_SHORT_SHA_LENGTH = 8


def build_integration_trigger_consumer(spawn: IntegratorSpawnCallback) -> Consumer:
    """The consumer that ensures the integrator session exists for each finalize-ready event of this computer."""

    async def handle(event: ReceivedEvent) -> None:
        ready = TodoFinalizeReadyData.model_validate(event.data)
        short_sha = ready.sha[:_SHORT_SHA_LENGTH]
        logger.info(_PROCESSING_EVENT, slug=ready.slug, branch=ready.branch, sha=short_sha)
        if not ready.project_path:
            raise ValueError(_MISSING_PROJECT_PATH_ERROR.format(slug=ready.slug))
        logger.info(
            _SPAWNING_EVENT,
            slug=ready.slug,
            branch=ready.branch,
            sha=short_sha,
            caller=ready.worker_session_id,
        )
        await spawn(ready.slug, ready.branch, ready.sha, ready.worker_session_id, ready.project_path)
        logger.info(_SPAWN_COMPLETED_EVENT, slug=ready.slug)

    return Consumer(
        name=INTEGRATION_TRIGGER_CONSUMER,
        interest=Interest(types=(TypePattern(TodoFinalizeReady.type_name()),), own_computer_only=True),
        handler=handle,
    )
