"""Event catalog — registry of all known event schemas."""

from __future__ import annotations

from enum import StrEnum
from importlib import import_module

from pydantic import BaseModel, model_validator

from teleclaude.events.envelope import EventLevel, EventVisibility


class LifecycleFamily(StrEnum):
    """Closed incident families for lifecycle rows that share a group value."""

    TODO_LIFECYCLE = "todo_lifecycle"
    PLANNING_READINESS = "planning_readiness"
    BUILD = "build"
    REVIEW = "review"
    REVIEW_GATE_APPROVED = "review_gate_approved"
    DEPLOY_ATTEMPT = "deploy_attempt"
    DEPLOYMENT_LIFECYCLE = "deployment_lifecycle"
    OPS_ALERT = "ops_alert"
    DEPENDENCY_UPDATE = "dependency_update"
    PREPARE_PIPELINE = "prepare_pipeline"
    BRANCH_PUSHED = "branch_pushed"
    DOCS_WATCHER_SYNC = "docs_watcher_sync"
    ENTITY_DEGRADATION = "entity_degradation"
    AGENT_SESSION_LIFECYCLE = "agent_session_lifecycle"
    AGENT_RESTART = "agent_restart"
    CONFIG_SYNC = "config_sync"
    JOB_RUN = "job_run"
    NOTIFICATION_ESCALATION = "notification_escalation"
    DEPLOYMENT_OUTCOME = "deployment_outcome"
    CONTENT_LIFECYCLE = "content_lifecycle"
    MARKETING_CONTENT_LIFECYCLE = "marketing_content_lifecycle"
    MARKETING_CAMPAIGN = "marketing_campaign"
    CREATIVE_ASSET_REVIEW = "creative_asset_review"
    CREATIVE_ASSET_TRANSCODE = "creative_asset_transcode"


class NotificationLifecycle(BaseModel):
    """Notification projection semantics for an event type."""

    creates: bool = False
    updates: bool = False
    resolves: bool = False
    group_key: str | None = None
    family: LifecycleFamily | None = None
    meaningful_fields: list[str] = []
    silent_fields: list[str] = []

    @model_validator(mode="after")
    def _validate_group_family(self) -> NotificationLifecycle:
        """Reject a grouped lifecycle whose incident family is implicit."""
        if self.group_key and self.family is None:
            raise ValueError("NotificationLifecycle group_key requires family")
        return self


class EventSchema(BaseModel):
    """Schema metadata describing how an event should be classified and projected."""

    event_type: str
    description: str
    default_level: EventLevel
    domain: str
    # Safer default per the v2 event-bus contract: cross-context schemas are the
    # majority. Schemas that intentionally stay in-process (content, deployment,
    # notification, signal) set ``default_visibility=EventVisibility.LOCAL``
    # explicitly. See docs/project/design/architecture-v2/event-bus-transports.md.
    default_visibility: EventVisibility = EventVisibility.CLUSTER
    lifecycle: NotificationLifecycle | None = None
    actionable: bool = False
    # Per-event delivery-debounce override: None inherits the platform default
    # (15s), a positive value sets the window, <= 0 delivers immediately.
    delivery_debounce_s: float | None = None


class EventCatalog:
    """In-memory registry of known event schemas keyed by event type."""

    def __init__(self) -> None:
        self._registry: dict[str, EventSchema] = {}

    def register(self, schema: EventSchema) -> None:
        """Register an event schema, rejecting duplicate event types."""
        if schema.event_type in self._registry:
            raise ValueError(f"Event type already registered: {schema.event_type}")
        self._registry[schema.event_type] = schema

    def get(self, event_type: str) -> EventSchema | None:
        """Return the schema for an event type, if one is registered."""
        return self._registry.get(event_type)

    def list_all(self) -> list[EventSchema]:
        """Return all registered schemas sorted by event type."""
        return sorted(self._registry.values(), key=lambda s: s.event_type)


def build_default_catalog() -> EventCatalog:
    """Build a catalog containing all built-in event schemas."""
    register_all = import_module("teleclaude.events.schemas").register_all
    catalog = EventCatalog()
    register_all(catalog)
    return catalog
