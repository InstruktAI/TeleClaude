"""Characterization tests for teleclaude.core.agent_coordinator._fanout."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.agent_coordinator._fanout import _FanoutMixin
from teleclaude.core.models import Session


def _make_fanout() -> _FanoutMixin:
    """Create a minimal _FanoutMixin instance with required service attrs."""
    mixin = object.__new__(_FanoutMixin)
    mixin.client = MagicMock()
    mixin.tts_manager = MagicMock()
    mixin.headless_snapshot_service = MagicMock()
    return mixin


def _make_session(**kwargs: object) -> Session:
    defaults: dict[str, object] = {  # guard: loose-dict - Session factory accepts varied field types
        "session_id": "sess-001",
        "computer_name": "local",
        "tmux_session_name": "test",
        "title": "Test Session",
    }
    defaults.update(kwargs)
    return Session(**defaults)


class TestSummarizeOutput:
    @pytest.mark.unit
    async def test_empty_raw_output_returns_none(self):
        mixin = _make_fanout()
        result = await mixin._summarize_output("sess-001", "   ")
        assert result is None

    @pytest.mark.unit
    async def test_summarize_exception_returns_none(self):
        mixin = _make_fanout()
        with patch(
            "teleclaude.core.agent_coordinator._fanout.summarize_agent_output",
            side_effect=RuntimeError("summarizer down"),
        ):
            result = await mixin._summarize_output("sess-001", "some output text")
        assert result is None

    @pytest.mark.unit
    async def test_valid_output_returns_summary(self):
        mixin = _make_fanout()
        with patch(
            "teleclaude.core.agent_coordinator._fanout.summarize_agent_output",
            new_callable=AsyncMock,
            return_value=("title", "summary text"),
        ):
            result = await mixin._summarize_output("sess-001", "some agent output")
        assert result == "summary text"


class TestExtractUserInputForCodex:
    @pytest.mark.unit
    async def test_no_session_returns_none(self):
        mixin = _make_fanout()
        mock_payload = MagicMock()
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            result = await mixin._extract_user_input_for_codex("sess-001", mock_payload)
        assert result is None

    @pytest.mark.unit
    async def test_non_codex_agent_returns_none(self):
        mixin = _make_fanout()
        session = _make_session(active_agent="claude")
        mock_payload = MagicMock()
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            result = await mixin._extract_user_input_for_codex("sess-001", mock_payload)
        assert result is None

    @pytest.mark.unit
    async def test_codex_without_transcript_returns_none(self):
        mixin = _make_fanout()
        session = _make_session(active_agent="codex", native_log_file=None)
        mock_payload = MagicMock()
        mock_payload.transcript_path = None
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            result = await mixin._extract_user_input_for_codex("sess-001", mock_payload)
        assert result is None


class TestMaybeSendHeadlessSnapshot:
    @pytest.mark.unit
    async def test_no_session_returns_early(self):
        mixin = _make_fanout()
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            await mixin._maybe_send_headless_snapshot("sess-001")
        mixin.headless_snapshot_service.send_snapshot.assert_not_called()  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    async def test_non_headless_session_returns_early(self):
        mixin = _make_fanout()
        session = _make_session(lifecycle_status="active")
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            await mixin._maybe_send_headless_snapshot("sess-001")
        mixin.headless_snapshot_service.send_snapshot.assert_not_called()  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    async def test_headless_without_agent_skips_snapshot(self):
        mixin = _make_fanout()
        session = _make_session(lifecycle_status="headless", active_agent=None)
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            await mixin._maybe_send_headless_snapshot("sess-001")
        mixin.headless_snapshot_service.send_snapshot.assert_not_called()  # pyright: ignore[reportAttributeAccessIssue]


class TestFanoutLinkedStopOutput:
    @pytest.mark.unit
    async def test_no_links_returns_zero(self):
        mixin = _make_fanout()
        with patch(
            "teleclaude.core.agent_coordinator._fanout.get_active_links_for_session",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await mixin._fanout_linked_stop_output("sess-001", "some output")
        assert result == 0


class TestNotifySessionListener:
    @pytest.mark.unit
    async def test_already_notified_skips_notification(self):
        mixin = _make_fanout()
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_notification_flag = AsyncMock(return_value=True)
            await mixin._notify_session_listener("sess-001")
        mock_db.set_notification_flag.assert_not_called()  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    async def test_not_notified_calls_notify_stop(self):
        mixin = _make_fanout()
        session = _make_session(title="My Session")
        with (
            patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._fanout.notify_stop",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            mock_db.get_notification_flag = AsyncMock(return_value=False)
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.set_notification_flag = AsyncMock()
            await mixin._notify_session_listener("sess-001")
        mock_db.set_notification_flag.assert_called_once_with("sess-001", True)


class TestSpeakSessionStart:
    @pytest.mark.unit
    async def test_no_messages_skips_tts(self):
        mixin = _make_fanout()
        with patch("teleclaude.core.agent_coordinator._fanout.SESSION_START_MESSAGES", []):
            await mixin._speak_session_start("sess-001")
        mixin.tts_manager.speak.assert_not_called()  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    async def test_tts_called_with_one_of_the_messages(self):
        mixin = _make_fanout()
        mixin.tts_manager.speak = AsyncMock()
        messages = ["Hello!", "Ready to work!"]
        with patch("teleclaude.core.agent_coordinator._fanout.SESSION_START_MESSAGES", messages):
            await mixin._speak_session_start("sess-001")
        call_args = mixin.tts_manager.speak.call_args
        assert call_args is not None
        spoken_message = call_args[0][0]
        assert spoken_message in messages

    @pytest.mark.unit
    async def test_tts_exception_does_not_propagate(self):
        mixin = _make_fanout()
        mixin.tts_manager.speak = AsyncMock(side_effect=RuntimeError("tts error"))
        with patch("teleclaude.core.agent_coordinator._fanout.SESSION_START_MESSAGES", ["Hi!"]):
            await mixin._speak_session_start("sess-001")


class TestUpdateSessionTitleAsync:
    @pytest.mark.unit
    async def test_no_session_returns_early(self):
        mixin = _make_fanout()
        now = datetime.now(UTC)
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            await mixin._update_session_title_async("sess-001", now, "some prompt")
        mock_db.update_session.assert_not_called()  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    async def test_timestamp_mismatch_returns_early(self):
        mixin = _make_fanout()
        expected_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        different_at = datetime(2024, 1, 1, 13, 0, 0, tzinfo=UTC)
        session = _make_session(last_message_sent_at=different_at)
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            await mixin._update_session_title_async("sess-001", expected_at, "some prompt")
        mock_db.update_session.assert_not_called()  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    async def test_slash_command_title_not_overwritten(self):
        mixin = _make_fanout()
        now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        session = _make_session(title="/my-command", last_message_sent_at=now)
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            await mixin._update_session_title_async("sess-001", now, "some prompt")
        mock_db.update_session.assert_not_called()  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    async def test_untitled_session_with_slash_command_sets_slash_title(self):
        mixin = _make_fanout()
        now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        session = _make_session(title="Untitled session", last_message_sent_at=now)
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            await mixin._update_session_title_async("sess-001", now, "/next-build my-slug")
        mock_db.update_session.assert_called_once()  # pyright: ignore[reportAttributeAccessIssue]
        call_kwargs = mock_db.update_session.call_args[1]
        assert call_kwargs["title"] == "/next-build my-slug"

    @pytest.mark.unit
    async def test_generates_title_from_transcript(self):
        mixin = _make_fanout()
        now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        session = _make_session(
            title="Some title",
            last_message_sent_at=now,
            active_agent="claude",
            native_log_file="/path/to/transcript.json",
        )
        with (
            patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._fanout.extract_recent_transcript_turns",
                return_value=["turn1"],
            ),
            patch(
                "teleclaude.core.agent_coordinator._fanout.generate_session_title",
                new_callable=AsyncMock,
                return_value="Generated Title",
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            await mixin._update_session_title_async("sess-001", now, "regular prompt")
        mock_db.update_session.assert_called()  # pyright: ignore[reportAttributeAccessIssue]
        call_kwargs = mock_db.update_session.call_args[1]
        assert call_kwargs["title"] == "Generated Title"


class TestExtractAgentOutput:
    @pytest.mark.unit
    async def test_no_transcript_path_returns_none(self):
        mixin = _make_fanout()
        session = _make_session(native_log_file=None)
        payload = MagicMock()
        payload.transcript_path = None
        payload.raw = {}
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            result = await mixin._extract_agent_output("sess-001", payload)
        assert result is None

    @pytest.mark.unit
    async def test_unknown_agent_name_returns_none(self):
        mixin = _make_fanout()
        session = _make_session(active_agent=None)
        payload = MagicMock()
        payload.transcript_path = "/path/to/transcript"
        payload.raw = {"agent_name": "unknown_agent_xyz"}
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            result = await mixin._extract_agent_output("sess-001", payload)
        assert result is None

    @pytest.mark.unit
    async def test_no_agent_name_returns_none(self):
        mixin = _make_fanout()
        session = _make_session(active_agent=None)
        payload = MagicMock()
        payload.transcript_path = "/path/to/transcript"
        payload.raw = {}
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            result = await mixin._extract_agent_output("sess-001", payload)
        assert result is None

    @pytest.mark.unit
    async def test_returns_last_agent_message_on_success(self):
        mixin = _make_fanout()
        session = _make_session(active_agent="claude")
        payload = MagicMock()
        payload.transcript_path = "/path/to/transcript"
        payload.raw = {"agent_name": "claude"}
        with (
            patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._fanout.extract_last_agent_message",
                return_value="Agent said this.",
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            result = await mixin._extract_agent_output("sess-001", payload)
        assert result == "Agent said this."

    @pytest.mark.unit
    async def test_empty_last_message_returns_none(self):
        mixin = _make_fanout()
        session = _make_session(active_agent="claude")
        payload = MagicMock()
        payload.transcript_path = "/path/to/transcript"
        payload.raw = {"agent_name": "claude"}
        with (
            patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._fanout.extract_last_agent_message",
                return_value="   ",
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            result = await mixin._extract_agent_output("sess-001", payload)
        assert result is None


class TestForwardStopToInitiator:
    @pytest.mark.unit
    async def test_no_session_returns_early(self):
        mixin = _make_fanout()
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            await mixin._forward_stop_to_initiator("sess-001")
        mixin.client.send_request.assert_not_called()  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    async def test_no_target_computer_returns_early(self):
        mixin = _make_fanout()
        session = MagicMock()
        session.get_metadata.return_value.get_transport.return_value.get_redis.return_value.target_computer = None
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            await mixin._forward_stop_to_initiator("sess-001")
        mixin.client.send_request.assert_not_called()  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    async def test_same_computer_returns_early(self):
        mixin = _make_fanout()
        session = MagicMock()
        session.get_metadata.return_value.get_transport.return_value.get_redis.return_value.target_computer = "myhost"
        with (
            patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._fanout.config") as mock_config,
        ):
            mock_config.computer.name = "myhost"
            mock_db.get_session = AsyncMock(return_value=session)
            await mixin._forward_stop_to_initiator("sess-001")
        mixin.client.send_request.assert_not_called()  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    async def test_remote_computer_sends_request(self):
        mixin = _make_fanout()
        mixin.client.send_request = AsyncMock()
        session = MagicMock()
        session.title = "My Session"
        session.get_metadata.return_value.get_transport.return_value.get_redis.return_value.target_computer = (
            "remotehost"
        )
        with (
            patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._fanout.config") as mock_config,
        ):
            mock_config.computer.name = "localhost"
            mock_db.get_session = AsyncMock(return_value=session)
            await mixin._forward_stop_to_initiator("sess-001")
        mixin.client.send_request.assert_called_once()  # pyright: ignore[reportAttributeAccessIssue]


class TestMaybeInjectCheckpoint:
    @pytest.mark.unit
    async def test_no_session_returns_early(self):
        mixin = _make_fanout()
        with patch(
            "teleclaude.core.agent_coordinator._fanout.inject_checkpoint_if_needed",
            new_callable=AsyncMock,
        ) as mock_inject:
            await mixin._maybe_inject_checkpoint("sess-001", None)
        mock_inject.assert_not_called()

    @pytest.mark.unit
    async def test_calls_inject_checkpoint_with_session(self):
        mixin = _make_fanout()
        session = _make_session(active_agent="claude")
        with (
            patch(
                "teleclaude.core.agent_coordinator._fanout.inject_checkpoint_if_needed",
                new_callable=AsyncMock,
            ) as mock_inject,
            patch("teleclaude.core.agent_coordinator._fanout.get_default_agent", return_value="claude"),
        ):
            await mixin._maybe_inject_checkpoint("sess-001", session)
        mock_inject.assert_called_once()

    @pytest.mark.unit
    async def test_injection_failure_does_not_propagate(self):
        mixin = _make_fanout()
        session = _make_session(active_agent="claude")
        with (
            patch(
                "teleclaude.core.agent_coordinator._fanout.inject_checkpoint_if_needed",
                new_callable=AsyncMock,
                side_effect=RuntimeError("checkpoint failed"),
            ),
            patch("teleclaude.core.agent_coordinator._fanout.get_default_agent", return_value="claude"),
        ):
            # Should not raise — failures are logged and swallowed
            await mixin._maybe_inject_checkpoint("sess-001", session)
