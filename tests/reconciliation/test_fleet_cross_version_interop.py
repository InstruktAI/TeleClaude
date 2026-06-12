"""Functional bindings for fleet cross-version interoperability."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from teleclaude.core.cache import DaemonCache
from teleclaude.core.models import ComputerInfo
from teleclaude.core.reconciliation import FeatureID, FeatureIDRegistry, FeatureMark
from teleclaude.core.reconciliation.capability_map import FleetCapabilityEntry, FleetCapabilityMap
from teleclaude.daemon import TeleClaudeDaemon
from teleclaude.transport.cluster_bridge import (
    CLUSTER_ENVELOPE_SCHEMA_VERSION,
    SESSION_PREFIX,
    ClusterBridge,
    decode_envelope,
)
from teleclaude.transport.cluster_publisher import ClusterPublisher
from teleclaude.transport.redis_transport._heartbeat import _HeartbeatMixin
from teleclaude.transport.redis_transport._peers import _PeersMixin

if TYPE_CHECKING:
    from redis.asyncio import Redis

pytestmark = [pytest.mark.functional]

_SPEC = "project/spec/feature/reconciliation/fleet-cross-version-interop"
_FEATURE_ID = "project/spec/feature/reconciliation/fleet-cross-version-interop"
_IGNORABLE_FEATURE_ID = "project/spec/feature/reconciliation/ignorable-capability"


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[bytes, bytes] = {}
        self.messages: list[tuple[str, str]] = []

    async def setex(self, key: str, _ttl: int, value: str) -> None:
        self.values[key.encode("utf-8")] = value.encode("utf-8")

    async def publish(self, channel: str, message: str) -> int:
        self.messages.append((channel, message))
        return 1

    async def get(self, key: bytes) -> bytes | None:
        return self.values.get(key)

    async def scan(self, _cursor: int, *, match: bytes, count: int) -> tuple[int, list[bytes]]:
        del count
        prefix, _, suffix = match.partition(b"*")
        keys = [key for key in self.values if key.startswith(prefix) and key.endswith(suffix)]
        return 0, sorted(keys)


class _HeartbeatHarness(_HeartbeatMixin):
    def __init__(self, redis: _FakeRedis, *, computer_name: str) -> None:
        self._redis = redis
        self.computer_name = computer_name
        self.heartbeat_ttl = 60

    async def _get_redis(self) -> Redis:
        return cast("Redis", self._redis)


class _PeerHarness(_PeersMixin):
    def __init__(self, redis: _FakeRedis, *, computer_name: str) -> None:
        self._redis = redis
        self.redis = redis
        self.computer_name = computer_name
        self.reconnects: list[str] = []

    async def _get_redis(self) -> Redis:
        return cast("Redis", self._redis)

    def _schedule_reconnect(self, reason: str, error: Exception | None = None) -> None:
        del error
        self.reconnects.append(reason)


# guard: loose-dict-func - synthesizes arbitrary cross-version heartbeat wire payloads; heterogeneous values and override bag by design
def _heartbeat_payload(
    *,
    computer_name: str,
    extra: dict[str, object] | None = None,
    omit: Iterable[str] = (),
) -> bytes:
    payload: dict[str, object] = {
        "computer_name": computer_name,
        "last_seen": "2026-06-11T00:00:00+00:00",
        "user": "peer-user",
        "host": "peer-host",
        "role": "worker",
        "system_stats": None,
    }
    if extra is not None:
        payload.update(extra)
    for key in omit:
        payload.pop(key, None)
    return json.dumps(payload).encode("utf-8")


def _registry_for_tests(*, carried_feature_ids: Iterable[str]) -> FeatureIDRegistry:
    return FeatureIDRegistry.from_entries(
        (
            FeatureID(_IGNORABLE_FEATURE_ID, FeatureMark.IGNORABLE),
            FeatureID(_FEATURE_ID, FeatureMark.MUST_NEGOTIATE),
        ),
        carried_feature_ids=carried_feature_ids,
    )


@pytest.mark.spec(_SPEC, "UC-FXI-1")
async def test_capability_advertisement_round_trips_through_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _FakeRedis()
    advertised = ComputerInfo(
        name="newer-node",
        status="online",
        user="node-user",
        host="node-host",
        role="worker",
        version="2.0.0",
        channel="alpha",
        capability_set=["feature-a"],
    )

    async def get_computer_info() -> ComputerInfo:
        return advertised

    monkeypatch.setattr(
        "teleclaude.transport.redis_transport._heartbeat.command_handlers.get_computer_info", get_computer_info
    )

    await _HeartbeatHarness(redis, computer_name=advertised.name)._send_heartbeat()
    peers = await _PeerHarness(redis, computer_name="older-node").discover_peers()

    [peer] = peers
    assert peer.version == advertised.version
    assert peer.channel == advertised.channel
    assert peer.capability_set == advertised.capability_set


@pytest.mark.spec(_SPEC, "UC-FXI-1")
async def test_older_heartbeat_payload_decodes_without_capability_fields() -> None:
    redis = _FakeRedis()
    redis.values[b"computer:older-node:heartbeat"] = _heartbeat_payload(
        computer_name="older-node",
        omit=("version", "channel", "capability_set"),
    )

    peers = await _PeerHarness(redis, computer_name="newer-node").discover_peers()

    [peer] = peers
    assert peer.version is None
    assert peer.channel is None
    assert peer.capability_set == []


@pytest.mark.spec(_SPEC, "UC-FXI-3")
def test_breaking_removal_waits_for_the_slowest_live_channel() -> None:
    observed_at = datetime(2026, 6, 11, tzinfo=UTC)
    capability_map = FleetCapabilityMap.materialize(
        [
            FleetCapabilityEntry(
                computer="alpha-node",
                version="2.0.0",
                channel="alpha",
                capability_set=frozenset({_FEATURE_ID}),
                last_advertised_at=observed_at,
            ),
            FleetCapabilityEntry(
                computer="stable-node",
                version="1.0.0",
                channel="stable",
                capability_set=frozenset(),
                last_advertised_at=observed_at,
            ),
        ],
        now=observed_at,
        heartbeat_ttl_seconds=60,
    )

    assert capability_map.safe_to_contract(_FEATURE_ID) is False


@pytest.mark.spec(_SPEC, "UC-FXI-5")
def test_safe_to_remove_is_derived_from_live_advertised_capabilities() -> None:
    observed_at = datetime(2026, 6, 11, tzinfo=UTC)
    capability_map = FleetCapabilityMap.materialize(
        [
            FleetCapabilityEntry(
                computer="alpha-node",
                version="2.0.0",
                channel="alpha",
                capability_set=frozenset({_FEATURE_ID}),
                last_advertised_at=observed_at,
            ),
            FleetCapabilityEntry(
                computer="stable-node",
                version="1.0.0",
                channel="stable",
                capability_set=frozenset({_FEATURE_ID}),
                last_advertised_at=observed_at,
            ),
        ],
        now=observed_at,
        heartbeat_ttl_seconds=60,
    )

    assert capability_map.safe_to_require(_FEATURE_ID) is True
    assert capability_map.safe_to_contract(_FEATURE_ID) is True


@pytest.mark.spec(_SPEC, "UC-FXI-5")
def test_aged_out_node_is_absent_from_safe_to_remove_answer() -> None:
    observed_at = datetime(2026, 6, 11, tzinfo=UTC)
    capability_map = FleetCapabilityMap.materialize(
        [
            FleetCapabilityEntry(
                computer="live-node",
                version="2.0.0",
                channel="alpha",
                capability_set=frozenset({_FEATURE_ID}),
                last_advertised_at=observed_at,
            ),
            FleetCapabilityEntry(
                computer="silent-node",
                version="1.0.0",
                channel="stable",
                capability_set=frozenset(),
                last_advertised_at=observed_at - timedelta(seconds=61),
            ),
        ],
        now=observed_at,
        heartbeat_ttl_seconds=60,
    )

    assert capability_map.safe_to_contract(_FEATURE_ID) is True


@pytest.mark.spec(_SPEC, "UC-FXI-5")
def test_cached_heartbeat_entries_materialize_into_capability_map() -> None:
    cache = DaemonCache()
    cache.update_computer(
        ComputerInfo(
            name="stable-node",
            status="online",
            version="1.0.0",
            channel="stable",
            capability_set=[_FEATURE_ID],
        )
    )

    capability_map = FleetCapabilityMap.materialize(
        cache.get_fleet_capability_entries(),
        now=datetime.now(UTC),
        heartbeat_ttl_seconds=60,
    )

    assert capability_map.safe_to_require(_FEATURE_ID) is True


@pytest.mark.spec(_SPEC, "UC-FXI-2")
def test_unsupported_ignorable_feature_leaves_daemon_cache_unchanged() -> None:
    daemon = object.__new__(TeleClaudeDaemon)
    daemon.cache = DaemonCache()
    bridge = ClusterBridge(
        redis_factory=lambda: object(),
        dispatch=daemon._dispatch_cluster_event,
        registry=_registry_for_tests(carried_feature_ids=()),
    )
    envelope = decode_envelope(
        json.dumps(
            {
                "schema_version": CLUSTER_ENVELOPE_SCHEMA_VERSION,
                "channel": f"{SESSION_PREFIX}created",
                "idempotency_key": "idem-daemon-unsupported-ignorable",
                "emitted_at": "2026-06-11T00:00:00+00:00",
                "origin": "newer-node",
                "feature_id": _IGNORABLE_FEATURE_ID,
                "payload": {"session_id": "sess-1"},
            }
        )
    )

    assert bridge.process_envelope(envelope) is False
    assert daemon.cache.get_sessions() == []


@pytest.mark.spec(_SPEC, "UC-FXI-2")
def test_unsupported_ignorable_feature_id_is_dropped_cleanly() -> None:
    dispatched = []
    bridge = ClusterBridge(
        redis_factory=lambda: object(),
        dispatch=dispatched.append,
        registry=_registry_for_tests(carried_feature_ids=()),
    )
    envelope = decode_envelope(
        json.dumps(
            {
                "schema_version": CLUSTER_ENVELOPE_SCHEMA_VERSION,
                "channel": f"{SESSION_PREFIX}created",
                "idempotency_key": "idem-unsupported-ignorable",
                "emitted_at": "2026-06-11T00:00:00+00:00",
                "origin": "newer-node",
                "feature_id": _IGNORABLE_FEATURE_ID,
                "payload": {"session_id": "sess-1"},
            }
        )
    )

    assert bridge.process_envelope(envelope) is False
    assert dispatched == []


@pytest.mark.spec(_SPEC, "UC-FXI-2")
async def test_ignorable_feature_id_round_trips_on_cluster_envelope() -> None:
    redis = _FakeRedis()

    async def redis_provider() -> _FakeRedis:
        return redis

    publisher = ClusterPublisher(
        origin="newer-node",
        redis_provider=redis_provider,
        registry=_registry_for_tests(carried_feature_ids=(_IGNORABLE_FEATURE_ID,)),
    )

    accepted = await publisher.publish(
        f"{SESSION_PREFIX}created",
        {"session_id": "sess-1"},
        feature_id=_IGNORABLE_FEATURE_ID,
    )

    assert accepted is True
    [(_channel, message)] = redis.messages
    envelope = decode_envelope(message)
    assert envelope.feature_id == _IGNORABLE_FEATURE_ID


@pytest.mark.spec(_SPEC, "UC-FXI-4")
async def test_must_negotiate_publish_holds_until_all_live_nodes_support() -> None:
    redis = _FakeRedis()
    observed_at = datetime(2026, 6, 11, tzinfo=UTC)
    capability_map = FleetCapabilityMap.materialize(
        [
            FleetCapabilityEntry(
                computer="stable-node",
                version="1.0.0",
                channel="stable",
                capability_set=frozenset(),
                last_advertised_at=observed_at,
            )
        ],
        now=observed_at,
        heartbeat_ttl_seconds=60,
    )

    async def redis_provider() -> _FakeRedis:
        return redis

    publisher = ClusterPublisher(
        origin="alpha-node",
        redis_provider=redis_provider,
        registry=_registry_for_tests(carried_feature_ids=(_FEATURE_ID,)),
        capability_map_provider=lambda: capability_map,
    )

    accepted = await publisher.publish(
        f"{SESSION_PREFIX}created",
        {"session_id": "sess-1"},
        feature_id=_FEATURE_ID,
    )

    assert accepted is False
    assert redis.messages == []
