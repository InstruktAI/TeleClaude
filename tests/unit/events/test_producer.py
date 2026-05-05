"""Characterization tests for teleclaude.events.producer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import teleclaude.events.producer as _mod
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility
from teleclaude.events.producer import (
    EventProducer,
    configure_producer,
    emit_event,
    ensure_event_producer,
)


def _make_redis(entry_id: str = "1234-0") -> MagicMock:
    redis = MagicMock()
    redis.xadd = AsyncMock(return_value=entry_id.encode())
    return redis


class TestEventProducer:
    @pytest.mark.asyncio
    async def test_emit_returns_entry_id_string(self) -> None:
        redis = _make_redis("1234-0")
        producer = EventProducer(redis)
        envelope = EventEnvelope(event="test.event", source="svc", level=EventLevel.OPERATIONAL)
        result = await producer.emit(envelope)
        assert result == "1234-0"

    @pytest.mark.asyncio
    async def test_emit_calls_xadd_with_stream_dict(self) -> None:
        redis = _make_redis()
        producer = EventProducer(redis, stream="my-stream", maxlen=500)
        envelope = EventEnvelope(event="test.event", source="svc", level=EventLevel.OPERATIONAL)
        await producer.emit(envelope)
        redis.xadd.assert_called_once()
        call_args = redis.xadd.call_args
        assert call_args.args[0] == "my-stream"

    @pytest.mark.asyncio
    async def test_emit_decodes_bytes_entry_id(self) -> None:
        redis = _make_redis("5678-0")
        producer = EventProducer(redis)
        envelope = EventEnvelope(event="test.event", source="svc", level=EventLevel.OPERATIONAL)
        result = await producer.emit(envelope)
        assert isinstance(result, str)
        assert result == "5678-0"

    @pytest.mark.asyncio
    async def test_emit_raises_on_xadd_failure(self) -> None:
        redis = MagicMock()
        redis.xadd = AsyncMock(side_effect=ConnectionError("redis down"))
        producer = EventProducer(redis)
        envelope = EventEnvelope(event="test.event", source="svc", level=EventLevel.OPERATIONAL)
        with pytest.raises(ConnectionError):
            await producer.emit(envelope)

    def test_default_stream(self) -> None:
        redis = MagicMock()
        producer = EventProducer(redis)
        assert producer._stream == "teleclaude:events"

    def test_default_maxlen(self) -> None:
        redis = MagicMock()
        producer = EventProducer(redis)
        assert producer._maxlen == 10000


class TestConfigureProducer:
    def test_configure_sets_module_producer(self) -> None:
        redis = _make_redis()
        producer = EventProducer(redis)
        configure_producer(producer)
        assert _mod._PRODUCER_STATE["producer"] is producer
        # cleanup
        _mod._PRODUCER_STATE["producer"] = None


class TestEnsureEventProducer:
    def test_returns_existing_producer_when_configured(self) -> None:
        redis = _make_redis()
        producer = EventProducer(redis)
        configure_producer(producer)
        try:
            assert ensure_event_producer() is producer
        finally:
            _mod._PRODUCER_STATE["producer"] = None

    def test_lazily_builds_and_registers_when_unconfigured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mod._PRODUCER_STATE["producer"] = None
        redis = _make_redis()
        built = EventProducer(redis)
        monkeypatch.setattr(_mod, "_build_producer_from_config", lambda: built)
        try:
            result = ensure_event_producer()
            assert result is built
            assert _mod._PRODUCER_STATE["producer"] is built
        finally:
            _mod._PRODUCER_STATE["producer"] = None

    def test_subsequent_calls_reuse_built_producer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mod._PRODUCER_STATE["producer"] = None
        redis = _make_redis()
        built = EventProducer(redis)
        calls = {"count": 0}

        def _build() -> EventProducer:
            calls["count"] += 1
            return built

        monkeypatch.setattr(_mod, "_build_producer_from_config", _build)
        try:
            first = ensure_event_producer()
            second = ensure_event_producer()
            assert first is second
            assert calls["count"] == 1
        finally:
            _mod._PRODUCER_STATE["producer"] = None


class TestEmitEvent:
    @pytest.mark.asyncio
    async def test_lazily_builds_producer_when_unconfigured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mod._PRODUCER_STATE["producer"] = None
        redis = _make_redis("4242-0")
        built = EventProducer(redis)
        monkeypatch.setattr(_mod, "_build_producer_from_config", lambda: built)
        try:
            result = await emit_event(
                event="test.event",
                source="svc",
                level=EventLevel.OPERATIONAL,
            )
            assert result == "4242-0"
            redis.xadd.assert_called_once()
        finally:
            _mod._PRODUCER_STATE["producer"] = None

    @pytest.mark.asyncio
    async def test_emits_via_configured_producer(self) -> None:
        redis = _make_redis("9999-0")
        producer = EventProducer(redis)
        configure_producer(producer)
        try:
            result = await emit_event(
                event="test.event",
                source="svc",
                level=EventLevel.OPERATIONAL,
                domain="test-domain",
                payload={"key": "val"},
            )
            assert result == "9999-0"
        finally:
            _mod._PRODUCER_STATE["producer"] = None

    @pytest.mark.asyncio
    async def test_emit_event_passes_visibility(self) -> None:
        redis = _make_redis()
        producer = EventProducer(redis)
        configure_producer(producer)
        try:
            await emit_event(
                event="test.event",
                source="svc",
                level=EventLevel.OPERATIONAL,
                visibility=EventVisibility.CLUSTER,
            )
            call_args = redis.xadd.call_args
            stream_data = call_args.args[1]
            assert stream_data["visibility"] == "cluster"
        finally:
            _mod._PRODUCER_STATE["producer"] = None
