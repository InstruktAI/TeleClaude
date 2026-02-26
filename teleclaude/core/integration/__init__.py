"""Integration event model package."""

from teleclaude.core.integration.event_store import AppendResult, IntegrationEventStore, IntegrationEventStoreError
from teleclaude.core.integration.events import (
    BranchPushedPayload,
    FinalizeReadyPayload,
    IntegrationEvent,
    IntegrationEventPayload,
    IntegrationEventType,
    IntegrationEventValidationError,
    ReviewApprovedPayload,
    build_integration_event,
    compute_idempotency_key,
    parse_event_type,
    validate_event_payload,
)
from teleclaude.core.integration.readiness_projection import (
    CandidateKey,
    CandidateReadiness,
    ProjectionUpdate,
    ReadinessProjection,
    ReadinessStatus,
)
from teleclaude.core.integration.service import IngestionResult, IngestionStatus, IntegrationEventService

__all__ = [
    "AppendResult",
    "BranchPushedPayload",
    "FinalizeReadyPayload",
    "IntegrationEvent",
    "IntegrationEventPayload",
    "IntegrationEventStore",
    "IntegrationEventStoreError",
    "IntegrationEventService",
    "IntegrationEventType",
    "IntegrationEventValidationError",
    "IngestionResult",
    "IngestionStatus",
    "ProjectionUpdate",
    "ReadinessProjection",
    "ReadinessStatus",
    "ReviewApprovedPayload",
    "CandidateKey",
    "CandidateReadiness",
    "build_integration_event",
    "compute_idempotency_key",
    "parse_event_type",
    "validate_event_payload",
]
