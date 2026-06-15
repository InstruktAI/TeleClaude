"""Lifecycle router cartridge — routes todo lifecycle events by payload.kind."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.config import config
from teleclaude.core.next_machine.lifecycle_runner import project_path_from_event_payload, run_lifecycle_runner
from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.pipeline import PipelineContext

logger = get_logger(__name__)

_PLANNING_PREFIX = "domain.software-development.planning."
_WORKFLOW_PREFIX = "workflow."

_TRIGGER_EVENTS = {
    "domain.software-development.planning.artifact_changed",
    "domain.software-development.planning.todo_created",
    "domain.software-development.planning.todo_activated",
    "domain.software-development.planning.dependency_resolved",
    "workflow.todo.created",
    "workflow.todo.delivered",
    "workflow.todo.phase_advanced",
    "workflow.todo.updated",
    "workflow.roadmap.entry_moved",
    "config.effective.updated",
}


class LifecycleRouterCartridge:
    """Cartridge that routes todo lifecycle events."""

    name = "lifecycle-router"

    def describe(self) -> str:
        """Return cartridge name."""
        return self.name

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        """Dispatch todo creation events and pass through other planning events."""
        if not (
            event.event.startswith(_PLANNING_PREFIX)
            or event.event.startswith(_WORKFLOW_PREFIX)
            or event.event in _TRIGGER_EVENTS
        ):
            return event
        if event.event not in _TRIGGER_EVENTS:
            return event
        origin = event.originating_computer
        if origin and origin != config.computer.name:
            return event

        if event.event == "workflow.todo.created":
            slug_raw = event.payload.get("slug")
            slug = slug_raw if isinstance(slug_raw, str) else ""
            pickup_requested = event.payload.get("pickup_requested", True)
            if not pickup_requested:
                logger.info("workflow.todo.created skipped: pickup_requested=False", slug=slug)
                return event
        project_path = project_path_from_event_payload(event.payload)
        if not project_path:
            logger.warning("workflow runner wake-up skipped: missing project identity", event=event.event)
            return event
        _ = context
        await run_lifecycle_runner(project_path, trigger=event.event, client_factory=lambda: TelecAPIClient())
        return event
