"""Characterization tests for teleclaude.daemon_hook_outbox."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import teleclaude.daemon_hook_outbox as daemon_hook_outbox
from teleclaude.core.db import HookOutboxRow
from teleclaude.core.events import AgentEventContext
from teleclaude.core.hook_outbox_queue import HookOutboxQueueItem, HookOutboxSessionQueue
from teleclaude.core.models import Session
from teleclaude.transport.redis_transport import RedisTransport


class _FakeRedisTransport(RedisTransport):  # pylint: disable=too-many-ancestors
    """Marker subclass used for isinstance checks."""


class _TestDaemon(daemon_hook_outbox._DaemonHookOutboxMixin):
    def __init__(self) -> None:
        self.shutdown_event = None  # pyright: ignore[reportAttributeAccessIssue]
        self._background_tasks = set()
        self._session_outbox_queues: dict[str, HookOutboxSessionQueue] = {}
        self._session_outbox_workers = {}
        self._hook_outbox_processed_count = 0
        self._hook_outbox_coalesced_count = 0
        self._hook_outbox_stale_dropped_count = 0
        self._hook_outbox_lag_samples_s: list[float] = []
        self._hook_outbox_last_summary_at = 0.0
        self._hook_outbox_last_backlog_warn_at: dict[str, float] = {}
        self._hook_outbox_last_lag_warn_at: dict[str, float] = {}
        self._hook_outbox_claim_paused_sessions: set[str] = set()
        self.cache = None  # pyright: ignore[reportAttributeAccessIssue]

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


def _queue_item(row_id: int, event_type: str, classification: str) -> HookOutboxQueueItem:
    return HookOutboxQueueItem(
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

    adapter.request_refresh = request_refresh  # pyright: ignore[reportAttributeAccessIssue]
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
    queue_state = HookOutboxSessionQueue()
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
        _now_iso: str,
        _limit: int,
        _lock_cutoff_iso: str,
        exclude_session_ids: frozenset[str] | None = None,
    ) -> list[HookOutboxRow]:
        captured_exclude.append(exclude_session_ids)
        # Return empty to end the iteration quickly.
        daemon_instance.shutdown_event.set()
        return []

    with (
        patch("teleclaude.daemon_hook_outbox.db") as mock_db,
        patch("teleclaude.daemon_hook_outbox.HOOK_OUTBOX_POLL_INTERVAL_S", 0),
    ):
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

    deleted_row_ids: list[int] = []

    async def fake_fetch(  # pylint: disable=unused-argument
        _now_iso: str,
        _limit: int,
        _lock_cutoff_iso: str,
        exclude_session_ids: frozenset[str] | None = None,
    ) -> list[HookOutboxRow]:
        nonlocal iteration_count
        iteration_count += 1
        if iteration_count == 1:
            return [stale_row, fresh_row]
        daemon_instance.shutdown_event.set()
        return []

    async def fake_delete(row_id: int) -> None:
        deleted_row_ids.append(row_id)

    async def fake_claim_batch(row_ids: list[int], _now_iso: str, _lock_cutoff_iso: str) -> set[int]:
        return set(row_ids)

    with (
        patch("teleclaude.daemon_hook_outbox.db") as mock_db,
        patch("teleclaude.daemon_hook_outbox.HOOK_OUTBOX_POLL_INTERVAL_S", 0),
    ):
        mock_db.fetch_hook_outbox_batch = fake_fetch
        mock_db.delete_hook_outbox_row = fake_delete
        mock_db.claim_hook_outbox_batch = fake_claim_batch
        # Stub enqueue to avoid real session worker spawning.
        daemon_instance._enqueue_session_outbox_item = AsyncMock()
        await daemon_instance._hook_outbox_worker()

    assert 10 in deleted_row_ids
    assert daemon_instance._hook_outbox_stale_dropped_count == 1


@pytest.mark.unit
async def test_dispatch_hook_event_drops_codex_subagent_agent_stop() -> None:
    daemon_instance = _TestDaemon()
    daemon_instance.shutdown_event = asyncio.Event()
    session = SimpleNamespace(tmux_session_name="tcx", lifecycle_status="open", active_agent="codex")
    trace_calls: list[tuple[str, dict[str, str]]] = []

    def _trace(message: str, **kwargs: str) -> None:
        trace_calls.append((message, kwargs))

    with (
        patch("teleclaude.daemon_hook_outbox.db") as mock_db,
        patch("teleclaude.daemon_hook_outbox.is_codex_subagent_transcript", return_value=True),
        patch("teleclaude.daemon_hook_outbox.logger.trace", side_effect=_trace),
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock()
        daemon_instance._handle_agent_event = AsyncMock()
        daemon_instance._ensure_output_polling = AsyncMock()

        await daemon_instance._dispatch_hook_event(
            "sess-drop",
            daemon_hook_outbox.AgentHookEvents.AGENT_STOP,
            {"agent_name": "codex", "transcript_path": "/tmp/child-rollout-c3.jsonl"},
        )

    assert not daemon_instance._handle_agent_event.called
    assert not mock_db.update_session.called
    assert any("Dropping Codex subagent agent_stop notification" in message for message, _ in trace_calls)


@pytest.mark.unit
async def test_dispatch_hook_event_processes_codex_non_subagent_agent_stop() -> None:
    daemon_instance = _TestDaemon()
    daemon_instance.shutdown_event = asyncio.Event()
    session = SimpleNamespace(tmux_session_name=None, lifecycle_status="open", active_agent="codex")

    with (
        patch("teleclaude.daemon_hook_outbox.db") as mock_db,
        patch("teleclaude.daemon_hook_outbox.is_codex_subagent_transcript", return_value=False),
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock()
        daemon_instance._handle_agent_event = AsyncMock()
        daemon_instance._ensure_output_polling = AsyncMock()

        await daemon_instance._dispatch_hook_event(
            "sess-keep",
            daemon_hook_outbox.AgentHookEvents.AGENT_STOP,
            {"agent_name": "codex", "transcript_path": "/tmp/parent-rollout-c3.jsonl"},
        )

    assert daemon_instance._handle_agent_event.called
    assert daemon_instance._handle_agent_event.call_count == 1
