"""Characterization tests for teleclaude.events.schemas.content."""

from __future__ import annotations

import pytest

from teleclaude.events.catalog import EventCatalog, EventSchema
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.schemas.content import register_content


def _catalog() -> EventCatalog:
    catalog = EventCatalog()
    register_content(catalog)
    return catalog


def test_register_content_registers_three_event_types() -> None:
    catalog = _catalog()
    types = {s.event_type for s in catalog.list_all()}
    assert types == {"content.dumped", "content.refined", "content.published"}


def test_content_dumped_schema_fields() -> None:
    schema = _catalog().get("content.dumped")
    assert schema is not None
    assert schema.domain == "content"
    assert schema.default_level == EventLevel.WORKFLOW
    assert schema.default_visibility == EventVisibility.LOCAL
    assert schema.idempotency_fields == ["content_id"]
    assert schema.actionable is False


def test_content_dumped_lifecycle_creates() -> None:
    schema = _catalog().get("content.dumped")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.creates is True
    assert schema.lifecycle.updates is False
    assert schema.lifecycle.resolves is False
    assert schema.lifecycle.meaningful_fields == ["content_id"]


def test_content_refined_lifecycle_updates() -> None:
    schema = _catalog().get("content.refined")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.updates is True
    assert schema.lifecycle.creates is False
    assert schema.lifecycle.resolves is False
    assert schema.lifecycle.group_key == "content_id"


def test_content_published_has_business_level() -> None:
    schema = _catalog().get("content.published")
    assert schema is not None
    assert schema.default_level == EventLevel.BUSINESS


def test_content_published_lifecycle_resolves() -> None:
    schema = _catalog().get("content.published")
    assert schema is not None
    assert schema.lifecycle is not None
    assert schema.lifecycle.resolves is True
    assert schema.lifecycle.group_key == "content_id"


def test_catalog_rejects_duplicate_registration() -> None:
    catalog = _catalog()
    with pytest.raises(ValueError, match="already registered"):
        catalog.register(
            EventSchema(
                event_type="content.dumped",
                description="dup",
                default_level=EventLevel.WORKFLOW,
                domain="content",
            )
        )
