"""Characterization tests for teleclaude.transport.redis_transport._connection."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.transport.redis_transport._transport import RedisTransport


@pytest.fixture
def transport() -> RedisTransport:
    with patch("teleclaude.transport.redis_transport._connection.Redis"):
        t = RedisTransport(MagicMock())
        t.redis = AsyncMock()
        return t


class TestResetIdlePollLogThrottle:
    @pytest.mark.unit
    def test_clears_last_log_timestamp(self, transport: RedisTransport) -> None:
        transport._idle_poll_last_log_at = 999.0
        transport._reset_idle_poll_log_throttle()
        assert transport._idle_poll_last_log_at is None

    @pytest.mark.unit
    def test_resets_suppressed_count_to_zero(self, transport: RedisTransport) -> None:
        transport._idle_poll_suppressed = 42
        transport._reset_idle_poll_log_throttle()
        assert transport._idle_poll_suppressed == 0


class TestMaybeLogIdlePoll:
    @pytest.mark.unit
    def test_increments_suppressed_count(self, transport: RedisTransport) -> None:
        transport._reset_idle_poll_log_throttle()
        transport._maybe_log_idle_poll(message_stream="messages:test")
        assert transport._idle_poll_suppressed == 1

    @pytest.mark.unit
    def test_does_not_log_within_60s_window(self, transport: RedisTransport) -> None:
        transport._reset_idle_poll_log_throttle()
        now = time.monotonic()
        transport._idle_poll_last_log_at = now - 30.0  # 30s ago, within window
        transport._idle_poll_suppressed = 0
        transport._maybe_log_idle_poll(message_stream="messages:test", now=now)
        # Within 60s window: counter increments but no log is emitted
        assert transport._idle_poll_suppressed == 1
        assert transport._idle_poll_last_log_at == now - 30.0

    @pytest.mark.unit
    def test_resets_suppressed_count_after_60s(self, transport: RedisTransport) -> None:
        transport._reset_idle_poll_log_throttle()
        now = time.monotonic()
        transport._idle_poll_last_log_at = now - 61.0  # expired
        transport._idle_poll_suppressed = 5
        transport._maybe_log_idle_poll(message_stream="messages:test", now=now)
        # After 60s window expires: throttled log emitted, counter resets, timestamp advances
        assert transport._idle_poll_suppressed == 0
        assert transport._idle_poll_last_log_at == now


class TestLogTaskException:
    @pytest.mark.unit
    def test_cancelled_task_does_not_log(self, transport: RedisTransport) -> None:
        task = MagicMock()
        task.cancelled.return_value = True
        # Should not raise, no logging expected
        transport._log_task_exception(task)
        task.exception.assert_not_called()

    @pytest.mark.unit
    def test_task_with_no_exception_does_not_log(self, transport: RedisTransport) -> None:
        task = MagicMock()
        task.cancelled.return_value = False
        task.exception.return_value = None
        transport._log_task_exception(task)
        task.exception.assert_called_once()


class TestStart:
    @pytest.mark.unit
    async def test_sets_running_flag(self, transport: RedisTransport) -> None:
        transport._ensure_connection_and_start_tasks = AsyncMock()
        assert transport._running is False
        await transport.start()
        assert transport._running is True

    @pytest.mark.unit
    async def test_start_called_twice_does_not_duplicate(self, transport: RedisTransport) -> None:
        transport._ensure_connection_and_start_tasks = AsyncMock()
        await transport.start()
        first_task = transport._connection_task
        await transport.start()
        # Second call should be a no-op — same task reference
        assert transport._connection_task is first_task


class TestStop:
    @pytest.mark.unit
    async def test_sets_running_false(self, transport: RedisTransport) -> None:
        transport._running = True
        transport.redis = AsyncMock()
        transport.redis.aclose = AsyncMock()
        await transport.stop()
        assert transport._running is False

    @pytest.mark.unit
    async def test_stop_when_not_running_is_noop(self, transport: RedisTransport) -> None:
        transport._running = False
        # Must not raise
        await transport.stop()

    @pytest.mark.unit
    async def test_cancels_message_poll_task(self, transport: RedisTransport) -> None:
        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.cancel = MagicMock()
        transport._running = True
        transport._message_poll_task = mock_task
        transport.redis = AsyncMock()
        transport.redis.aclose = AsyncMock()
        await transport.stop()
        mock_task.cancel.assert_called_once()


class TestCreateRedisClient:
    @pytest.mark.unit
    def test_creates_client_with_url(self, transport: RedisTransport) -> None:
        with patch("teleclaude.transport.redis_transport._connection.Redis") as mock_redis_cls:
            mock_redis_cls.from_url.return_value = MagicMock()
            transport._create_redis_client()
            mock_redis_cls.from_url.assert_called_once()
            assert mock_redis_cls.from_url.call_args[0][0] == transport.redis_url

    @pytest.mark.unit
    def test_ssl_cert_reqs_set_for_rediss_url(self, transport: RedisTransport) -> None:
        transport.redis_url = "rediss://localhost:6379"
        with patch("teleclaude.transport.redis_transport._connection.Redis") as mock_redis_cls:
            mock_redis_cls.from_url.return_value = MagicMock()
            transport._create_redis_client()
            call_kwargs = mock_redis_cls.from_url.call_args[1]
            assert "ssl_cert_reqs" in call_kwargs


class TestScheduleReconnect:
    @pytest.mark.unit
    def test_clears_redis_ready_event(self, transport: RedisTransport) -> None:
        transport._running = True
        transport._redis_ready.set()
        transport._reconnect_task = None
        with patch.object(transport, "task_registry", None):
            with patch("teleclaude.transport.redis_transport._connection.asyncio.create_task") as mock_ct:
                mock_ct.return_value = MagicMock(done=MagicMock(return_value=True))
                transport._schedule_reconnect("test-reason")
        assert not transport._redis_ready.is_set()

    @pytest.mark.unit
    def test_records_error_message(self, transport: RedisTransport) -> None:
        transport._running = True
        transport._reconnect_task = MagicMock(done=MagicMock(return_value=True))
        exc = ValueError("conn refused")
        with patch("teleclaude.transport.redis_transport._connection.asyncio.create_task") as mock_ct:
            mock_ct.return_value = MagicMock(done=MagicMock(return_value=True))
            transport.task_registry = None
            transport._schedule_reconnect("error-reason", error=exc)
        assert transport._redis_last_error == "conn refused"

    @pytest.mark.unit
    def test_does_nothing_when_not_running(self, transport: RedisTransport) -> None:
        transport._running = False
        transport._redis_ready.set()
        transport._schedule_reconnect("reason")
        # Event should still be set — not cleared when transport is stopped
        assert transport._redis_ready.is_set()
