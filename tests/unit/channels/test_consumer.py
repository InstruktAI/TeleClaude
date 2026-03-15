"""Characterization tests for teleclaude.channels.consumer."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from redis.exceptions import ResponseError

from teleclaude.channels.consumer import consume, ensure_consumer_group


class TestEnsureConsumerGroup:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_creates_group_with_mkstream(self) -> None:
        redis = AsyncMock()

        await ensure_consumer_group(redis, "channel:demo:events", "workers")

        redis.xgroup_create.assert_awaited_once_with("channel:demo:events", "workers", id="0", mkstream=True)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ignores_busygroup_errors(self) -> None:
        redis = AsyncMock()
        redis.xgroup_create = AsyncMock(side_effect=ResponseError("BUSYGROUP Consumer Group name already exists"))

        await ensure_consumer_group(redis, "channel:demo:events", "workers")

        redis.xgroup_create.assert_awaited_once_with("channel:demo:events", "workers", id="0", mkstream=True)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_reraises_other_response_errors(self) -> None:
        redis = AsyncMock()
        redis.xgroup_create = AsyncMock(side_effect=ResponseError("NOAUTH"))

        with pytest.raises(ResponseError, match="NOAUTH"):
            await ensure_consumer_group(redis, "channel:demo:events", "workers")


class TestConsume:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_stream_has_no_messages(self) -> None:
        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(return_value=[])

        messages = await consume(redis, "channel:demo:events", "workers", "consumer-1", count=5, block_ms=0)

        assert messages == []
        redis.xreadgroup.assert_awaited_once_with(
            "workers",
            "consumer-1",
            {"channel:demo:events": ">"},
            count=5,
            block=None,
        )
        redis.xack.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_decodes_payloads_and_acknowledges_all_read_ids(self) -> None:
        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            return_value=[
                (
                    b"channel:demo:events",
                    [
                        (b"1-0", {b"payload": b'{"kind": "deploy"}'}),
                        ("2-0", {"payload": "not-json"}),
                        (b"3-0", {}),
                    ],
                )
            ]
        )
        redis.xack = AsyncMock()

        messages = await consume(redis, "channel:demo:events", "workers", "consumer-1", block_ms=25)

        assert messages == [
            {"id": "1-0", "payload": {"kind": "deploy"}},
            {"id": "2-0", "payload": {"raw": "not-json"}},
        ]
        redis.xreadgroup.assert_awaited_once_with(
            "workers",
            "consumer-1",
            {"channel:demo:events": ">"},
            count=10,
            block=25,
        )
        redis.xack.assert_awaited_once_with("channel:demo:events", "workers", b"1-0", "2-0", b"3-0")
