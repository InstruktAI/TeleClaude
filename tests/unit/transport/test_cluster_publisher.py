"""Tests for the cluster.* publisher helper."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from teleclaude.transport.cluster_publisher import ClusterPublisher

# Protocol identifiers (named-constant form per snapshot-testing policy).
TEST_CHANNEL = "cluster.session.created"
TEST_PROJECT_CHANNEL = "cluster.project.registered"
TEST_ORIGIN = "MozMini"
TEST_PAYLOAD: dict[str, object] = {"session_id": "s-1"}  # guard: loose-dict - test payload fixture
TEST_PROJECT_PAYLOAD: dict[str, object] = {"path": "/a"}  # guard: loose-dict - test payload fixture


@pytest.fixture
def fake_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.publish = AsyncMock()
    return redis


def _publisher(redis: AsyncMock, *, origin: str = TEST_ORIGIN) -> ClusterPublisher:
    async def provider() -> AsyncMock:
        return redis

    return ClusterPublisher(origin=origin, redis_provider=provider)


class TestPublish:
    @pytest.mark.unit
    async def test_publishes_envelope_to_channel(self, fake_redis: AsyncMock) -> None:
        publisher = _publisher(fake_redis)

        ok = await publisher.publish(TEST_CHANNEL, TEST_PAYLOAD)

        assert ok is True
        fake_redis.publish.assert_awaited_once()
        channel, body = fake_redis.publish.await_args.args
        assert channel == TEST_CHANNEL

        envelope = json.loads(body)
        assert envelope["channel"] == TEST_CHANNEL
        assert envelope["origin"] == TEST_ORIGIN
        assert envelope["payload"] == TEST_PAYLOAD
        assert isinstance(envelope["idempotency_key"], str) and envelope["idempotency_key"]
        assert isinstance(envelope["emitted_at"], str) and envelope["emitted_at"]

    @pytest.mark.unit
    async def test_each_publish_gets_unique_idempotency_key(self, fake_redis: AsyncMock) -> None:
        publisher = _publisher(fake_redis)

        await publisher.publish(TEST_PROJECT_CHANNEL, TEST_PROJECT_PAYLOAD)
        await publisher.publish(TEST_PROJECT_CHANNEL, TEST_PROJECT_PAYLOAD)

        keys = {json.loads(call.args[1])["idempotency_key"] for call in fake_redis.publish.await_args_list}
        assert len(keys) == 2

    @pytest.mark.unit
    async def test_publish_failure_is_swallowed_and_returns_false(self, fake_redis: AsyncMock) -> None:
        fake_redis.publish.side_effect = RuntimeError("redis down")
        publisher = _publisher(fake_redis)

        ok = await publisher.publish(TEST_CHANNEL, TEST_PAYLOAD)

        assert ok is False
