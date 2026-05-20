"""teleclaude.events — event processing platform core package."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog, EventSchema, NotificationLifecycle
    from teleclaude.events.catalog import build_default_catalog as build_default_catalog
    from teleclaude.events.db import EventDB, get_event_db
    from teleclaude.events.envelope import ActionDescriptor, EventEnvelope, EventLevel, EventVisibility
    from teleclaude.events.pipeline import Pipeline, PipelineContext
    from teleclaude.events.processor import EventProcessor
    from teleclaude.events.producer import EventProducer, configure_producer, emit_event, ensure_event_producer

_EXPORTS = {
    "ActionDescriptor": ("teleclaude.events.envelope", "ActionDescriptor"),
    "EventCatalog": ("teleclaude.events.catalog", "EventCatalog"),
    "EventDB": ("teleclaude.events.db", "EventDB"),
    "EventEnvelope": ("teleclaude.events.envelope", "EventEnvelope"),
    "EventLevel": ("teleclaude.events.envelope", "EventLevel"),
    "EventProcessor": ("teleclaude.events.processor", "EventProcessor"),
    "EventProducer": ("teleclaude.events.producer", "EventProducer"),
    "EventSchema": ("teleclaude.events.catalog", "EventSchema"),
    "EventVisibility": ("teleclaude.events.envelope", "EventVisibility"),
    "NotificationLifecycle": ("teleclaude.events.catalog", "NotificationLifecycle"),
    "Pipeline": ("teleclaude.events.pipeline", "Pipeline"),
    "PipelineContext": ("teleclaude.events.pipeline", "PipelineContext"),
    "build_default_catalog": ("teleclaude.events.catalog", "build_default_catalog"),
    "configure_producer": ("teleclaude.events.producer", "configure_producer"),
    "emit_event": ("teleclaude.events.producer", "emit_event"),
    "ensure_event_producer": ("teleclaude.events.producer", "ensure_event_producer"),
    "get_event_db": ("teleclaude.events.db", "get_event_db"),
}


def __getattr__(name: str) -> object:
    """Load exported symbols lazily to keep event submodules acyclic."""
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(importlib.import_module(module_name), attr_name)
    globals()[name] = value
    return value


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
    "ensure_event_producer",
    "get_event_db",
]
