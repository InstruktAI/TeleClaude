"""Tests for the cross-computer Redis cluster bridge."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from teleclaude.transport.cluster_bridge import (
    COMPUTER_PREFIX,
    PROJECT_PREFIX,
    SESSION_PREFIX,
    TODO_PREFIX,
    ClusterBridge,
    ClusterCategory,
    ClusterEnvelope,
    MalformedClusterEnvelopeError,
    decode_envelope,
)

# Category discriminators (named-constant form per snapshot-testing policy).
SESSION_CATEGORY: ClusterCategory = "session"
PROJECT_CATEGORY: ClusterCategory = "project"
TODO_CATEGORY: ClusterCategory = "todo"
COMPUTER_CATEGORY: ClusterCategory = "computer"


def _envelope(
    *,
    channel: str = SESSION_PREFIX + "created",
    idempotency_key: str = "key-1",
    origin: str = "MozMini",
    payload: dict[str, object] | None = None,  # guard: loose-dict - mirrors envelope payload shape
) -> ClusterEnvelope:
    return ClusterEnvelope(
        channel=channel,
        idempotency_key=idempotency_key,
        emitted_at="2026-06-02T12:00:00Z",
        origin=origin,
        payload=payload if payload is not None else {"session_id": "s-1"},
    )


def _bridge(dispatch: Any) -> ClusterBridge:
    return ClusterBridge(redis_factory=lambda: MagicMock(), dispatch=dispatch)


class TestProcessEnvelope:
    def test_dispatches_session_envelope(self) -> None:
        dispatch = MagicMock()
        bridge = _bridge(dispatch)
        envelope = _envelope(channel=SESSION_PREFIX + "created")

        assert bridge.process_envelope(envelope) is True
        dispatch.assert_called_once_with(envelope)

    def test_dispatches_project_envelope(self) -> None:
        dispatch = MagicMock()
        bridge = _bridge(dispatch)
        envelope = _envelope(channel=PROJECT_PREFIX + "registered", idempotency_key="p-1")

        assert bridge.process_envelope(envelope) is True
        dispatch.assert_called_once_with(envelope)

    def test_dispatches_todo_envelope(self) -> None:
        dispatch = MagicMock()
        bridge = _bridge(dispatch)
        envelope = _envelope(channel=TODO_PREFIX + "updated", idempotency_key="t-1")

        assert bridge.process_envelope(envelope) is True
        dispatch.assert_called_once_with(envelope)

    def test_dispatches_computer_envelope(self) -> None:
        dispatch = MagicMock()
        bridge = _bridge(dispatch)
        envelope = _envelope(channel=COMPUTER_PREFIX + "updated", idempotency_key="c-1")

        assert bridge.process_envelope(envelope) is True
        dispatch.assert_called_once_with(envelope)

    def test_unknown_channel_is_dropped(self) -> None:
        dispatch = MagicMock()
        bridge = _bridge(dispatch)
        envelope = _envelope(channel="workflow.todo.created", idempotency_key="u-1")

        assert bridge.process_envelope(envelope) is False
        dispatch.assert_not_called()

    def test_idempotency_dedup_on_duplicate_key(self) -> None:
        dispatch = MagicMock()
        bridge = _bridge(dispatch)
        envelope = _envelope(idempotency_key="dup-key")

        first = bridge.process_envelope(envelope)
        second = bridge.process_envelope(envelope)

        assert first is True
        assert second is False
        assert dispatch.call_count == 1

    def test_dispatcher_exception_is_swallowed(self) -> None:
        dispatch = MagicMock(side_effect=RuntimeError("downstream failure"))
        bridge = _bridge(dispatch)
        envelope = _envelope()

        # Must not raise — subscriber loop continuation depends on it.
        assert bridge.process_envelope(envelope) is False
        dispatch.assert_called_once()


class TestDecodeEnvelope:
    def test_decodes_valid_envelope_round_trips(self) -> None:
        expected = ClusterEnvelope(
            channel=SESSION_PREFIX + "updated",
            idempotency_key="k-1",
            emitted_at="2026-06-02T00:00:00Z",
            origin="MozBook",
            payload={"session_id": "s-1"},
        )
        raw = json.dumps(
            {
                "channel": expected.channel,
                "idempotency_key": expected.idempotency_key,
                "emitted_at": expected.emitted_at,
                "origin": expected.origin,
                "payload": expected.payload,
            }
        )

        decoded = decode_envelope(raw)

        assert decoded == expected

    def test_decodes_bytes_input(self) -> None:
        raw = json.dumps(
            {
                "channel": SESSION_PREFIX + "closed",
                "idempotency_key": "k-2",
                "emitted_at": "2026-06-02T00:00:00Z",
                "origin": "MozMini",
                "payload": {"session_id": "s-2"},
            }
        ).encode("utf-8")

        decoded = decode_envelope(raw)
        assert decoded.channel == SESSION_PREFIX + "closed"

    def test_missing_channel_raises(self) -> None:
        raw = json.dumps(
            {
                "idempotency_key": "k",
                "emitted_at": "2026-06-02T00:00:00Z",
                "origin": "MozMini",
                "payload": {"session_id": "s"},
            }
        )
        with pytest.raises(MalformedClusterEnvelopeError):
            decode_envelope(raw)

    def test_missing_idempotency_key_raises(self) -> None:
        raw = json.dumps(
            {
                "channel": SESSION_PREFIX + "created",
                "emitted_at": "2026-06-02T00:00:00Z",
                "origin": "MozMini",
                "payload": {"session_id": "s"},
            }
        )
        with pytest.raises(MalformedClusterEnvelopeError):
            decode_envelope(raw)

    def test_missing_origin_raises(self) -> None:
        raw = json.dumps(
            {
                "channel": SESSION_PREFIX + "created",
                "idempotency_key": "k",
                "emitted_at": "2026-06-02T00:00:00Z",
                "payload": {"session_id": "s"},
            }
        )
        with pytest.raises(MalformedClusterEnvelopeError):
            decode_envelope(raw)

    def test_missing_payload_raises(self) -> None:
        raw = json.dumps(
            {
                "channel": SESSION_PREFIX + "created",
                "idempotency_key": "k",
                "emitted_at": "2026-06-02T00:00:00Z",
                "origin": "MozMini",
            }
        )
        with pytest.raises(MalformedClusterEnvelopeError):
            decode_envelope(raw)

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(MalformedClusterEnvelopeError):
            decode_envelope("not-json")

    def test_non_object_root_raises(self) -> None:
        with pytest.raises(MalformedClusterEnvelopeError):
            decode_envelope("[1,2,3]")


class TestEnvelopeCategory:
    def test_session_prefix_yields_session_category(self) -> None:
        envelope = _envelope(channel=SESSION_PREFIX + "created")
        assert envelope.category == SESSION_CATEGORY

    def test_project_prefix_yields_project_category(self) -> None:
        envelope = _envelope(channel=PROJECT_PREFIX + "registered")
        assert envelope.category == PROJECT_CATEGORY

    def test_todo_prefix_yields_todo_category(self) -> None:
        envelope = _envelope(channel=TODO_PREFIX + "updated")
        assert envelope.category == TODO_CATEGORY

    def test_computer_prefix_yields_computer_category(self) -> None:
        envelope = _envelope(channel=COMPUTER_PREFIX + "updated")
        assert envelope.category == COMPUTER_CATEGORY

    def test_unknown_prefix_yields_none(self) -> None:
        envelope = _envelope(channel="other.channel.kind")
        assert envelope.category is None
