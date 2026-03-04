"""Integration trigger cartridge — feeds integration events to readiness projection.

Watches for review.approved, deployment.started, and deployment.failed events
in the pipeline. When a candidate transitions to READY via the readiness
projection, triggers the singleton integrator session via a daemon callback.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

from teleclaude_events.envelope import EventEnvelope
from teleclaude_events.pipeline import PipelineContext

logger = logging.getLogger(__name__)

INTEGRATION_EVENT_TYPES = frozenset(
    {
        "domain.software-development.review.approved",
        "domain.software-development.deployment.started",
        "domain.software-development.deployment.completed",
        "domain.software-development.deployment.failed",
    }
)

IntegratorSpawnCallback = Callable[[str, str, str], Coroutine[Any, Any, Any] | None]


class IntegrationTriggerCartridge:
    """Pipeline cartridge that bridges event-platform events to the integration module.

    For matching integration events: extracts (slug, branch, sha) and feeds
    to the readiness projection.  When a candidate goes READY, invokes the
    spawn callback to start or wake the singleton integrator session.

    Non-matching events pass through unchanged.
    """

    name = "integration-trigger"

    def __init__(
        self,
        *,
        spawn_callback: IntegratorSpawnCallback | None = None,
    ) -> None:
        self._spawn_callback = spawn_callback

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
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

        if (
            event.event == "domain.software-development.deployment.started"
            and slug
            and branch
            and sha
            and self._spawn_callback is not None
        ):
            try:
                result = self._spawn_callback(slug, branch, sha)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Integration trigger spawn callback failed for %s", slug)

        return event
