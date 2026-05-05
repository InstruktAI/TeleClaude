"""Characterization tests for teleclaude.core.agent_coordinator._fanout."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.agent_coordinator._fanout import _FanoutMixin
from teleclaude.core.models import Session


def _make_fanout() -> _FanoutMixin:
    """Create a minimal _FanoutMixin instance with required service attrs."""
    mixin = object.__new__(_FanoutMixin)
    mixin.client = MagicMock()
    mixin.tts_manager = MagicMock()
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

    @pytest.mark.unit
    async def test_direct_link_noop_output_is_suppressed(self):
        mixin = _make_fanout()
        sender = _make_session(session_id="sess-001", title="Sender", computer_name="peer-host")
        peer = SimpleNamespace(session_id="sess-002", computer_name="local")
        link = SimpleNamespace(link_id="link-001", mode="direct_link")
        command_service = SimpleNamespace(process_message=AsyncMock())

        with (
            patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._fanout.get_active_links_for_session",
                new_callable=AsyncMock,
                return_value=[link],
            ),
            patch(
                "teleclaude.core.agent_coordinator._fanout.get_peer_members",
                new_callable=AsyncMock,
                return_value=[peer],
            ),
            patch(
                "teleclaude.core.agent_coordinator._fanout.get_command_service",
                return_value=command_service,
            ),
            patch("teleclaude.core.agent_coordinator._fanout.logger") as logger,
        ):
            mock_db.get_session = AsyncMock(return_value=sender)
            delivered = await mixin._fanout_linked_stop_output("sess-001", "Thanks.")

        assert delivered == 0
        command_service.process_message.assert_not_awaited()
        extra = logger.info.call_args.kwargs["extra"]
        assert extra == {
            "source_session_id": "sess-001",
            "target_session_id": "sess-002",
            "link_id": "link-001",
            "role": "assistant",
            "reason": "acknowledgment_only",
            "preview": "Thanks.",
        }


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


class TestExtractAgentOutputSince:
    @pytest.mark.unit
    async def test_no_transcript_path_returns_none(self):
        mixin = _make_fanout()
        session = _make_session(native_log_file=None)
        payload = MagicMock()
        payload.transcript_path = None
        payload.raw = {}
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            result = await mixin._extract_agent_output_since(
                "sess-001",
                payload,
                since_timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC),
            )
        assert result is None

    @pytest.mark.unit
    async def test_returns_assistant_text_after_timestamp(self):
        mixin = _make_fanout()
        session = _make_session(active_agent="claude", native_log_file="/path/to/transcript")
        payload = MagicMock()
        payload.transcript_path = None
        payload.raw = {"agent_name": "claude"}
        with (
            patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._fanout.get_assistant_messages_since",
                return_value=[
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "thinking", "thinking": "reasoning"},
                            {"type": "text", "text": "First reply"},
                            {"type": "tool_use", "name": "Bash"},
                        ],
                    },
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "Second reply"},
                        ],
                    },
                ],
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            result = await mixin._extract_agent_output_since(
                "sess-001",
                payload,
                since_timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC),
            )

        assert result == "First reply\n\nSecond reply"


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
        session.origin_metadata = {"redis": {}}
        session.get_origin_section = lambda key: dict(session.origin_metadata.get(key, {}))
        with patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            await mixin._forward_stop_to_initiator("sess-001")
        mixin.client.send_request.assert_not_called()  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    async def test_same_computer_returns_early(self):
        mixin = _make_fanout()
        session = MagicMock()
        session.origin_metadata = {"redis": {"target_computer": "myhost"}}
        session.get_origin_section = lambda key: dict(session.origin_metadata.get(key, {}))
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
        session.origin_metadata = {"redis": {"target_computer": "remotehost"}}
        session.get_origin_section = lambda key: dict(session.origin_metadata.get(key, {}))
        with (
            patch("teleclaude.core.agent_coordinator._fanout.db") as mock_db,
            patch("teleclaude.core.agent_coordinator._fanout.config") as mock_config,
        ):
            mock_config.computer.name = "localhost"
            mock_db.get_session = AsyncMock(return_value=session)
            await mixin._forward_stop_to_initiator("sess-001")
        mixin.client.send_request.assert_called_once()  # pyright: ignore[reportAttributeAccessIssue]
