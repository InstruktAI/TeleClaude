"""Tests for EventCatalog registry."""

from __future__ import annotations

import pytest

from teleclaude_events.catalog import EventCatalog, EventSchema, NotificationLifecycle, build_default_catalog
from teleclaude_events.envelope import EventLevel


def _make_schema(event_type: str = "test.event", idempotency_fields: list[str] | None = None) -> EventSchema:
    return EventSchema(
        event_type=event_type,
        description="Test event",
        default_level=EventLevel.WORKFLOW,
        domain="test",
        idempotency_fields=idempotency_fields or [],
    )


def test_register_and_get() -> None:
    catalog = EventCatalog()
    schema = _make_schema("test.created")
    catalog.register(schema)
    result = catalog.get("test.created")
    assert result is not None
    assert result.event_type == "test.created"


def test_get_unknown_returns_none() -> None:
    catalog = EventCatalog()
    assert catalog.get("unknown.event") is None


def test_list_all_sorted() -> None:
    catalog = EventCatalog()
    catalog.register(_make_schema("b.event"))
    catalog.register(_make_schema("a.event"))
    catalog.register(_make_schema("c.event"))
    all_schemas = catalog.list_all()
    types = [s.event_type for s in all_schemas]
    assert types == sorted(types)


def test_duplicate_registration_raises() -> None:
    catalog = EventCatalog()
    catalog.register(_make_schema("test.event"))
    with pytest.raises(ValueError, match="already registered"):
        catalog.register(_make_schema("test.event"))


def test_build_idempotency_key_with_fields() -> None:
    catalog = EventCatalog()
    schema = _make_schema("test.event", idempotency_fields=["slug", "round"])
    catalog.register(schema)
    key = catalog.build_idempotency_key("test.event", {"slug": "my-task", "round": "1"})
    assert key is not None
    assert "my-task" in key
    assert "1" in key
    assert key.startswith("test.event:")


def test_build_idempotency_key_no_fields_returns_none() -> None:
    catalog = EventCatalog()
    catalog.register(_make_schema("test.event", idempotency_fields=[]))
    key = catalog.build_idempotency_key("test.event", {"slug": "my-task"})
    assert key is None


def test_build_idempotency_key_unknown_event_returns_none() -> None:
    catalog = EventCatalog()
    key = catalog.build_idempotency_key("unknown.event", {"slug": "x"})
    assert key is None


def test_build_default_catalog_has_schemas() -> None:
    catalog = build_default_catalog()
    schemas = catalog.list_all()
    assert len(schemas) > 0


def test_build_default_catalog_has_system_schemas() -> None:
    catalog = build_default_catalog()
    assert catalog.get("system.daemon.restarted") is not None
    assert catalog.get("system.worker.crashed") is not None


def test_build_default_catalog_has_software_development_schemas() -> None:
    catalog = build_default_catalog()
    assert catalog.get("domain.software-development.planning.todo_created") is not None
    assert catalog.get("domain.software-development.build.completed") is not None


def test_notification_lifecycle_defaults() -> None:
    lc = NotificationLifecycle()
    assert lc.creates is False
    assert lc.updates is False
    assert lc.resolves is False
    assert lc.group_key is None
    assert lc.meaningful_fields == []
    assert lc.silent_fields == []


def test_event_schema_actionable_default() -> None:
    schema = _make_schema()
    assert schema.actionable is False
