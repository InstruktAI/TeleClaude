"""Lifecycle router cartridge — routes todo lifecycle events by payload.kind."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.cli.api_client import RunSessionArgs, TelecAPIClient
from teleclaude.config import config
from teleclaude.core.next_machine.kinds import canonical_kind
from teleclaude.core.next_machine.slug_resolution import (
    deps_satisfied,
    effective_delivered_slugs_for_dependencies,
    effective_prepared_slugs_for_dependencies,
)
from teleclaude.core.todos_db import get_todos_db
from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.pipeline import PipelineContext
from teleclaude.types.lifecycle import LifecyclePhase

logger = get_logger(__name__)

_PLANNING_PREFIX = "domain.software-development.planning."
_WORKFLOW_PREFIX = "workflow."

_TRIGGER_EVENTS = {
    "domain.software-development.planning.artifact_changed",
    "domain.software-development.planning.todo_created",
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
        """Dispatch todo creation events and pass through other planning events."""
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

        if event.event == "workflow.todo.created":
            pickup_requested = event.payload.get("pickup_requested", True)
            if not pickup_requested:
                logger.info("workflow.todo.created skipped: pickup_requested=False", slug=slug)
                return event
            kind_raw = event.payload.get("kind")
            kind = kind_raw if isinstance(kind_raw, str) else None
            phase_raw = event.payload.get("lifecycle_phase")
            phase = phase_raw if isinstance(phase_raw, str) else None
            project_path_raw = event.payload.get("project_path")
            project_path = project_path_raw if isinstance(project_path_raw, str) else ""
            await self._dispatch_router_lane(slug, kind, phase, project_path=project_path)
            return event

        _ = context
        return event

    async def _dispatch_router_lane(
        self,
        slug: str,
        kind: str | None,
        lifecycle_phase: str | None,
        *,
        project_path: str,
    ) -> None:
        """Dispatch a todo creation event to the correct orchestrator.

        Routing is a pure function of the canonical kind plus creation evidence:
        a bug, or an already-prepared todo (a supplied ``--plan``), skips prepare
        and enters the work lane; feature/change enter prepare, where the state
        machine derives the kind's entry phase (PRD for feature, plan for change).
        """
        if not project_path:
            raise ValueError(f"Cannot dispatch lifecycle lane for {slug}: missing project_path")
        dispatch_args: RunSessionArgs
        if kind is None or lifecycle_phase == LifecyclePhase.UNKINDED.value:
            dispatch_args = {
                "command": "/analyze-todo-input",
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
                kind="",
                command=dispatch_args["command"],
            )
            return

        resolved_kind = canonical_kind(kind)
        todos_db = await get_todos_db(project_path)
        dependencies = await todos_db.load_deps()
        work_lane = lifecycle_phase == LifecyclePhase.PREPARED.value
        satisfied = (
            await effective_delivered_slugs_for_dependencies(todos_db)
            if work_lane
            else await effective_prepared_slugs_for_dependencies(todos_db)
        )
        if not deps_satisfied(dependencies, satisfied, slug):
            unmet = [dep for dep in dependencies.get(slug, []) if dep not in satisfied]
            logger.info("workflow.todo.created skipped: dependency-blocked", slug=slug, unmet=unmet)
            return

        if lifecycle_phase == LifecyclePhase.PREPARED.value:
            dispatch_args = {
                "command": "/next-work",
                "project_path": project_path,
                "args": slug,
                "detach": True,
            }
        else:
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
