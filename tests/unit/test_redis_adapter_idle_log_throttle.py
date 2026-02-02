"""Unit tests for Redis adapter idle poll log throttling."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.transport.redis_transport import RedisTransport


def test_idle_poll_log_is_throttled_to_once_per_minute(monkeypatch):
    """Test that idle poll logging is suppressed until the throttle window elapses."""
    adapter = RedisTransport(adapter_client=MagicMock())

    calls = []

    def record_trace(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr("teleclaude.transport.redis_transport.logger.trace", record_trace)

    adapter._reset_idle_poll_log_throttle()

    adapter._maybe_log_idle_poll(message_stream="messages:test", now=0.0)
    adapter._maybe_log_idle_poll(message_stream="messages:test", now=30.0)
    adapter._maybe_log_idle_poll(message_stream="messages:test", now=59.0)
    assert calls == []

    adapter._maybe_log_idle_poll(message_stream="messages:test", now=60.0)
    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs["stream"] == "messages:test"
    assert kwargs["suppressed"] == 4
    assert kwargs["interval_s"] == 60

    # Next minute window
    adapter._maybe_log_idle_poll(message_stream="messages:test", now=119.0)
    assert len(calls) == 1
    adapter._maybe_log_idle_poll(message_stream="messages:test", now=120.0)
    assert len(calls) == 2
