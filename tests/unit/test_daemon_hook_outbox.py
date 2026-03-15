"""Characterization tests for teleclaude.daemon_hook_outbox."""

from __future__ import annotations

from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta

import pytest

import teleclaude.daemon_hook_outbox as daemon_hook_outbox
from teleclaude.core.db import HookOutboxRow
from teleclaude.core.events import AgentEventContext
from teleclaude.core.models import Session
from teleclaude.transport.redis_transport import RedisTransport


class _FakeRedisTransport(RedisTransport):
    """Marker subclass used for isinstance checks."""


class _TestDaemon(daemon_hook_outbox._DaemonHookOutboxMixin):
    def __init__(self) -> None:
        self.shutdown_event = None
        self._background_tasks = set()
        self._session_outbox_queues: dict[str, daemon_hook_outbox._HookOutboxSessionQueue] = {}
        self._session_outbox_workers = {}
        self._hook_outbox_processed_count = 0
        self._hook_outbox_coalesced_count = 0
        self._hook_outbox_lag_samples_s: list[float] = []
        self._hook_outbox_last_summary_at = 0.0
        self._hook_outbox_last_backlog_warn_at: dict[str, float] = {}
        self._hook_outbox_last_lag_warn_at: dict[str, float] = {}
        self._hook_outbox_claim_paused_sessions: set[str] = set()
        self.cache = None

    def _queue_background_task(
        self,
        coro: Coroutine[object, object, object],
        label: str,
    ) -> None:  # pragma: no cover - unused in these tests
        raise NotImplementedError

    async def _handle_agent_event(
        self,
        _event: str,
        context: AgentEventContext,
    ) -> None:  # pragma: no cover - unused in these tests
        raise NotImplementedError

    async def _ensure_output_polling(self, session: Session) -> None:  # pragma: no cover - unused in these tests
        raise NotImplementedError


def _queue_item(row_id: int, event_type: str, classification: str) -> daemon_hook_outbox._HookOutboxQueueItem:
    return daemon_hook_outbox._HookOutboxQueueItem(
        row={
            "id": row_id,
            "session_id": "sess-1",
            "event_type": event_type,
            "payload": "{}",
            "created_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            "attempt_count": 0,
        },
        event_type=event_type,
        classification=classification,
    )


def test_make_stale_read_callback_requests_refresh_only_for_remote_redis() -> None:
    refresh_calls: list[tuple[str, str, str]] = []
    adapter = object.__new__(_FakeRedisTransport)

    def request_refresh(computer: str, resource_type: str, reason: str) -> None:
        refresh_calls.append((computer, resource_type, reason))

    adapter.request_refresh = request_refresh
    callback = daemon_hook_outbox._DaemonHookOutboxMixin._make_stale_read_callback(
        local_computer_name="workstation",
        get_adapter=lambda: adapter,
    )

    callback("sessions", "local")
    callback("sessions", "workstation")
    callback("sessions", "")
    callback("sessions", "remote-box")

    assert refresh_calls == [("remote-box", "sessions", "ttl")]


def test_enqueue_bursty_item_replaces_latest_matching_item_after_critical_boundary() -> None:
    daemon_instance = _TestDaemon()
    pending = [
        _queue_item(1, daemon_hook_outbox.AgentHookEvents.TOOL_USE, "bursty"),
        _queue_item(2, daemon_hook_outbox.AgentHookEvents.AGENT_STOP, "critical"),
        _queue_item(3, daemon_hook_outbox.AgentHookEvents.TOOL_USE, "bursty"),
    ]
    claimed_row_ids = {1, 2, 3}
    replacement = _queue_item(4, daemon_hook_outbox.AgentHookEvents.TOOL_USE, "bursty")
    dropped_rows: list[HookOutboxRow] = []

    enqueued = daemon_instance._enqueue_bursty_item(
        pending,
        claimed_row_ids,
        replacement,
        replacement.row,
        4,
        daemon_hook_outbox.AgentHookEvents.TOOL_USE,
        dropped_rows,
    )

    assert enqueued is True
    assert [int(item.row["id"]) for item in pending] == [1, 2, 4]
    assert [int(row["id"]) for row in dropped_rows] == [3]
    assert claimed_row_ids == {1, 2, 4}


@pytest.mark.unit
async def test_should_pause_hook_outbox_claims_uses_watermark_hysteresis() -> None:
    daemon_instance = _TestDaemon()
    session_id = "sess-1"
    queue_state = daemon_hook_outbox._HookOutboxSessionQueue()
    queue_state.pending = [
        _queue_item(index, daemon_hook_outbox.AgentHookEvents.TOOL_USE, "bursty")
        for index in range(daemon_hook_outbox.HOOK_OUTBOX_SESSION_CLAIM_HIGH_WATERMARK)
    ]
    daemon_instance._session_outbox_queues[session_id] = queue_state

    assert await daemon_instance._should_pause_hook_outbox_claims(session_id) is True
    assert session_id in daemon_instance._hook_outbox_claim_paused_sessions

    queue_state.pending = [
        _queue_item(index, daemon_hook_outbox.AgentHookEvents.TOOL_USE, "bursty")
        for index in range(daemon_hook_outbox.HOOK_OUTBOX_SESSION_CLAIM_LOW_WATERMARK)
    ]

    assert await daemon_instance._should_pause_hook_outbox_claims(session_id) is False
    assert session_id not in daemon_instance._hook_outbox_claim_paused_sessions
