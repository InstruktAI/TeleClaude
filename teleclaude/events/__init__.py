"""teleclaude.events — event processing platform core package."""

from teleclaude.events.catalog import EventCatalog, EventSchema, NotificationLifecycle, build_default_catalog
from teleclaude.events.db import EventDB
from teleclaude.events.envelope import ActionDescriptor, EventEnvelope, EventLevel, EventVisibility
from teleclaude.events.pipeline import Pipeline, PipelineContext
from teleclaude.events.processor import EventProcessor
from teleclaude.events.producer import EventProducer, configure_producer, emit_event

__all__ = [
    "ActionDescriptor",
    "EventCatalog",
    "EventDB",
    "EventEnvelope",
    "EventLevel",
    "EventProcessor",
    "EventProducer",
    "EventSchema",
    "EventVisibility",
    "NotificationLifecycle",
    "Pipeline",
    "PipelineContext",
    "build_default_catalog",
    "configure_producer",
    "emit_event",
]
