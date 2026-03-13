"""Integration trigger cartridge — feeds integration events to readiness projection.

Watches for review.approved, branch.pushed, and deployment.started events in the
pipeline.  Each event is translated to its canonical integration event type and
forwarded to the readiness projection via an injected ingest callback.  When a
candidate transitions to READY, the singleton integrator session is spawned via
the spawn callback.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine, Mapping, Sequence
from typing import Any

from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.pipeline import PipelineContext

logger = logging.getLogger(__name__)

INTEGRATION_EVENT_TYPES = frozenset(
    {
        "domain.software-development.review.approved",
        "domain.software-development.branch.pushed",
        "domain.software-development.deployment.started",
        "domain.software-development.deployment.completed",
        "domain.software-development.deployment.failed",
    }
)

# Maps platform event type → canonical integration event type
_PLATFORM_TO_CANONICAL: dict[str, str] = {
    "domain.software-development.review.approved": "review_approved",
    "domain.software-development.branch.pushed": "branch_pushed",
    "domain.software-development.deployment.started": "finalize_ready",
}

IntegratorSpawnCallback = Callable[[str, str, str], Coroutine[Any, Any, Any] | None]
# Ingest callback: takes (canonical_event_type, payload) → returns list of (slug, branch, sha) ready candidates
IngestionCallback = Callable[[str, Mapping[str, Any]], Sequence[tuple[str, str, str]]]


def _strip_pipeline_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Remove pipeline-private fields before canonical integration validation.

    Trust and later cartridges annotate payloads with underscore-prefixed keys
    such as ``_trust_flags``. Those fields are internal transport metadata, not
    part of the integration lifecycle contract, so they must not leak into the
    canonical validator.
    """

    return {key: value for key, value in payload.items() if not key.startswith("_")}


class IntegrationTriggerCartridge:
    """Pipeline cartridge that bridges event-platform events to the integration module.

    For matching integration events: translates to canonical type and calls the
    ingest callback to feed the readiness projection.  When a candidate goes READY,
    invokes the spawn callback to start or wake the singleton integrator session.

    Non-matching events pass through unchanged.
    """

    name = "integration-trigger"

    def __init__(
        self,
        *,
        spawn_callback: IntegratorSpawnCallback | None = None,
        ingest_callback: IngestionCallback | None = None,
    ) -> None:
        self._spawn_callback = spawn_callback
        self._ingest_callback = ingest_callback

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        if event.event not in INTEGRATION_EVENT_TYPES:
            return event

        payload = event.payload
        canonical_payload = _strip_pipeline_metadata(payload)
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

        canonical_type = _PLATFORM_TO_CANONICAL.get(event.event)
        if canonical_type and self._ingest_callback is not None:
            try:
                ready_candidates = self._ingest_callback(canonical_type, canonical_payload)
                if ready_candidates:
                    first = ready_candidates[0]
                    first_slug, first_branch, first_sha = first
                    if self._spawn_callback is not None:
                        try:
                            result = self._spawn_callback(first_slug, first_branch, first_sha)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception:
                            logger.exception("Integration trigger spawn callback failed for %s", first_slug)
            except Exception:
                logger.exception("Integration trigger ingest callback failed for %s event", event.event)

        return event
