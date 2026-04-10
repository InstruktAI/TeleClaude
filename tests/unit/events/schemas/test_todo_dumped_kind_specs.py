# guard: no-companion
"""Test spec (xfail) for work-cartridge-lifecycle-routing event schema behavior."""

from __future__ import annotations

import pytest

from teleclaude.events.catalog import EventCatalog
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility
from teleclaude.events.schemas.software_development import register_software_development

pytestmark = [
    pytest.mark.unit,
]


def _catalog() -> EventCatalog:
    catalog = EventCatalog()
    register_software_development(catalog)
    return catalog


def test_todo_dumped_schema_exposes_kind_as_meaningful_notification_field() -> None:
    schema = _catalog().get("domain.software-development.planning.todo_dumped")

    assert schema is not None
    assert schema.lifecycle is not None
    assert set(schema.lifecycle.meaningful_fields) >= {"slug", "kind"}


def test_todo_dumped_stream_roundtrip_preserves_kind_and_project_context() -> None:
    envelope = EventEnvelope(
        event="domain.software-development.planning.todo_dumped",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        visibility=EventVisibility.LOCAL,
        payload={
            "slug": "my-slug",
            "kind": "bug",
            "project_root": "/project",
        },
    )

    restored = EventEnvelope.from_stream_dict(envelope.to_stream_dict())

    assert restored.payload["slug"] == "my-slug"
    assert restored.payload["kind"] == "bug"
    assert restored.payload["project_root"] == "/project"


def test_todo_dumped_accepts_legacy_payloads_without_kind() -> None:
    envelope = EventEnvelope(
        event="domain.software-development.planning.todo_dumped",
        source="legacy-producer",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        visibility=EventVisibility.LOCAL,
        payload={
            "slug": "legacy-slug",
            "project_root": "/project",
        },
    )

    restored = EventEnvelope.from_stream_dict(envelope.to_stream_dict())

    assert restored.payload["slug"] == "legacy-slug"
    assert "kind" not in restored.payload
