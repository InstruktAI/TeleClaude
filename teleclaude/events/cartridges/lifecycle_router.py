"""Lifecycle router cartridge — routes todo lifecycle events by payload.kind."""

from __future__ import annotations

import os

from instrukt_ai_logging import get_logger

from teleclaude.cli.api_client import RunSessionArgs, TelecAPIClient
from teleclaude.config import config
from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.pipeline import PipelineContext

logger = get_logger(__name__)

_PLANNING_PREFIX = "domain.software-development.planning."
_WORKFLOW_PREFIX = "workflow."

_TRIGGER_EVENTS = {
    "domain.software-development.planning.artifact_changed",
    "domain.software-development.planning.todo_created",
    "domain.software-development.planning.todo_dumped",
    "domain.software-development.planning.todo_activated",
    "domain.software-development.planning.dependency_resolved",
    "workflow.todo.created",
}


class LifecycleRouterCartridge:
    """Cartridge that routes todo lifecycle events."""

    name = "lifecycle-router"

    def describe(self) -> str:
        """Return cartridge name."""
        return self.name

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        """Dispatch todo dump events and pass through other planning events."""
        if not (event.event.startswith(_PLANNING_PREFIX) or event.event.startswith(_WORKFLOW_PREFIX)):
            return event
        if event.event not in _TRIGGER_EVENTS:
            return event
        origin = event.originating_computer
        if origin and origin != config.computer.name:
            return event

        slug_raw = event.payload.get("slug")
        slug = slug_raw if isinstance(slug_raw, str) else None
        if not slug:
            logger.warning("event missing slug, skipping", event=event.event)
            return event

        # todo_dumped → route by payload.kind (no todo-state reads)
        if event.event == f"{_PLANNING_PREFIX}todo_dumped":
            kind_raw = event.payload.get("kind")
            kind = kind_raw if isinstance(kind_raw, str) else None
            await self._dispatch_router_lane(slug, kind)
            return event

        if event.event == "workflow.todo.created":
            pickup_requested = event.payload.get("pickup_requested", True)
            if not pickup_requested:
                logger.info("workflow.todo.created skipped: pickup_requested=False", slug=slug)
                return event
            kind_raw = event.payload.get("kind")
            kind = kind_raw if isinstance(kind_raw, str) else None
            await self._dispatch_router_lane(slug, kind)
            return event

        _ = context
        return event

    async def _dispatch_router_lane(self, slug: str, kind: str | None) -> None:
        """Dispatch a todo_dumped event to the correct orchestrator based on ``kind``.

        Routing is a pure function of the ``kind`` payload field: no todo state
        is read during dispatch. Missing and unknown kinds degrade to the
        default todo lane.
        """
        project_path = os.environ.get("TELECLAUDE_PROJECT_PATH", os.getcwd())
        dispatch_args: RunSessionArgs
        resolved_kind: str

        if kind == "prepped":
            resolved_kind = "prepped"
            dispatch_args = {
                "command": "/next-work",
                "project_path": project_path,
                "args": slug,
                "detach": True,
            }
        elif kind == "built":
            resolved_kind = "built"
            dispatch_args = {
                "command": "/next-work",
                "project_path": project_path,
                "args": slug,
                "detach": True,
            }
        elif kind == "bug":
            resolved_kind = "bug"
            dispatch_args = {
                "command": "/next-work",
                "project_path": project_path,
                "args": slug,
                "agent": "claude",
                "thinking_mode": "slow",
                "detach": True,
            }
        elif kind in ("todo", "feature", "refactor", "migration"):
            resolved_kind = "todo"
            dispatch_args = {
                "command": "/next-prepare",
                "project_path": project_path,
                "args": slug,
                "detach": True,
                "additional_context": "human_in_loop: false\n",
            }
        else:
            if kind is not None:
                logger.warning(
                    "unknown kind, degrading to todo lane",
                    slug=slug,
                    kind=kind,
                )
            resolved_kind = "todo"
            dispatch_args = {
                "command": "/next-prepare",
                "project_path": project_path,
                "args": slug,
                "detach": True,
                "additional_context": "human_in_loop: false\n",
            }

        api = TelecAPIClient()
        await api.connect()
        try:
            await api.run_session(**dispatch_args)
        finally:
            await api.close()
        logger.info(
            "dispatched lane",
            slug=slug,
            kind=resolved_kind,
            command=dispatch_args["command"],
        )
