"""Characterization tests for teleclaude.adapters.ui.output_cadence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop
from teleclaude.core.models import Session

# ---------------------------------------------------------------------------
# Minimal fake adapter satisfying OutputCadenceLoop's interface
# ---------------------------------------------------------------------------


class _FakeAdapter:
    ADAPTER_KEY = "discord"

    def __init__(self) -> None:
        self.clear_turn_state = AsyncMock()
        self.send_threaded_output = AsyncMock(return_value="msg-1")


def _make_session(**kwargs: object) -> Session:
    return Session(
        session_id="sess-test",
        computer_name="local",
        tmux_session_name="test",
        title="Test",
        **kwargs,
    )


@pytest.fixture
def adapter() -> _FakeAdapter:
    return _FakeAdapter()


@pytest.fixture
def cadence_loop(adapter: _FakeAdapter) -> OutputCadenceLoop:
    return OutputCadenceLoop(adapter, interval_seconds=1.0)


# ---------------------------------------------------------------------------
# Tick filtering — sessions skipped before pull_session_output
# ---------------------------------------------------------------------------


class TestTickFiltering:
    @pytest.mark.unit
    async def test_skips_session_without_native_log_file(
        self, cadence_loop: OutputCadenceLoop, adapter: _FakeAdapter
    ) -> None:
        session = _make_session(active_agent="claude", native_log_file=None)
        with patch("teleclaude.adapters.ui.output_cadence.db") as mock_db:
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            await cadence_loop._tick()
        adapter.send_threaded_output.assert_not_called()

    @pytest.mark.unit
    async def test_skips_session_without_active_agent(
        self, cadence_loop: OutputCadenceLoop, adapter: _FakeAdapter
    ) -> None:
        session = _make_session(native_log_file="/tmp/log.jsonl", active_agent=None)
        with patch("teleclaude.adapters.ui.output_cadence.db") as mock_db:
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            await cadence_loop._tick()
        adapter.send_threaded_output.assert_not_called()

    @pytest.mark.unit
    async def test_skips_session_missing_both(self, cadence_loop: OutputCadenceLoop, adapter: _FakeAdapter) -> None:
        session = _make_session(native_log_file=None, active_agent=None)
        with patch("teleclaude.adapters.ui.output_cadence.db") as mock_db:
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            await cadence_loop._tick()
        adapter.send_threaded_output.assert_not_called()


# ---------------------------------------------------------------------------
# Per-session locking — skip when previous tick still rendering
# ---------------------------------------------------------------------------


class TestPerSessionLocking:
    @pytest.mark.unit
    async def test_skips_session_when_lock_held(self, cadence_loop: OutputCadenceLoop, adapter: _FakeAdapter) -> None:
        session = _make_session(native_log_file="/tmp/log.jsonl", active_agent="claude")
        lock = asyncio.Lock()
        cadence_loop._locks[session.session_id] = lock
        await lock.acquire()
        try:
            with patch("teleclaude.adapters.ui.output_cadence.db") as mock_db:
                mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
                await cadence_loop._tick()
        finally:
            lock.release()
        adapter.send_threaded_output.assert_not_called()


# ---------------------------------------------------------------------------
# Content-hash deduplication
# ---------------------------------------------------------------------------


class TestContentHashDedup:
    @pytest.mark.unit
    async def test_skips_send_when_digest_unchanged(
        self, cadence_loop: OutputCadenceLoop, adapter: _FakeAdapter
    ) -> None:
        message = "same content"
        digest = sha256(message.encode("utf-8")).hexdigest()
        session = _make_session(native_log_file="/tmp/log.jsonl", active_agent="claude")
        cadence_loop._render_digests[session.session_id] = digest

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
            patch("teleclaude.adapters.ui.output_cadence.get_assistant_messages_since", return_value=["msg"]),
            patch("teleclaude.adapters.ui.output_cadence.count_renderable_assistant_blocks", return_value=1),
            patch("teleclaude.adapters.ui.output_cadence.render_clean_agent_output", return_value=(message, None)),
            patch(
                "teleclaude.core.agent_coordinator._helpers._has_active_output_message",
                new=AsyncMock(return_value=False),
            ),
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            await cadence_loop._tick()

        adapter.send_threaded_output.assert_not_called()

    @pytest.mark.unit
    async def test_sends_when_digest_changes(self, cadence_loop: OutputCadenceLoop, adapter: _FakeAdapter) -> None:
        session = _make_session(native_log_file="/tmp/log.jsonl", active_agent="claude")
        new_message = "new content"
        cadence_loop._render_digests[session.session_id] = "stale-digest"

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
            patch("teleclaude.adapters.ui.output_cadence.get_assistant_messages_since", return_value=["msg"]),
            patch("teleclaude.adapters.ui.output_cadence.count_renderable_assistant_blocks", return_value=1),
            patch("teleclaude.adapters.ui.output_cadence.render_clean_agent_output", return_value=(new_message, None)),
            patch(
                "teleclaude.core.agent_coordinator._helpers._has_active_output_message",
                new=AsyncMock(return_value=False),
            ),
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            await cadence_loop._tick()

        adapter.send_threaded_output.assert_called_once()
        assert cadence_loop._render_digests[session.session_id] == sha256(new_message.encode()).hexdigest()

    @pytest.mark.unit
    async def test_skips_send_when_no_assistant_messages(
        self, cadence_loop: OutputCadenceLoop, adapter: _FakeAdapter
    ) -> None:
        session = _make_session(native_log_file="/tmp/log.jsonl", active_agent="claude")

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
            patch("teleclaude.adapters.ui.output_cadence.get_assistant_messages_since", return_value=[]),
            patch(
                "teleclaude.core.agent_coordinator._helpers._has_active_output_message",
                new=AsyncMock(return_value=False),
            ),
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            await cadence_loop._tick()

        adapter.send_threaded_output.assert_not_called()


# ---------------------------------------------------------------------------
# Turn break detection
# ---------------------------------------------------------------------------


class TestTurnBreakDetection:
    @pytest.mark.unit
    async def test_clears_turn_state_when_new_user_message_detected(
        self, cadence_loop: OutputCadenceLoop, adapter: _FakeAdapter
    ) -> None:
        session = _make_session(
            native_log_file="/tmp/log.jsonl",
            active_agent="claude",
            last_tool_done_at=None,
        )
        user_ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        fresh_session = _make_session(native_log_file="/tmp/log.jsonl", active_agent="claude")

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._helpers._has_active_output_message",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "teleclaude.adapters.ui.output_cadence.extract_last_user_message_with_timestamp",
                return_value=("user msg", user_ts),
            ),
            patch("teleclaude.adapters.ui.output_cadence.get_assistant_messages_since", return_value=[]),
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            mock_db.update_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=fresh_session)
            await cadence_loop._tick()

        adapter.clear_turn_state.assert_called_once_with(session)

    @pytest.mark.unit
    async def test_no_turn_break_when_user_message_not_newer_than_cursor(
        self, cadence_loop: OutputCadenceLoop, adapter: _FakeAdapter
    ) -> None:
        old_ts = datetime(2024, 1, 1, tzinfo=UTC)
        session = _make_session(
            native_log_file="/tmp/log.jsonl",
            active_agent="claude",
            last_tool_done_at=datetime(2024, 6, 1, tzinfo=UTC),
        )

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._helpers._has_active_output_message",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "teleclaude.adapters.ui.output_cadence.extract_last_user_message_with_timestamp",
                return_value=("user msg", old_ts),
            ),
            patch("teleclaude.adapters.ui.output_cadence.get_assistant_messages_since", return_value=[]),
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            await cadence_loop._tick()

        adapter.clear_turn_state.assert_not_called()


# ---------------------------------------------------------------------------
# Cursor update logic
# ---------------------------------------------------------------------------


class TestCursorUpdate:
    @pytest.mark.unit
    async def test_updates_cursor_when_no_active_output_message(
        self, cadence_loop: OutputCadenceLoop, adapter: _FakeAdapter
    ) -> None:
        session = _make_session(native_log_file="/tmp/log.jsonl", active_agent="claude")
        last_ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        fresh_session = _make_session(native_log_file="/tmp/log.jsonl", active_agent="claude")

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
            patch("teleclaude.adapters.ui.output_cadence.get_assistant_messages_since", return_value=["msg"]),
            patch("teleclaude.adapters.ui.output_cadence.count_renderable_assistant_blocks", return_value=1),
            patch("teleclaude.adapters.ui.output_cadence.render_clean_agent_output", return_value=("content", last_ts)),
            patch(
                "teleclaude.core.agent_coordinator._helpers._has_active_output_message",
                new=AsyncMock(return_value=False),
            ),
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            mock_db.get_session = AsyncMock(return_value=fresh_session)
            mock_db.update_session = AsyncMock()
            await cadence_loop._tick()

        mock_db.update_session.assert_called_once()
        _, call_kwargs = mock_db.update_session.call_args
        assert "last_tool_done_at" in call_kwargs
        assert call_kwargs["last_tool_done_at"] == last_ts.isoformat()

    @pytest.mark.unit
    async def test_skips_cursor_update_when_output_message_active(
        self, cadence_loop: OutputCadenceLoop, adapter: _FakeAdapter
    ) -> None:
        session = _make_session(native_log_file="/tmp/log.jsonl", active_agent="claude")
        last_ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        fresh_session = _make_session(native_log_file="/tmp/log.jsonl", active_agent="claude")

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
            patch("teleclaude.adapters.ui.output_cadence.get_assistant_messages_since", return_value=["msg"]),
            patch("teleclaude.adapters.ui.output_cadence.count_renderable_assistant_blocks", return_value=1),
            patch("teleclaude.adapters.ui.output_cadence.render_clean_agent_output", return_value=("content", last_ts)),
            patch(
                "teleclaude.adapters.ui.output_cadence.extract_last_user_message_with_timestamp",
                return_value=None,
            ),
            patch(
                "teleclaude.core.agent_coordinator._helpers._has_active_output_message",
                new=AsyncMock(return_value=True),
            ),
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            mock_db.get_session = AsyncMock(return_value=fresh_session)
            mock_db.update_session = AsyncMock()
            await cadence_loop._tick()

        mock_db.update_session.assert_not_called()

    @pytest.mark.unit
    async def test_skips_cursor_update_when_last_ts_is_none(
        self, cadence_loop: OutputCadenceLoop, adapter: _FakeAdapter
    ) -> None:
        session = _make_session(native_log_file="/tmp/log.jsonl", active_agent="claude")

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
            patch("teleclaude.adapters.ui.output_cadence.get_assistant_messages_since", return_value=["msg"]),
            patch("teleclaude.adapters.ui.output_cadence.count_renderable_assistant_blocks", return_value=1),
            patch("teleclaude.adapters.ui.output_cadence.render_clean_agent_output", return_value=("content", None)),
            patch(
                "teleclaude.core.agent_coordinator._helpers._has_active_output_message",
                new=AsyncMock(return_value=False),
            ),
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            mock_db.update_session = AsyncMock()
            await cadence_loop._tick()

        mock_db.update_session.assert_not_called()
