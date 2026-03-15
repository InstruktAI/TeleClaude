"""Characterization tests for teleclaude.events.catalog."""

from __future__ import annotations

import pytest

from teleclaude.events.catalog import EventCatalog, EventSchema, NotificationLifecycle
from teleclaude.events.envelope import EventLevel, EventVisibility


def _make_schema(event_type: str = "test.event", domain: str = "test") -> EventSchema:
    return EventSchema(
        event_type=event_type,
        description="a test event",
        default_level=EventLevel.OPERATIONAL,
        domain=domain,
    )


class TestNotificationLifecycle:
    def test_defaults_all_false(self) -> None:
        lc = NotificationLifecycle()
        assert lc.creates is False
        assert lc.updates is False
        assert lc.resolves is False

    def test_defaults_group_key_none(self) -> None:
        lc = NotificationLifecycle()
        assert lc.group_key is None

    def test_defaults_fields_empty(self) -> None:
        lc = NotificationLifecycle()
        assert lc.meaningful_fields == []
        assert lc.silent_fields == []


class TestEventSchema:
    def test_default_visibility_local(self) -> None:
        s = _make_schema()
        assert s.default_visibility == EventVisibility.LOCAL

    def test_default_idempotency_fields_empty(self) -> None:
        s = _make_schema()
        assert s.idempotency_fields == []

    def test_default_lifecycle_none(self) -> None:
        s = _make_schema()
        assert s.lifecycle is None

    def test_default_actionable_false(self) -> None:
        s = _make_schema()
        assert s.actionable is False


class TestEventCatalog:
    def test_register_and_get(self) -> None:
        catalog = EventCatalog()
        schema = _make_schema("my.event")
        catalog.register(schema)
        assert catalog.get("my.event") is schema

    def test_get_unknown_returns_none(self) -> None:
        catalog = EventCatalog()
        assert catalog.get("unknown.event") is None

    def test_duplicate_registration_raises(self) -> None:
        catalog = EventCatalog()
        catalog.register(_make_schema("dup.event"))
        with pytest.raises(ValueError):
            catalog.register(_make_schema("dup.event"))

    def test_list_all_returns_sorted_by_type(self) -> None:
        catalog = EventCatalog()
        catalog.register(_make_schema("z.event"))
        catalog.register(_make_schema("a.event"))
        catalog.register(_make_schema("m.event"))
        types = [s.event_type for s in catalog.list_all()]
        assert types == sorted(types)

    def test_list_all_returns_all_registered(self) -> None:
        catalog = EventCatalog()
        catalog.register(_make_schema("a.event"))
        catalog.register(_make_schema("b.event"))
        assert len(catalog.list_all()) == 2

    def test_list_all_empty_when_nothing_registered(self) -> None:
        catalog = EventCatalog()
        assert catalog.list_all() == []


class TestBuildIdempotencyKey:
    def test_returns_none_when_schema_not_found(self) -> None:
        catalog = EventCatalog()
        key = catalog.build_idempotency_key("missing.event", {"id": "123"})
        assert key is None

    def test_returns_none_when_no_idempotency_fields(self) -> None:
        catalog = EventCatalog()
        schema = EventSchema(
            event_type="no.fields",
            description="x",
            default_level=EventLevel.OPERATIONAL,
            domain="test",
            idempotency_fields=[],
        )
        catalog.register(schema)
        key = catalog.build_idempotency_key("no.fields", {"id": "123"})
        assert key is None

    def test_builds_key_from_payload_fields(self) -> None:
        catalog = EventCatalog()
        schema = EventSchema(
            event_type="my.event",
            description="x",
            default_level=EventLevel.OPERATIONAL,
            domain="test",
            idempotency_fields=["slug", "version"],
        )
        catalog.register(schema)
        key = catalog.build_idempotency_key("my.event", {"slug": "abc", "version": "1"})
        assert key == "my.event:abc:1"

    def test_missing_payload_field_becomes_empty_string(self) -> None:
        catalog = EventCatalog()
        schema = EventSchema(
            event_type="my.event",
            description="x",
            default_level=EventLevel.OPERATIONAL,
            domain="test",
            idempotency_fields=["slug"],
        )
        catalog.register(schema)
        key = catalog.build_idempotency_key("my.event", {})
        assert key == "my.event:"

    def test_key_starts_with_event_type(self) -> None:
        catalog = EventCatalog()
        schema = EventSchema(
            event_type="some.event",
            description="x",
            default_level=EventLevel.OPERATIONAL,
            domain="test",
            idempotency_fields=["id"],
        )
        catalog.register(schema)
        key = catalog.build_idempotency_key("some.event", {"id": "42"})
        assert key is not None
        assert key.startswith("some.event:")
