"""teleclaude_events — event processing platform core package."""

from teleclaude_events.catalog import EventCatalog, EventSchema, NotificationLifecycle, build_default_catalog
from teleclaude_events.db import EventDB
from teleclaude_events.envelope import ActionDescriptor, EventEnvelope, EventLevel, EventVisibility
from teleclaude_events.pipeline import Pipeline, PipelineContext
from teleclaude_events.processor import EventProcessor
from teleclaude_events.producer import EventProducer, configure_producer, emit_event

__all__ = [
    "EventEnvelope",
    "EventLevel",
    "EventVisibility",
    "ActionDescriptor",
    "EventCatalog",
    "EventSchema",
    "NotificationLifecycle",
    "build_default_catalog",
    "EventDB",
    "Pipeline",
    "PipelineContext",
    "EventProcessor",
    "EventProducer",
    "configure_producer",
    "emit_event",
]
