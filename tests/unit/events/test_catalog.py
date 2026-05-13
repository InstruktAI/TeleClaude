"""Characterization tests for teleclaude.events.catalog."""

from __future__ import annotations

import pytest

from teleclaude.events.catalog import EventCatalog, EventSchema, NotificationLifecycle
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.schemas import register_all


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
    def test_default_visibility_cluster(self) -> None:
        """Per the v2 event-bus contract, the safer default is CLUSTER.

        Schemas that intentionally stay in-process declare LOCAL explicitly;
        leaving the default in place classifies the event as cross-context.
        See docs/project/design/architecture-v2/event-bus-transports.md.
        """
        s = _make_schema()
        assert s.default_visibility == EventVisibility.CLUSTER

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


class TestRegisteredSchemaVisibility:
    """Cross-domain audit pinning implementation-plan §R6.

    Lives in ``test_catalog.py`` (rather than a separate test file) because
    the catalog is the single source of truth for registered schemas; a
    dedicated audit module would only be an orphan to the central catalog.
    """

    @staticmethod
    def _registered_visibilities() -> list[tuple[str, EventVisibility]]:
        catalog = EventCatalog()
        register_all(catalog)
        return [(event_type, schema.default_visibility) for event_type, schema in catalog._registry.items()]

    @pytest.mark.unit
    def test_at_least_one_schema_is_registered(self) -> None:
        """Sanity: ``register_all`` populates the catalog."""
        pairs = self._registered_visibilities()
        assert pairs, "expected at least one registered schema"

    @pytest.mark.unit
    def test_every_registered_schema_visibility_is_valid_enum_member(self) -> None:
        """Every registered schema's ``default_visibility`` is a valid ``EventVisibility``.

        Pins the R6 contract: the visibility-aware bus cannot route a schema
        without a non-None, valid-enum visibility. The dataclass default
        makes this structurally true; this test prevents a future schema
        from smuggling in a stray value at registration.
        """
        valid = set(EventVisibility)
        invalid = [(event_type, vis) for event_type, vis in self._registered_visibilities() if vis not in valid]
        assert not invalid, f"schemas with invalid default_visibility: {invalid}"
