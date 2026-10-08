"""Lifecycle router cartridge — routes todo lifecycle events by payload.kind."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.config import config
from teleclaude.core.next_machine.lifecycle_runner import (
    default_session_runner,
    project_path_from_event_payload,
    run_lifecycle_runner,
)
from teleclaude.events.pipeline import PipelineContext
from teleclaude.events.wire import StreamEvent
from teleclaude.project_root import is_project_checkout

logger = get_logger(__name__)

_TRIGGER_EVENTS = {
    "teleclaude.scheduler.tick.minute",
    "sdlc.todo.created",
    "sdlc.todo.delivered",
    "sdlc.todo.phase_advanced",
    "sdlc.todo.updated",
    "sdlc.roadmap.entry_moved",
    "teleclaude.config.effective.updated",
    "teleclaude.agent_runtime.session.ended",
}


class LifecycleRouterCartridge:
    """Cartridge that routes todo lifecycle events."""

    name = "lifecycle-router"

    def describe(self) -> str:
        """Return cartridge name."""
        return self.name

    async def process(self, event: StreamEvent, context: PipelineContext) -> StreamEvent | None:
        """Wake the lifecycle runner on domain-bound trigger events; pass others through."""
        if event.type not in _TRIGGER_EVENTS:
            return event
        origin = event.source
        if origin and origin != config.computer.name:
            return event

        if event.type == "sdlc.todo.created":
            slug_raw = event.data.get("slug")
            slug = slug_raw if isinstance(slug_raw, str) else ""
            pickup_requested = event.data.get("pickup_requested", True)
            if not pickup_requested:
                logger.info("sdlc.todo.created skipped: pickup_requested=False", slug=slug)
                return event
        if event.type == "teleclaude.scheduler.tick.minute":
            _ = context
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
                    logger.debug(
                        "scheduler lifecycle wake-up skipped: project is not a checkout", project_path=project.path
                    )
                    continue
                await run_lifecycle_runner(
                    project.path,
                    trigger=event.type,
                    client_factory=default_session_runner,
                )
            return event
        project_path = project_path_from_event_payload(event.data)
        if not project_path:
            logger.warning("workflow runner wake-up skipped: missing project identity", event=event.type)
            return event
        _ = context
        await run_lifecycle_runner(
            project_path,
            trigger=event.type,
            client_factory=default_session_runner,
        )
        return event
