"""teleclaude.events — event processing platform core package."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog, EventDeclaration, PlatformEvent
    from teleclaude.events.catalog import build_default_catalog as build_default_catalog
    from teleclaude.events.db import EventDB, get_event_db
    from teleclaude.events.envelope import EventLevel, EventVisibility, ReceivedEvent
    from teleclaude.events.pipeline import Pipeline, PipelineContext
    from teleclaude.events.processor import EventProcessor
    from teleclaude.events.producer import EventProducer, configure_producer, ensure_event_producer, publish_event

_EXPORTS = {
    "EventCatalog": ("teleclaude.events.catalog", "EventCatalog"),
    "EventDB": ("teleclaude.events.db", "EventDB"),
    "EventLevel": ("teleclaude.events.envelope", "EventLevel"),
    "EventProcessor": ("teleclaude.events.processor", "EventProcessor"),
    "EventProducer": ("teleclaude.events.producer", "EventProducer"),
    "EventDeclaration": ("teleclaude.events.catalog", "EventDeclaration"),
    "EventVisibility": ("teleclaude.events.envelope", "EventVisibility"),
    "PlatformEvent": ("teleclaude.events.catalog", "PlatformEvent"),
    "Pipeline": ("teleclaude.events.pipeline", "Pipeline"),
    "PipelineContext": ("teleclaude.events.pipeline", "PipelineContext"),
    "build_default_catalog": ("teleclaude.events.catalog", "build_default_catalog"),
    "configure_producer": ("teleclaude.events.producer", "configure_producer"),
    "publish_event": ("teleclaude.events.producer", "publish_event"),
    "ReceivedEvent": ("teleclaude.events.envelope", "ReceivedEvent"),
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
    "EventCatalog",
    "EventDB",
    "EventDeclaration",
    "EventLevel",
    "EventProcessor",
    "EventProducer",
    "EventVisibility",
    "Pipeline",
    "PipelineContext",
    "PlatformEvent",
    "ReceivedEvent",
    "build_default_catalog",
    "configure_producer",
    "ensure_event_producer",
    "get_event_db",
    "publish_event",
]
