"""Characterization tests for teleclaude.daemon_hook_outbox."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

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
        self._hook_outbox_stale_dropped_count = 0
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


def _make_outbox_row(
    event_type: str,
    age_seconds: float,
    row_id: int = 1,
    session_id: str = "sess-1",
) -> HookOutboxRow:
    created_at = (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat()
    return {
        "id": row_id,
        "session_id": session_id,
        "event_type": event_type,
        "payload": "{}",
        "created_at": created_at,
        "attempt_count": 0,
    }


def test_stale_user_prompt_submit_detected() -> None:
    row = _make_outbox_row("user_prompt_submit", age_seconds=400)
    assert daemon_hook_outbox._DaemonHookOutboxMixin._is_stale_outbox_row(row) is True


def test_staleness_just_under_ttl_is_not_stale() -> None:
    """One second under TTL (299s) should NOT be stale — the check is strictly greater-than."""
    row = _make_outbox_row("user_prompt_submit", age_seconds=299)
    assert daemon_hook_outbox._DaemonHookOutboxMixin._is_stale_outbox_row(row) is False


def test_staleness_one_second_past_ttl_is_stale() -> None:
    row = _make_outbox_row("user_prompt_submit", age_seconds=301)
    assert daemon_hook_outbox._DaemonHookOutboxMixin._is_stale_outbox_row(row) is True


def test_stale_lifecycle_events_are_all_exempt() -> None:
    """Every lifecycle event type in the exempt set survives staleness regardless of age."""
    for event_type in daemon_hook_outbox.HOOK_EVENT_STALENESS_EXEMPT:
        row = _make_outbox_row(event_type, age_seconds=600)
        assert daemon_hook_outbox._DaemonHookOutboxMixin._is_stale_outbox_row(row) is False, (
            f"{event_type} should be exempt from staleness"
        )


def test_stale_row_with_missing_created_at_is_not_stale() -> None:
    row: HookOutboxRow = {
        "id": 1,
        "session_id": "sess-1",
        "event_type": "user_prompt_submit",
        "payload": "{}",
        "created_at": None,
        "attempt_count": 0,
    }
    assert daemon_hook_outbox._DaemonHookOutboxMixin._is_stale_outbox_row(row) is False


def test_fresh_user_prompt_submit_not_stale() -> None:
    row = _make_outbox_row("user_prompt_submit", age_seconds=10)
    assert daemon_hook_outbox._DaemonHookOutboxMixin._is_stale_outbox_row(row) is False


@pytest.mark.unit
async def test_worker_passes_paused_sessions_to_db_fetch() -> None:
    """The worker must pass the paused-session snapshot to the DB query."""
    daemon_instance = _TestDaemon()
    daemon_instance.shutdown_event = asyncio.Event()
    daemon_instance._hook_outbox_claim_paused_sessions = {"paused-sess-A", "paused-sess-B"}

    captured_exclude: list[frozenset[str] | None] = []

    async def fake_fetch(
        now_iso: str,
        limit: int,
        lock_cutoff_iso: str,
        exclude_session_ids: frozenset[str] | None = None,
    ) -> list[HookOutboxRow]:
        captured_exclude.append(exclude_session_ids)
        # Return empty to end the iteration quickly.
        daemon_instance.shutdown_event.set()
        return []

    with patch("teleclaude.daemon_hook_outbox.db") as mock_db:
        mock_db.fetch_hook_outbox_batch = fake_fetch
        await daemon_instance._hook_outbox_worker()

    assert len(captured_exclude) == 1
    assert captured_exclude[0] == frozenset({"paused-sess-A", "paused-sess-B"})


@pytest.mark.unit
async def test_worker_drops_stale_rows_and_increments_counter() -> None:
    """Stale rows must be marked delivered with 'stale:{event_type}' and counted."""
    daemon_instance = _TestDaemon()
    daemon_instance.shutdown_event = asyncio.Event()

    stale_row = _make_outbox_row("user_prompt_submit", age_seconds=400, row_id=10, session_id="sess-flood")
    fresh_row = _make_outbox_row("session_start", age_seconds=2, row_id=20, session_id="sess-healthy")
    iteration_count = 0

    delivered_calls: list[tuple[int, str | None]] = []

    async def fake_fetch(
        now_iso: str,
        limit: int,
        lock_cutoff_iso: str,
        exclude_session_ids: frozenset[str] | None = None,
    ) -> list[HookOutboxRow]:
        nonlocal iteration_count
        iteration_count += 1
        if iteration_count == 1:
            return [stale_row, fresh_row]
        daemon_instance.shutdown_event.set()
        return []

    async def fake_mark_delivered(row_id: int, error: str | None = None) -> None:
        delivered_calls.append((row_id, error))

    async def fake_claim_batch(row_ids: list[int], now_iso: str, lock_cutoff_iso: str) -> set[int]:
        return set(row_ids)

    with patch("teleclaude.daemon_hook_outbox.db") as mock_db:
        mock_db.fetch_hook_outbox_batch = fake_fetch
        mock_db.mark_hook_outbox_delivered = fake_mark_delivered
        mock_db.claim_hook_outbox_batch = fake_claim_batch
        # Stub enqueue to avoid real session worker spawning.
        daemon_instance._enqueue_session_outbox_item = AsyncMock()
        await daemon_instance._hook_outbox_worker()

    assert (10, "stale:user_prompt_submit") in delivered_calls
    assert daemon_instance._hook_outbox_stale_dropped_count == 1


@pytest.mark.unit
async def test_ensure_headless_session_uses_resolved_caller_role() -> None:
    """_ensure_headless_session must pass resolve_cli_caller_role() result as human_role."""
    daemon_instance = _TestDaemon()
    fake_session = MagicMock()

    with (
        patch("teleclaude.daemon_hook_outbox.resolve_cli_caller_role", return_value="admin"),
        patch("teleclaude.daemon_hook_outbox.db") as mock_db,
        patch("teleclaude.daemon_hook_outbox.config"),
        patch("teleclaude.daemon_hook_outbox.event_bus"),
    ):
        mock_db.create_headless_session = AsyncMock(return_value=fake_session)
        result = await daemon_instance._ensure_headless_session("sess-headless", {})

    assert result is fake_session
    mock_db.create_headless_session.assert_called_once()
    _, kwargs = mock_db.create_headless_session.call_args
    assert kwargs["human_role"] == "admin"
