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
