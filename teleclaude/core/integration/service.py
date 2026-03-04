"""Integration event ingestion service.

With the integrator-wiring delivery, the readiness projection is fed from
the integration trigger cartridge (pipeline-based) rather than from a
file-based event store replay.  The file store is no longer used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from teleclaude.core.integration.events import (
    IntegrationEvent,
    IntegrationEventType,
    IntegrationEventValidationError,
    build_integration_event,
    parse_event_type,
)
from teleclaude.core.integration.readiness_projection import (
    CandidateReadiness,
    IntegratedChecker,
    ProjectionUpdate,
    ReachabilityChecker,
    ReadinessProjection,
)

IngestionStatus = Literal["APPENDED", "DUPLICATE", "REJECTED"]


@dataclass(frozen=True)
class IngestionResult:
    """Result of ingesting a single event."""

    status: IngestionStatus
    event: IntegrationEvent | None
    diagnostics: tuple[str, ...]
    transitioned_to_ready: tuple[CandidateReadiness, ...]
    transitioned_to_superseded: tuple[CandidateReadiness, ...]


class IntegrationEventService:
    """Ingest canonical events and keep readiness projection synchronized.

    In pipeline mode, events arrive via the integration trigger cartridge
    and are applied directly to the projection.  No file-based store is used.
    """

    def __init__(self, *, projection: ReadinessProjection) -> None:
        self._projection = projection
        self._last_update = ProjectionUpdate(transitioned_to_ready=(), transitioned_to_superseded=(), diagnostics=())

    @classmethod
    def create(
        cls,
        *,
        reachability_checker: ReachabilityChecker,
        integrated_checker: IntegratedChecker,
        remote: str = "origin",
    ) -> IntegrationEventService:
        """Build service with a fresh projection (pipeline-fed, no file store)."""
        return cls(
            projection=ReadinessProjection(
                reachability_checker=reachability_checker,
                integrated_checker=integrated_checker,
                remote=remote,
            ),
        )

    def replay(self, events: tuple[IntegrationEvent, ...] = ()) -> ProjectionUpdate:
        """Rebuild projection from a sequence of events (e.g. Redis Stream history)."""
        self._last_update = self._projection.replay(events)
        return self._last_update

    def ingest_raw(
        self, raw_event_type: str, payload: Mapping[str, object], *, idempotency_key: str | None = None
    ) -> IngestionResult:
        """Ingest event with runtime event-type validation."""
        try:
            event_type = parse_event_type(raw_event_type)
        except IntegrationEventValidationError as exc:
            return IngestionResult(
                status="REJECTED",
                event=None,
                diagnostics=exc.diagnostics,
                transitioned_to_ready=(),
                transitioned_to_superseded=(),
            )
        return self.ingest(event_type, payload, idempotency_key=idempotency_key)

    def ingest(
        self, event_type: IntegrationEventType, payload: Mapping[str, object], *, idempotency_key: str | None = None
    ) -> IngestionResult:
        """Validate and project one canonical event (no file persistence)."""
        try:
            event = build_integration_event(event_type, payload, idempotency_key=idempotency_key)
        except IntegrationEventValidationError as exc:
            return IngestionResult(
                status="REJECTED",
                event=None,
                diagnostics=exc.diagnostics,
                transitioned_to_ready=(),
                transitioned_to_superseded=(),
            )

        self._last_update = self._projection.apply(event)
        return IngestionResult(
            status="APPENDED",
            event=event,
            diagnostics=self._last_update.diagnostics,
            transitioned_to_ready=self._last_update.transitioned_to_ready,
            transitioned_to_superseded=self._last_update.transitioned_to_superseded,
        )

    def get_candidate(self, *, slug: str, branch: str, sha: str) -> CandidateReadiness | None:
        """Read current readiness snapshot for one candidate."""
        return self._projection.get_readiness(slug=slug, branch=branch, sha=sha)

    def all_candidates(self) -> tuple[CandidateReadiness, ...]:
        """List all known candidates and their readiness states."""
        return self._projection.all_candidates()
