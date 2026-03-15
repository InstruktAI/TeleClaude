"""Characterization tests for teleclaude.events.envelope."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from teleclaude.events.envelope import (
    SCHEMA_VERSION,
    ActionDescriptor,
    EventEnvelope,
    EventLevel,
    EventVisibility,
)


def _minimal_envelope(**kwargs: object) -> EventEnvelope:
    defaults: dict[str, object] = {  # guard: loose-dict - test helper merges caller overrides into defaults
        "event": "test.event",
        "source": "test",
        "level": EventLevel.OPERATIONAL,
    }
    defaults.update(kwargs)
    return EventEnvelope(**defaults)


class TestEventLevel:
    def test_infrastructure_value(self) -> None:
        assert int(EventLevel.INFRASTRUCTURE) == 0

    def test_operational_value(self) -> None:
        assert int(EventLevel.OPERATIONAL) == 1

    def test_workflow_value(self) -> None:
        assert int(EventLevel.WORKFLOW) == 2

    def test_business_value(self) -> None:
        assert int(EventLevel.BUSINESS) == 3

    def test_ordering(self) -> None:
        assert EventLevel.INFRASTRUCTURE < EventLevel.OPERATIONAL < EventLevel.WORKFLOW < EventLevel.BUSINESS


class TestEventVisibility:
    def test_local_value(self) -> None:
        assert EventVisibility.LOCAL.value == "local"

    def test_cluster_value(self) -> None:
        assert EventVisibility.CLUSTER.value == "cluster"

    def test_public_value(self) -> None:
        assert EventVisibility.PUBLIC.value == "public"


class TestEventEnvelopeDefaults:
    def test_version_defaults_to_schema_version(self) -> None:
        e = _minimal_envelope()
        assert e.version == SCHEMA_VERSION

    def test_visibility_defaults_to_local(self) -> None:
        e = _minimal_envelope()
        assert e.visibility == EventVisibility.LOCAL

    def test_payload_defaults_to_empty_dict(self) -> None:
        e = _minimal_envelope()
        assert e.payload == {}

    def test_domain_defaults_to_empty_string(self) -> None:
        e = _minimal_envelope()
        assert e.domain == ""

    def test_timestamp_is_set_on_creation(self) -> None:
        e = _minimal_envelope()
        assert e.timestamp is not None
        assert e.timestamp.tzinfo is not None

    def test_idempotency_key_defaults_none(self) -> None:
        e = _minimal_envelope()
        assert e.idempotency_key is None

    def test_entity_defaults_none(self) -> None:
        e = _minimal_envelope()
        assert e.entity is None

    def test_actions_defaults_none(self) -> None:
        e = _minimal_envelope()
        assert e.actions is None

    def test_terminal_when_defaults_none(self) -> None:
        e = _minimal_envelope()
        assert e.terminal_when is None

    def test_resolution_shape_defaults_none(self) -> None:
        e = _minimal_envelope()
        assert e.resolution_shape is None


class TestEventEnvelopeRequired:
    def test_missing_event_raises(self) -> None:
        with pytest.raises(ValidationError):
            EventEnvelope.model_validate({"source": "s", "level": 1})

    def test_missing_level_raises(self) -> None:
        with pytest.raises(ValidationError):
            EventEnvelope.model_validate({"event": "e", "source": "s"})


class TestToStreamDict:
    def test_event_field_preserved(self) -> None:
        e = _minimal_envelope()
        d = e.to_stream_dict()
        assert d["event"] == "test.event"

    def test_level_serialized_as_int_string(self) -> None:
        e = _minimal_envelope(level=EventLevel.WORKFLOW)
        d = e.to_stream_dict()
        assert d["level"] == "2"

    def test_visibility_serialized_as_value(self) -> None:
        e = _minimal_envelope(visibility=EventVisibility.CLUSTER)
        d = e.to_stream_dict()
        assert d["visibility"] == "cluster"

    def test_payload_serialized_as_json(self) -> None:
        e = _minimal_envelope(payload={"key": "val"})
        d = e.to_stream_dict()
        assert json.loads(d["payload"]) == {"key": "val"}

    def test_empty_payload_serialized_as_empty_json_object(self) -> None:
        e = _minimal_envelope()
        d = e.to_stream_dict()
        assert d["payload"] == "{}"

    def test_none_entity_serialized_as_empty_string(self) -> None:
        e = _minimal_envelope()
        d = e.to_stream_dict()
        assert d["entity"] == ""

    def test_none_idempotency_key_serialized_as_empty_string(self) -> None:
        e = _minimal_envelope()
        d = e.to_stream_dict()
        assert d["idempotency_key"] == ""

    def test_extra_fields_serialized_in_extra_key(self) -> None:
        e = _minimal_envelope(custom_field="custom_value")
        d = e.to_stream_dict()
        extra = json.loads(d["_extra"])
        assert extra["custom_field"] == "custom_value"

    def test_no_extra_key_when_no_extra_fields(self) -> None:
        e = _minimal_envelope()
        d = e.to_stream_dict()
        assert "_extra" not in d

    def test_actions_serialized_when_present(self) -> None:
        e = _minimal_envelope(actions={"act": ActionDescriptor(description="do it", produces="something")})
        d = e.to_stream_dict()
        actions = json.loads(d["actions"])
        assert "act" in actions
        assert actions["act"]["description"] == "do it"

    def test_empty_actions_serialized_as_empty_string(self) -> None:
        e = _minimal_envelope()
        d = e.to_stream_dict()
        assert d["actions"] == ""


class TestFromStreamDict:
    def test_roundtrip_basic(self) -> None:
        e = _minimal_envelope(source="svc", domain="test-domain")
        d = e.to_stream_dict()
        restored = EventEnvelope.from_stream_dict(d)
        assert restored.event == e.event
        assert restored.source == e.source
        assert restored.domain == e.domain

    def test_roundtrip_payload(self) -> None:
        e = _minimal_envelope(payload={"a": 1, "b": "two"})
        d = e.to_stream_dict()
        restored = EventEnvelope.from_stream_dict(d)
        assert restored.payload == {"a": 1, "b": "two"}

    def test_roundtrip_level(self) -> None:
        e = _minimal_envelope(level=EventLevel.BUSINESS)
        d = e.to_stream_dict()
        restored = EventEnvelope.from_stream_dict(d)
        assert restored.level == EventLevel.BUSINESS

    def test_roundtrip_visibility(self) -> None:
        e = _minimal_envelope(visibility=EventVisibility.PUBLIC)
        d = e.to_stream_dict()
        restored = EventEnvelope.from_stream_dict(d)
        assert restored.visibility == EventVisibility.PUBLIC

    def test_roundtrip_extra_fields(self) -> None:
        e = _minimal_envelope(extra_prop="extra_val")
        d = e.to_stream_dict()
        restored = EventEnvelope.from_stream_dict(d)
        assert restored.model_extra is not None
        assert restored.model_extra.get("extra_prop") == "extra_val"

    def test_accepts_bytes_keys_and_values(self) -> None:
        e = _minimal_envelope()
        d = e.to_stream_dict()
        bytes_dict = {k.encode(): v.encode() for k, v in d.items()}
        restored = EventEnvelope.from_stream_dict(bytes_dict)
        assert restored.event == e.event

    def test_roundtrip_idempotency_key(self) -> None:
        e = _minimal_envelope(idempotency_key="abc:123")
        d = e.to_stream_dict()
        restored = EventEnvelope.from_stream_dict(d)
        assert restored.idempotency_key == "abc:123"

    def test_roundtrip_entity(self) -> None:
        e = _minimal_envelope(entity="entity-id")
        d = e.to_stream_dict()
        restored = EventEnvelope.from_stream_dict(d)
        assert restored.entity == "entity-id"

    def test_roundtrip_resolution_shape(self) -> None:
        shape = {"outcome": "str"}
        e = _minimal_envelope(resolution_shape=shape)
        d = e.to_stream_dict()
        restored = EventEnvelope.from_stream_dict(d)
        assert restored.resolution_shape == shape

    def test_roundtrip_terminal_when(self) -> None:
        e = _minimal_envelope(terminal_when="resolved")
        d = e.to_stream_dict()
        restored = EventEnvelope.from_stream_dict(d)
        assert restored.terminal_when == "resolved"

    def test_roundtrip_actions(self) -> None:
        e = _minimal_envelope(actions={"do_it": ActionDescriptor(description="desc", produces="prod")})
        d = e.to_stream_dict()
        restored = EventEnvelope.from_stream_dict(d)
        assert restored.actions is not None
        assert "do_it" in restored.actions

    def test_roundtrip_timestamp_precision(self) -> None:
        fixed_ts = datetime(2024, 1, 15, 12, 30, 0, tzinfo=UTC)
        e = _minimal_envelope(timestamp=fixed_ts)
        d = e.to_stream_dict()
        restored = EventEnvelope.from_stream_dict(d)
        assert restored.timestamp == fixed_ts
