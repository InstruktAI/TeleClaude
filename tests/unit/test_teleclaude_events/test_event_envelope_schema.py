"""Tests for event-envelope-schema: expansion joint, core taxonomy, versioning, JSON Schema export."""

from __future__ import annotations

import json

from teleclaude_events.catalog import build_default_catalog
from teleclaude_events.envelope import SCHEMA_VERSION, EventEnvelope, EventLevel, EventVisibility
from teleclaude_events.schema_export import export_json_schema

# ---------------------------------------------------------------------------
# Phase 1: Expansion joint
# ---------------------------------------------------------------------------


def test_extra_fields_survive_construction() -> None:
    env = EventEnvelope(
        event="test.event",
        source="test",
        level=EventLevel.WORKFLOW,
        custom_tag="mesh-origin-xyz",
        priority_override=5,
    )
    assert env.custom_tag == "mesh-origin-xyz"  # type: ignore[attr-defined]
    assert env.priority_override == 5  # type: ignore[attr-defined]


def test_extra_fields_not_in_declared_fields() -> None:
    env = EventEnvelope(
        event="test.event",
        source="test",
        level=EventLevel.WORKFLOW,
        custom_tag="extra",
    )
    assert "custom_tag" not in EventEnvelope.model_fields
    assert env.model_extra is not None
    assert "custom_tag" in env.model_extra


def test_extra_fields_roundtrip_stream_dict() -> None:
    env = EventEnvelope(
        event="deployment.failed",
        source="demo",
        level=EventLevel.BUSINESS,
        domain="infrastructure",
        payload={"service": "proxy"},
        custom_tag="mesh-origin-xyz",
        priority_override=5,
    )
    stream = env.to_stream_dict()
    assert "_extra" in stream
    restored = EventEnvelope.from_stream_dict(stream)
    assert restored.custom_tag == "mesh-origin-xyz"  # type: ignore[attr-defined]
    assert restored.priority_override == 5  # type: ignore[attr-defined]


def test_no_extra_fields_produces_no_extra_key() -> None:
    env = EventEnvelope(
        event="test.event",
        source="test",
        level=EventLevel.WORKFLOW,
    )
    stream = env.to_stream_dict()
    assert "_extra" not in stream


def test_extra_fields_roundtrip_with_bytes_dict() -> None:
    env = EventEnvelope(
        event="test.event",
        source="test",
        level=EventLevel.WORKFLOW,
        mesh_node="node-a",
    )
    stream = env.to_stream_dict()
    bytes_dict = {k.encode(): v.encode() for k, v in stream.items()}
    restored = EventEnvelope.from_stream_dict(bytes_dict)
    assert restored.mesh_node == "node-a"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Phase 2: Core taxonomy
# ---------------------------------------------------------------------------

EXPECTED_FAMILIES = {"system", "domain", "node", "deployment", "content", "notification", "schema"}


def test_all_root_families_registered() -> None:
    catalog = build_default_catalog()
    registered_families = {s.event_type.split(".")[0] for s in catalog.list_all()}
    assert EXPECTED_FAMILIES.issubset(registered_families)


def test_each_registered_event_has_required_fields() -> None:
    catalog = build_default_catalog()
    for schema in catalog.list_all():
        assert schema.description, f"{schema.event_type} missing description"
        assert schema.default_level is not None, f"{schema.event_type} missing level"
        assert schema.domain, f"{schema.event_type} missing domain"


def test_new_event_types_idempotency_key_generation() -> None:
    catalog = build_default_catalog()
    key = catalog.build_idempotency_key("node.alive", {"node_id": "node-1"})
    assert key is not None
    assert "node-1" in key

    key = catalog.build_idempotency_key("deployment.failed", {"slug": "my-slug", "sha": "abc123"})
    assert key is not None
    assert "my-slug" in key


def test_node_events_registered() -> None:
    catalog = build_default_catalog()
    assert catalog.get("node.alive") is not None
    assert catalog.get("node.leaving") is not None
    assert catalog.get("node.descriptor_updated") is not None


def test_deployment_events_registered() -> None:
    catalog = build_default_catalog()
    assert catalog.get("deployment.started") is not None
    assert catalog.get("deployment.completed") is not None
    assert catalog.get("deployment.failed") is not None
    assert catalog.get("deployment.rolled_back") is not None


def test_content_events_registered() -> None:
    catalog = build_default_catalog()
    assert catalog.get("content.dumped") is not None
    assert catalog.get("content.refined") is not None
    assert catalog.get("content.published") is not None


def test_notification_events_registered() -> None:
    catalog = build_default_catalog()
    assert catalog.get("notification.escalation") is not None
    assert catalog.get("notification.resolution") is not None


def test_schema_events_registered() -> None:
    catalog = build_default_catalog()
    assert catalog.get("schema.proposed") is not None
    assert catalog.get("schema.adopted") is not None


def test_deployment_failed_is_actionable() -> None:
    catalog = build_default_catalog()
    schema = catalog.get("deployment.failed")
    assert schema is not None
    assert schema.actionable is True


def test_notification_escalation_is_actionable() -> None:
    catalog = build_default_catalog()
    schema = catalog.get("notification.escalation")
    assert schema is not None
    assert schema.actionable is True


def test_node_events_are_cluster_visible() -> None:
    catalog = build_default_catalog()
    for event_type in ("node.alive", "node.leaving", "node.descriptor_updated"):
        schema = catalog.get(event_type)
        assert schema is not None
        assert schema.default_visibility == EventVisibility.CLUSTER, f"{event_type} should be CLUSTER"


# ---------------------------------------------------------------------------
# Phase 3: Schema versioning
# ---------------------------------------------------------------------------


def test_schema_version_constant_exists() -> None:
    assert SCHEMA_VERSION == 1


def test_envelope_default_version_matches_schema_version() -> None:
    env = EventEnvelope(event="test", source="demo", level=EventLevel.OPERATIONAL)
    assert env.version == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Phase 4: JSON Schema export
# ---------------------------------------------------------------------------


def test_export_json_schema_returns_dict() -> None:
    schema = export_json_schema()
    assert isinstance(schema, dict)


def test_exported_schema_has_event_property() -> None:
    schema = export_json_schema()
    props = schema.get("properties", {})
    assert "event" in props


def test_exported_schema_is_structurally_valid() -> None:
    schema = export_json_schema()
    # A valid JSON Schema must have a type or properties at the top level
    assert "properties" in schema or "type" in schema
    # Must be serialisable
    assert json.dumps(schema)


def test_exported_schema_validates_real_envelope() -> None:
    catalog = build_default_catalog()
    node_schema = catalog.get("node.alive")
    assert node_schema is not None

    env = EventEnvelope(
        event="node.alive",
        source="node-1",
        level=node_schema.default_level,
        domain=node_schema.domain,
        visibility=node_schema.default_visibility,
    )
    envelope_dict = json.loads(env.model_dump_json())
    json_schema = export_json_schema()
    # All declared required fields present in the exported envelope
    for required_field in json_schema.get("required", []):
        assert required_field in envelope_dict, f"Required field {required_field!r} missing from envelope"


def test_export_json_schema_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from teleclaude_events.schema_export import export_json_schema_file

    output = tmp_path / "schema.json"
    export_json_schema_file(output)
    assert output.exists()
    loaded = json.loads(output.read_text())
    assert "properties" in loaded
    assert "event" in loaded["properties"]
