"""Integration coverage for the cluster envelope wire contract."""

from __future__ import annotations

import json
from typing import NotRequired, TypedDict

import pytest

from teleclaude.transport.cluster_bridge import (
    CLUSTER_ENVELOPE_SCHEMA_VERSION,
    SESSION_PREFIX,
    MalformedClusterEnvelopeError,
    decode_envelope,
)
from teleclaude.transport.cluster_publisher import ClusterPublisher

pytestmark = pytest.mark.integration


class _ClusterPayload(TypedDict):
    session_id: str


class _FutureField(TypedDict):
    capability: str


class _RawEnvelope(TypedDict):
    schema_version: NotRequired[int | str]
    channel: str
    idempotency_key: str
    emitted_at: str
    origin: NotRequired[str]
    payload: _ClusterPayload
    future_field: NotRequired[_FutureField]


class _PublishingRedis:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.messages.append((channel, message))
        return 1


def _raw_envelope() -> _RawEnvelope:
    return {
        "schema_version": CLUSTER_ENVELOPE_SCHEMA_VERSION,
        "channel": f"{SESSION_PREFIX}created",
        "idempotency_key": "idem-1",
        "emitted_at": "2026-06-11T00:00:00+00:00",
        "origin": "local-computer",
        "payload": {"session_id": "sess-1"},
    }


def test_decode_envelope_defaults_absent_schema_version_to_current_version() -> None:
    raw = _raw_envelope()
    del raw["schema_version"]

    envelope = decode_envelope(json.dumps(raw))

    assert envelope.schema_version == CLUSTER_ENVELOPE_SCHEMA_VERSION


def test_decode_envelope_ignores_unknown_extra_keys() -> None:
    raw = _raw_envelope()
    raw["future_field"] = {"capability": "newer-peer"}

    envelope = decode_envelope(json.dumps(raw))

    assert envelope.schema_version == CLUSTER_ENVELOPE_SCHEMA_VERSION
    assert not hasattr(envelope, "future_field")


def test_decode_envelope_rejects_malformed_schema_version() -> None:
    raw = _raw_envelope()
    raw["schema_version"] = "1"

    with pytest.raises(MalformedClusterEnvelopeError):
        decode_envelope(json.dumps(raw))


def test_decode_envelope_still_rejects_missing_required_field() -> None:
    raw = _raw_envelope()
    del raw["origin"]

    with pytest.raises(MalformedClusterEnvelopeError):
        decode_envelope(json.dumps(raw))


async def test_cluster_publisher_stamps_schema_version_that_decodes_round_trip() -> None:
    redis = _PublishingRedis()

    async def redis_provider() -> _PublishingRedis:
        return redis

    publisher = ClusterPublisher(origin="local-computer", redis_provider=redis_provider)

    accepted = await publisher.publish(f"{SESSION_PREFIX}created", {"session_id": "sess-1"})

    assert accepted is True
    [(_channel, message)] = redis.messages
    envelope = decode_envelope(message)
    assert envelope.schema_version == CLUSTER_ENVELOPE_SCHEMA_VERSION
