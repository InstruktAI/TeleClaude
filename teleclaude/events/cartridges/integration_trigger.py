"""Integration trigger cartridge — spawns integrator on deployment.started.

Stateless: reacts to ``deployment.started`` (finalize ready) by immediately
spawning or waking the singleton integrator session.  The integrator's own
state machine scans worktree state.yaml files to find candidates — no
in-memory event accumulation needed here.

Other integration lifecycle events pass through for observability.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.pipeline import PipelineContext

logger = get_logger(__name__)

_SPAWN_EVENT = "domain.software-development.deployment.started"

INTEGRATION_EVENT_TYPES = frozenset(
    {
        "domain.software-development.review.approved",
        "domain.software-development.branch.pushed",
        _SPAWN_EVENT,
        "domain.software-development.deployment.completed",
        "domain.software-development.deployment.failed",
    }
)

IntegratorSpawnCallback = Callable[[str, str, str, str], Coroutine[Any, Any, Any] | None]


class IntegrationTriggerCartridge:
    """Spawn the integrator when ``deployment.started`` fires.

    The integrator state machine scans worktree state for finalize-ready
    candidates.  This cartridge only needs to ensure the session exists.
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

    async def process(self, event: EventEnvelope, _context: PipelineContext) -> EventEnvelope | None:
        """On deployment.started, spawn the integrator. All events pass through."""
        if event.event not in INTEGRATION_EVENT_TYPES:
            return event

        payload = event.payload
        slug = str(payload.get("slug", ""))
        branch = str(payload.get("branch", ""))
        sha = str(payload.get("sha", ""))

        logger.info(
            "Integration trigger processing %s (slug=%s, branch=%s, sha=%s)",
            event.event,
            slug,
            branch,
            sha[:8] if sha else "",
        )

        if event.event == _SPAWN_EVENT and self._spawn_callback is not None:
            caller_session_id = str(payload.get("caller_session_id", ""))
            await self._spawn_integrator(slug, branch, sha, caller_session_id)

        return event

    def identifier(self) -> str:
        """Return the stable cartridge identifier."""
        return self.name

    async def _spawn_integrator(self, slug: str, branch: str, sha: str, caller_session_id: str) -> None:
        """Spawn or wake the singleton integrator session."""
        logger.info(
            "Integration trigger: spawning integrator for slug=%s branch=%s sha=%s caller=%s",
            slug,
            branch,
            sha[:8] if sha else "",
            caller_session_id or "unknown",
        )
        try:
            result = self._spawn_callback(slug, branch, sha, caller_session_id)
            if asyncio.iscoroutine(result):
                await result
            logger.info("Integration trigger: spawn callback completed for %s", slug)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Integration trigger spawn callback failed for %s", slug)
