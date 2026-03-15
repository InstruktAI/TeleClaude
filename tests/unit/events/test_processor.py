"""Characterization tests for teleclaude.events.processor."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.events.processor import (
    CONSUMER_GROUP,
    STREAM_NAME,
    EventProcessor,
)


def _make_envelope() -> EventEnvelope:
    return EventEnvelope(event="test.event", source="test", level=EventLevel.OPERATIONAL)


def _make_redis() -> MagicMock:
    redis = MagicMock()
    redis.xgroup_create = AsyncMock()
    redis.xreadgroup = AsyncMock(return_value=[])
    redis.xack = AsyncMock()
    return redis


class TestConstants:
    def test_stream_name(self) -> None:
        assert STREAM_NAME == "teleclaude:events"

    def test_consumer_group(self) -> None:
        assert CONSUMER_GROUP == "event-processor"


class TestEventProcessorInit:
    def test_default_stream(self) -> None:
        redis = _make_redis()
        pipeline = MagicMock()
        processor = EventProcessor(redis, pipeline)
        assert processor._stream == STREAM_NAME

    def test_default_group(self) -> None:
        redis = _make_redis()
        pipeline = MagicMock()
        processor = EventProcessor(redis, pipeline)
        assert processor._group == CONSUMER_GROUP

    def test_custom_stream_and_group(self) -> None:
        redis = _make_redis()
        pipeline = MagicMock()
        processor = EventProcessor(redis, pipeline, stream="s", group="g")
        assert processor._stream == "s"
        assert processor._group == "g"

    def test_consumer_name_override(self) -> None:
        redis = _make_redis()
        pipeline = MagicMock()
        processor = EventProcessor(redis, pipeline, consumer_name="my-consumer")
        assert processor._consumer == "my-consumer"

    def test_consumer_name_defaults_to_pid_based(self) -> None:
        import os

        redis = _make_redis()
        pipeline = MagicMock()
        processor = EventProcessor(redis, pipeline)
        assert f"{os.getpid()}" in processor._consumer


class TestEventProcessorStart:
    @pytest.mark.asyncio
    async def test_start_creates_consumer_group(self) -> None:
        redis = _make_redis()
        redis.xreadgroup = AsyncMock(side_effect=[[], asyncio.CancelledError()])
        pipeline = MagicMock()
        pipeline.execute = AsyncMock()
        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()
        await processor.start(shutdown)
        redis.xgroup_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_handles_busygroup_error(self) -> None:
        redis = _make_redis()
        redis.xgroup_create = AsyncMock(side_effect=Exception("BUSYGROUP already exists"))
        redis.xreadgroup = AsyncMock(return_value=[])
        pipeline = MagicMock()
        pipeline.execute = AsyncMock()
        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()
        # Should not raise on BUSYGROUP
        await processor.start(shutdown)

    @pytest.mark.asyncio
    async def test_start_raises_on_non_busygroup_xgroup_error(self) -> None:
        redis = _make_redis()
        redis.xgroup_create = AsyncMock(side_effect=Exception("connection refused"))
        pipeline = MagicMock()
        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()
        with pytest.raises(Exception, match="connection refused"):
            await processor.start(shutdown)


class TestProcessEntries:
    @pytest.mark.asyncio
    async def test_processes_entries_and_acks(self) -> None:
        event = _make_envelope()
        stream_dict = event.to_stream_dict()
        entries = [("stream", [("entry-1", stream_dict)])]

        redis = _make_redis()
        redis.xreadgroup = AsyncMock(side_effect=[entries, asyncio.CancelledError()])
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(return_value=event)
        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()
        await processor.start(shutdown)
        pipeline.execute.assert_called_once()
        redis.xack.assert_called_once()

    @pytest.mark.asyncio
    async def test_acks_even_if_pipeline_returns_none(self) -> None:
        event = _make_envelope()
        stream_dict = event.to_stream_dict()
        entries = [("stream", [("entry-1", stream_dict)])]

        redis = _make_redis()
        redis.xreadgroup = AsyncMock(side_effect=[entries, asyncio.CancelledError()])
        pipeline = MagicMock()
        pipeline.execute = AsyncMock(return_value=None)
        processor = EventProcessor(redis, pipeline)
        shutdown = asyncio.Event()
        shutdown.set()
        await processor.start(shutdown)
        redis.xack.assert_called_once()
