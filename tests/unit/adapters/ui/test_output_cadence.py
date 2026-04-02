"""Characterization tests for teleclaude.adapters.ui.output_cadence."""
# pylint: disable=protected-access,redefined-outer-name,missing-class-docstring,missing-function-docstring,too-few-public-methods,unused-argument,import-outside-toplevel

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop, _find_last_genuine_user_boundary
from teleclaude.core.agents import AgentName
from teleclaude.core.models import JsonDict, Session

# ---------------------------------------------------------------------------
# Minimal fake adapter satisfying OutputCadenceLoop's interface
# ---------------------------------------------------------------------------


class _FakeAdapter:
    ADAPTER_KEY = "discord"

    def __init__(self) -> None:
        self.clear_turn_state = AsyncMock()
        self.send_threaded_output = AsyncMock(return_value="msg-1")
        self.ensure_channel = AsyncMock(side_effect=lambda session: session)  # pyright: ignore[reportUnknownLambdaType]
        self.send_message = AsyncMock(return_value="reflected-msg")
        self._clear_output_message_id = AsyncMock()
        self.set_last_delivered_at = AsyncMock()

    def get_last_delivered_at(self, session: Session) -> datetime | None:
        from teleclaude.utils.transcript._utils import _parse_timestamp

        raw = session.get_origin_section(self.ADAPTER_KEY).get("last_delivered_at")
        if isinstance(raw, str):
            return _parse_timestamp(raw)
        return None


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
# _find_last_genuine_user_boundary — direct unit tests
# ---------------------------------------------------------------------------


class TestFindLastGenuineUserBoundary:
    @pytest.mark.unit
    def test_empty_list_returns_zero(self) -> None:
        assert _find_last_genuine_user_boundary([]) == 0

    @pytest.mark.unit
    def test_no_user_messages_returns_zero(self) -> None:
        entries = [
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}},
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "bye"}]}},
        ]
        assert _find_last_genuine_user_boundary(entries) == 0

    @pytest.mark.unit
    def test_returns_index_of_last_genuine_user_message(self) -> None:
        entries = [
            {"message": {"role": "user", "content": [{"type": "text", "text": "first"}]}},
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "reply"}]}},
            {"message": {"role": "user", "content": [{"type": "text", "text": "second"}]}},
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}},
        ]
        assert _find_last_genuine_user_boundary(entries) == 2

    @pytest.mark.unit
    def test_skips_tool_result_only_entries(self) -> None:
        entries = [
            {"message": {"role": "user", "content": [{"type": "text", "text": "real"}]}},
            {"message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]}},
        ]
        # Scans backwards: index 1 is tool-result-only (skipped), index 0 is genuine.
        assert _find_last_genuine_user_boundary(entries) == 0

    @pytest.mark.unit
    def test_only_tool_result_user_messages_returns_zero(self) -> None:
        entries = [
            {"message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]}},
        ]
        assert _find_last_genuine_user_boundary(entries) == 0


# ---------------------------------------------------------------------------
# _detect_turn_boundary — direct unit tests
# ---------------------------------------------------------------------------


def _write_transcript(path: Path, entries: list[JsonDict]) -> str:
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return str(path)


class TestDetectTurnBoundary:
    @pytest.mark.unit
    def test_no_transcript_file_returns_false(self, cadence_loop: OutputCadenceLoop) -> None:
        session = _make_session(native_log_file="/nonexistent/path.jsonl", active_agent="claude")
        result = cadence_loop._detect_turn_boundary(session, "/nonexistent/path.jsonl", AgentName.CLAUDE)
        assert result is False

    @pytest.mark.unit
    def test_no_genuine_user_message_returns_false(self, cadence_loop: OutputCadenceLoop, tmp_path: Path) -> None:
        transcript = _write_transcript(
            tmp_path / "no_user.jsonl",
            [
                {
                    "timestamp": "2024-06-01T10:00:00+00:00",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
                }
            ],
        )
        session = _make_session(native_log_file=transcript, active_agent="claude")
        assert cadence_loop._detect_turn_boundary(session, transcript, AgentName.CLAUDE) is False

    @pytest.mark.unit
    def test_first_call_returns_true_on_genuine_user_message(
        self, cadence_loop: OutputCadenceLoop, tmp_path: Path
    ) -> None:
        transcript = _write_transcript(
            tmp_path / "with_user.jsonl",
            [
                {
                    "timestamp": "2024-06-01T10:00:00+00:00",
                    "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]},
                }
            ],
        )
        session = _make_session(native_log_file=transcript, active_agent="claude")
        assert cadence_loop._detect_turn_boundary(session, transcript, AgentName.CLAUDE) is True

    @pytest.mark.unit
    def test_repeated_call_with_same_timestamp_returns_false(
        self, cadence_loop: OutputCadenceLoop, tmp_path: Path
    ) -> None:
        entries = [
            {
                "timestamp": "2024-06-01T10:00:00+00:00",
                "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]},
            }
        ]
        transcript = _write_transcript(tmp_path / "repeat.jsonl", entries)
        session = _make_session(native_log_file=transcript, active_agent="claude")

        assert cadence_loop._detect_turn_boundary(session, transcript, AgentName.CLAUDE) is True
        assert cadence_loop._detect_turn_boundary(session, transcript, AgentName.CLAUDE) is False

    @pytest.mark.unit
    def test_new_user_message_advances_boundary(self, cadence_loop: OutputCadenceLoop, tmp_path: Path) -> None:
        transcript_path = tmp_path / "new_turn.jsonl"
        entries_v1 = [
            {
                "timestamp": "2024-06-01T10:00:00+00:00",
                "message": {"role": "user", "content": [{"type": "text", "text": "first"}]},
            }
        ]
        transcript = _write_transcript(transcript_path, entries_v1)
        session = _make_session(native_log_file=transcript, active_agent="claude")

        cadence_loop._detect_turn_boundary(session, transcript, AgentName.CLAUDE)  # consume first turn

        entries_v2 = entries_v1 + [
            {
                "timestamp": "2024-06-01T11:00:00+00:00",
                "message": {"role": "user", "content": [{"type": "text", "text": "second"}]},
            }
        ]
        transcript = _write_transcript(transcript_path, entries_v2)
        assert cadence_loop._detect_turn_boundary(session, transcript, AgentName.CLAUDE) is True

    @pytest.mark.unit
    def test_missing_timestamp_first_call_returns_true(self, cadence_loop: OutputCadenceLoop, tmp_path: Path) -> None:
        """F1: genuine user message with absent timestamp must trigger boundary on first call."""
        transcript = _write_transcript(
            tmp_path / "no_ts.jsonl",
            [{"message": {"role": "user", "content": [{"type": "text", "text": "no timestamp"}]}}],
        )
        session = _make_session(native_log_file=transcript, active_agent="claude")
        assert cadence_loop._detect_turn_boundary(session, transcript, AgentName.CLAUDE) is True

    @pytest.mark.unit
    def test_missing_timestamp_second_call_returns_false(self, cadence_loop: OutputCadenceLoop, tmp_path: Path) -> None:
        """F1: repeated calls with same absent-timestamp message must not re-fire boundary."""
        transcript = _write_transcript(
            tmp_path / "no_ts_repeat.jsonl",
            [{"message": {"role": "user", "content": [{"type": "text", "text": "no timestamp"}]}}],
        )
        session = _make_session(native_log_file=transcript, active_agent="claude")

        assert cadence_loop._detect_turn_boundary(session, transcript, AgentName.CLAUDE) is True
        assert cadence_loop._detect_turn_boundary(session, transcript, AgentName.CLAUDE) is False


# ---------------------------------------------------------------------------
# _build_reflection_belt — direct unit tests
# ---------------------------------------------------------------------------


class TestBuildReflectionBelt:
    @pytest.mark.unit
    def test_empty_transcript_returns_none(self, cadence_loop: OutputCadenceLoop, tmp_path: Path) -> None:
        transcript = str(tmp_path / "empty.jsonl")
        Path(transcript).write_text("", encoding="utf-8")
        session = _make_session(native_log_file=transcript, active_agent="claude")

        result, ts = cadence_loop._build_reflection_belt(session, transcript, AgentName.CLAUDE)
        assert result is None
        assert ts is None

    @pytest.mark.unit
    def test_includes_user_and_assistant_messages(self, cadence_loop: OutputCadenceLoop, tmp_path: Path) -> None:
        transcript = _write_transcript(
            tmp_path / "belt.jsonl",
            [
                {
                    "timestamp": "2024-06-01T10:00:00+00:00",
                    "message": {"role": "user", "content": [{"type": "text", "text": "hello user"}]},
                },
                {
                    "timestamp": "2024-06-01T10:00:01+00:00",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "hello assistant"}]},
                },
            ],
        )
        session = _make_session(native_log_file=transcript, active_agent="claude")

        mock_identity = MagicMock()
        mock_identity.display_name = "TestUser"
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = mock_identity

        with patch("teleclaude.adapters.ui.output_cadence.get_identity_resolver", return_value=mock_resolver):
            result, _ = cadence_loop._build_reflection_belt(session, transcript, AgentName.CLAUDE)

        assert result is not None
        assert "hello user" in result
        assert "hello assistant" in result

    @pytest.mark.unit
    def test_uses_resolved_display_name(self, cadence_loop: OutputCadenceLoop, tmp_path: Path) -> None:
        transcript = _write_transcript(
            tmp_path / "display.jsonl",
            [{"message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}}],
        )
        session = _make_session(native_log_file=transcript, active_agent="claude")

        mock_identity = MagicMock()
        mock_identity.display_name = "Maurice"
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = mock_identity

        with patch("teleclaude.adapters.ui.output_cadence.get_identity_resolver", return_value=mock_resolver):
            result, _ = cadence_loop._build_reflection_belt(session, transcript, AgentName.CLAUDE)

        assert result is not None
        assert "Maurice" in result

    @pytest.mark.unit
    def test_display_name_valueerror_falls_back_to_input_origin(
        self, cadence_loop: OutputCadenceLoop, tmp_path: Path
    ) -> None:
        transcript = _write_transcript(
            tmp_path / "fallback.jsonl",
            [{"message": {"role": "user", "content": [{"type": "text", "text": "test"}]}}],
        )
        session = _make_session(native_log_file=transcript, active_agent="claude", last_input_origin="telegram")

        mock_identity = MagicMock()
        type(mock_identity).display_name = PropertyMock(side_effect=ValueError("no display name"))
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = mock_identity

        with patch("teleclaude.adapters.ui.output_cadence.get_identity_resolver", return_value=mock_resolver):
            result, _ = cadence_loop._build_reflection_belt(session, transcript, AgentName.CLAUDE)

        assert result is not None
        assert "telegram" in result
