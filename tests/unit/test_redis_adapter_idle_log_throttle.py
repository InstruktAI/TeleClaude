from __future__ import annotations

from unittest.mock import MagicMock

from teleclaude.adapters.redis_adapter import RedisAdapter


def test_idle_poll_log_is_throttled_to_once_per_minute(monkeypatch):
    adapter = RedisAdapter(adapter_client=MagicMock())

    debug_mock = MagicMock()
    monkeypatch.setattr("teleclaude.adapters.redis_adapter.logger.debug", debug_mock)

    adapter._reset_idle_poll_log_throttle()

    adapter._maybe_log_idle_poll(message_stream="messages:test", now=0.0)
    adapter._maybe_log_idle_poll(message_stream="messages:test", now=30.0)
    adapter._maybe_log_idle_poll(message_stream="messages:test", now=59.0)
    assert debug_mock.call_count == 0

    adapter._maybe_log_idle_poll(message_stream="messages:test", now=60.0)
    assert debug_mock.call_count == 1
    _, kwargs = debug_mock.call_args
    assert kwargs["stream"] == "messages:test"
    assert kwargs["suppressed"] == 4
    assert kwargs["interval_s"] == 60

    # Next minute window
    adapter._maybe_log_idle_poll(message_stream="messages:test", now=119.0)
    assert debug_mock.call_count == 1
    adapter._maybe_log_idle_poll(message_stream="messages:test", now=120.0)
    assert debug_mock.call_count == 2
