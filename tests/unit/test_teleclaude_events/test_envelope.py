"""Tests for EventEnvelope serialization and deserialization."""

from __future__ import annotations

from teleclaude_events.envelope import ActionDescriptor, EventEnvelope, EventLevel, EventVisibility


def test_event_visibility_values() -> None:
    assert EventVisibility.LOCAL == "local"
    assert EventVisibility.CLUSTER == "cluster"
    assert EventVisibility.PUBLIC == "public"


def test_event_level_values() -> None:
    assert int(EventLevel.INFRASTRUCTURE) == 0
    assert int(EventLevel.OPERATIONAL) == 1
    assert int(EventLevel.WORKFLOW) == 2
    assert int(EventLevel.BUSINESS) == 3


def test_envelope_defaults() -> None:
    env = EventEnvelope(
        event="test.event",
        source="test",
        level=EventLevel.WORKFLOW,
    )
    assert env.version == 1
    assert env.domain == ""
    assert env.description == ""
    assert env.visibility == EventVisibility.LOCAL
    assert env.payload == {}
    assert env.idempotency_key is None
    assert env.entity is None


def test_envelope_with_payload() -> None:
    env = EventEnvelope(
        event="domain.test.created",
        source="worker",
        level=EventLevel.BUSINESS,
        domain="test",
        visibility=EventVisibility.CLUSTER,
        payload={"slug": "my-task", "title": "Task Title"},
        entity="telec://todo/my-task",
    )
    assert env.payload["slug"] == "my-task"
    assert env.entity == "telec://todo/my-task"


def test_to_stream_dict_roundtrip() -> None:
    env = EventEnvelope(
        event="domain.test.created",
        source="worker",
        level=EventLevel.WORKFLOW,
        domain="test",
        visibility=EventVisibility.LOCAL,
        payload={"key": "value", "number": 42},
        description="Test event",
    )
    stream_dict = env.to_stream_dict()

    # All values should be strings
    assert all(isinstance(v, str) for v in stream_dict.values())

    # Deserialize
    stream_bytes = {k.encode(): v.encode() for k, v in stream_dict.items()}
    restored = EventEnvelope.from_stream_dict(stream_bytes)

    assert restored.event == env.event
    assert restored.source == env.source
    assert int(restored.level) == int(env.level)
    assert restored.domain == env.domain
    assert restored.visibility == env.visibility
    assert restored.payload == env.payload
    assert restored.description == env.description


def test_to_stream_dict_contains_required_fields() -> None:
    env = EventEnvelope(
        event="test.event",
        source="test",
        level=EventLevel.INFRASTRUCTURE,
    )
    stream_dict = env.to_stream_dict()
    assert "event" in stream_dict
    assert "source" in stream_dict
    assert "level" in stream_dict
    assert "version" in stream_dict
    assert "timestamp" in stream_dict


def test_action_descriptor() -> None:
    action = ActionDescriptor(
        description="Approve the review",
        produces="domain.review.approved",
    )
    assert action.description == "Approve the review"
    assert action.produces == "domain.review.approved"
    assert action.outcome_shape is None


def test_envelope_with_actions() -> None:
    env = EventEnvelope(
        event="domain.review.needs_decision",
        source="review-worker",
        level=EventLevel.BUSINESS,
        actions={
            "approve": ActionDescriptor(
                description="Approve",
                produces="domain.review.approved",
            )
        },
    )
    assert env.actions is not None
    assert "approve" in env.actions
