"""Integration trigger cartridge — spawns integrator on todo_finalize_ready.

Stateless: reacts to ``planning.todo_finalize_ready`` (emitted by the
finalize-ready stamp) by ensuring the singleton integrator session exists.
The integrator's own state machine scans worktree state to find candidates
— no in-memory event accumulation needed here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.pipeline import PipelineContext

logger = get_logger(__name__)

_SPAWN_EVENT = "domain.software-development.planning.todo_finalize_ready"

IntegratorSpawnCallback = Callable[[str, str, str, str, str], Coroutine[Any, Any, Any] | None]


class IntegrationTriggerCartridge:
    """Spawn the integrator when ``todo_finalize_ready`` fires.

    The integrator state machine scans worktree state for finalize-ready
    candidates. This cartridge only needs to ensure the session exists.
    """

    name = "integration-trigger"

    def describe(self) -> str:
        """Return cartridge name."""
        return self.name

    def __init__(
        self,
        *,
        spawn_callback: IntegratorSpawnCallback | None = None,
    ) -> None:
        self._spawn_callback = spawn_callback
        self._spawned_event_keys: set[tuple[str, str, str]] = set()

    async def process(self, event: EventEnvelope, _context: PipelineContext) -> EventEnvelope | None:
        """On todo_finalize_ready, spawn the integrator. All other events pass through."""
        if event.event != _SPAWN_EVENT:
            return event
        origin = event.originating_computer
        if origin and origin != config.computer.name:
            return event

        payload = event.payload
        slug = str(payload.get("slug", ""))
        branch = str(payload.get("branch", ""))
        sha = str(payload.get("sha", ""))
        project_path = str(payload.get("project_path", ""))

        logger.info(
            "Integration trigger processing %s (slug=%s, branch=%s, sha=%s)",
            event.event,
            slug,
            branch,
            sha[:8] if sha else "",
        )

        if self._spawn_callback is not None:
            worker_session_id = str(payload.get("worker_session_id", ""))
            logical_key = (slug, sha, worker_session_id)
            if logical_key in self._spawned_event_keys:
                logger.info(
                    "skipping duplicate integrator spawn for slug=%s branch=%s sha=%s caller=%s",
                    slug,
                    branch,
                    sha[:8] if sha else "",
                    worker_session_id or "unknown",
                )
                return event
            await self._spawn_integrator(slug, branch, sha, worker_session_id, project_path)
            self._spawned_event_keys.add(logical_key)

        return event

    def identifier(self) -> str:
        """Return the stable cartridge identifier."""
        return self.name

    async def _spawn_integrator(
        self,
        slug: str,
        branch: str,
        sha: str,
        caller_session_id: str,
        project_path: str,
    ) -> None:
        """Ensure the singleton integrator session exists."""
        if not project_path:
            raise ValueError(f"Cannot spawn integrator for {slug}: missing project_path")
        logger.info(
            "spawning integrator for slug=%s branch=%s sha=%s caller=%s",
            slug,
            branch,
            sha[:8] if sha else "",
            caller_session_id or "unknown",
        )
        result = self._spawn_callback(slug, branch, sha, caller_session_id, project_path)
        if asyncio.iscoroutine(result):
            await result
        logger.info("spawn callback completed for %s", slug)
