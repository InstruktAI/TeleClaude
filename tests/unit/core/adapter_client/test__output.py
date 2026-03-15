"""Characterization tests for teleclaude.core.adapter_client._output."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.adapter_client._client import AdapterClient
from teleclaude.core.models import CleanupTrigger, MessageMetadata, Session
from teleclaude.core.origins import InputOrigin


def _make_session(
    session_id: str = "sess-1",
    last_input_origin: str = "telegram",
    *,
    initiator_session_id: str | None = None,
) -> Session:
    return Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name=f"tmux-{session_id}",
        title="Session",
        last_input_origin=last_input_origin,
        initiator_session_id=initiator_session_id,
    )


def _make_ui_adapter(*, threaded: bool = False) -> MagicMock:
    adapter = MagicMock(spec=UiAdapter)
    adapter.THREADED_OUTPUT = threaded
    adapter.ensure_channel = AsyncMock(side_effect=lambda session: session)
    adapter.send_error_feedback = AsyncMock()
    adapter.send_message = AsyncMock(return_value="message-id")
    adapter.delete_message = AsyncMock(return_value=True)
    adapter.edit_message = AsyncMock(return_value=True)
    adapter.send_file = AsyncMock(return_value="file-msg")
    adapter.send_output_update = AsyncMock(return_value="output-msg")
    adapter.send_threaded_output = AsyncMock(return_value="thread-msg")
    adapter.update_channel_title = AsyncMock(return_value=True)
    adapter.delete_channel = AsyncMock(return_value=True)
    adapter.move_badge_to_bottom = AsyncMock()
    adapter.clear_turn_state = AsyncMock()
    adapter.drop_pending_output = MagicMock(return_value=0)
    return adapter


def _make_base_adapter() -> MagicMock:
    return MagicMock(spec=BaseAdapter)


@pytest.fixture(autouse=True)
def _display_title() -> object:
    with patch(
        "teleclaude.core.adapter_client._channels.get_display_title_for_session",
        AsyncMock(return_value="Session"),
    ) as mock_title:
        yield mock_title


class TestSendErrorFeedback:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_calls_each_ui_adapter(self):
        client = AdapterClient()
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        await client.send_error_feedback("sess-1", "error")

        telegram.send_error_feedback.assert_awaited_once_with("sess-1", "error")
        discord.send_error_feedback.assert_awaited_once_with("sess-1", "error")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_reraises_first_adapter_exception(self):
        client = AdapterClient()
        telegram = _make_ui_adapter()
        telegram.send_error_feedback = AsyncMock(side_effect=RuntimeError("adapter failure"))
        client.register_adapter("telegram", telegram)

        with pytest.raises(RuntimeError):
            await client.send_error_feedback("sess-1", "error")


class TestEditAndDeleteMessage:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_edit_message_fans_out_to_ui_adapters_and_returns_origin_result(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        discord.edit_message = AsyncMock(return_value=False)
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        with patch("teleclaude.core.adapter_client._channels.db.get_session", AsyncMock(return_value=session)):
            result = await client.edit_message(session, "msg-1", "updated")

        assert result is True
        telegram.ensure_channel.assert_awaited_once_with(session)
        discord.ensure_channel.assert_awaited_once_with(session)
        telegram.edit_message.assert_awaited_once_with(session, "msg-1", "updated")
        discord.edit_message.assert_awaited_once_with(session, "msg-1", "updated")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_delete_message_returns_false_when_no_adapter_succeeds(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        telegram.delete_message = AsyncMock(return_value=False)
        discord.delete_message = AsyncMock(return_value=None)
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        with patch("teleclaude.core.adapter_client._channels.db.get_session", AsyncMock(return_value=session)):
            result = await client.delete_message(session, "msg-1")

        assert result is False


class TestSendFile:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_entry_point_file_message_id(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        telegram.send_file = AsyncMock(return_value="telegram-file")
        discord.send_file = AsyncMock(return_value="discord-file")
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        with patch("teleclaude.core.adapter_client._channels.db.get_session", AsyncMock(return_value=session)):
            result = await client.send_file(session, "/tmp/file.txt", caption="notes")

        assert result == "telegram-file"
        telegram.send_file.assert_awaited_once_with(session, "/tmp/file.txt", caption="notes")
        discord.send_file.assert_awaited_once_with(session, "/tmp/file.txt", caption="notes")


class TestSendMessage:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_feedback_messages_are_suppressed_for_ai_child_sessions(self):
        client = AdapterClient()
        session = _make_session(initiator_session_id="parent-sess")

        with patch("teleclaude.core.adapter_client._output.db") as mock_db:
            mock_db.get_pending_deletions = AsyncMock(return_value=[])
            mock_db.get_session = AsyncMock(return_value=session)

            result = await client.send_message(session, "feedback")

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_feedback_cleanup_deletes_pending_messages_and_routes_only_to_origin_ui(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        telegram.send_message = AsyncMock(return_value="new-feedback")
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        with (
            patch("teleclaude.core.adapter_client._channels.db.get_session", AsyncMock(return_value=session)),
            patch("teleclaude.core.adapter_client._output.db") as mock_db,
        ):
            mock_db.get_pending_deletions = AsyncMock(return_value=["old-1", "old-2"])
            mock_db.clear_pending_deletions = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.add_pending_deletion = AsyncMock()

            result = await client.send_message(session, "feedback")

        assert result == "new-feedback"
        assert telegram.delete_message.await_count == 2
        assert discord.delete_message.await_count == 2
        telegram.send_message.assert_awaited_once()
        assert discord.send_message.await_count == 0
        mock_db.clear_pending_deletions.assert_awaited_once_with(session.session_id, deletion_type="feedback")
        mock_db.add_pending_deletion.assert_awaited_once_with(
            session.session_id,
            "new-feedback",
            deletion_type="feedback",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_source_only_messages_with_non_ui_origin_are_dropped(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="redis")
        telegram = _make_ui_adapter()
        client.register_adapter("telegram", telegram)

        with patch("teleclaude.core.adapter_client._output.db") as mock_db:
            mock_db.get_pending_deletions = AsyncMock(return_value=[])
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.add_pending_deletion = AsyncMock()

            result = await client.send_message(
                session,
                "transcript",
                metadata=MessageMetadata(is_transcription=True),
                cleanup_trigger=CleanupTrigger.NEXT_TURN,
            )

        assert result is None
        assert telegram.send_message.await_count == 0
        assert telegram.ensure_channel.await_count == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_transcription_routes_only_to_origin_ui_adapter(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        telegram.send_message = AsyncMock(return_value="transcript-msg")
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        with (
            patch("teleclaude.core.adapter_client._channels.db.get_session", AsyncMock(return_value=session)),
            patch("teleclaude.core.adapter_client._output.db") as mock_db,
        ):
            mock_db.get_pending_deletions = AsyncMock(return_value=[])
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.add_pending_deletion = AsyncMock()

            result = await client.send_message(
                session,
                "transcript",
                metadata=MessageMetadata(is_transcription=True),
                cleanup_trigger=CleanupTrigger.NEXT_TURN,
            )

        assert result == "transcript-msg"
        telegram.send_message.assert_awaited_once()
        assert discord.send_message.await_count == 0
        mock_db.add_pending_deletion.assert_awaited_once_with(
            session.session_id,
            "transcript-msg",
            deletion_type="user_input",
        )


class TestMoveBadgeAndThreadState:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_move_badge_to_bottom_calls_each_ui_adapter(self):
        client = AdapterClient()
        session = _make_session()
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        await client.move_badge_to_bottom(session)

        telegram.move_badge_to_bottom.assert_awaited_once_with(session)
        discord.move_badge_to_bottom.assert_awaited_once_with(session)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_break_threaded_turn_drops_pending_output_and_clears_turn_state(self):
        client = AdapterClient()
        session = _make_session()
        telegram = _make_ui_adapter(threaded=True)
        discord = _make_ui_adapter(threaded=True)
        redis = _make_base_adapter()
        telegram.drop_pending_output.return_value = 2
        discord.drop_pending_output.return_value = 1
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)
        client.register_adapter("redis", redis)

        await client.break_threaded_turn(session)

        telegram.drop_pending_output.assert_called_once_with(session.session_id)
        discord.drop_pending_output.assert_called_once_with(session.session_id)
        telegram.clear_turn_state.assert_awaited_once_with(session)
        discord.clear_turn_state.assert_awaited_once_with(session)


class TestThreadedAndStreamingOutput:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_threaded_output_cleans_feedback_and_returns_origin_message_id(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        telegram = _make_ui_adapter(threaded=True)
        discord = _make_ui_adapter(threaded=True)
        telegram.send_threaded_output = AsyncMock(return_value="thread-msg")
        discord.send_threaded_output = AsyncMock(return_value="discord-thread")
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        with (
            patch("teleclaude.core.adapter_client._channels.db.get_session", AsyncMock(return_value=session)),
            patch("teleclaude.core.adapter_client._output.db") as mock_db,
        ):
            mock_db.get_pending_deletions = AsyncMock(return_value=["feedback-1"])
            mock_db.clear_pending_deletions = AsyncMock()

            result = await client.send_threaded_output(session, "output block")

        assert result == "thread-msg"
        telegram.delete_message.assert_awaited_once_with(session, "feedback-1")
        discord.delete_message.assert_awaited_once_with(session, "feedback-1")
        telegram.send_threaded_output.assert_awaited_once_with(session, "output block", multi_message=False)
        discord.send_threaded_output.assert_awaited_once_with(session, "output block", multi_message=False)
        mock_db.clear_pending_deletions.assert_awaited_once_with(session.session_id, deletion_type="feedback")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_output_update_cleans_feedback_and_routes_to_ui_adapters(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        telegram.send_output_update = AsyncMock(return_value="output-msg")
        discord.send_output_update = AsyncMock(return_value="discord-output")
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        with (
            patch("teleclaude.core.adapter_client._channels.db.get_session", AsyncMock(return_value=session)),
            patch("teleclaude.core.adapter_client._output.db") as mock_db,
        ):
            mock_db.get_pending_deletions = AsyncMock(return_value=["feedback-1"])
            mock_db.clear_pending_deletions = AsyncMock()

            result = await client.send_output_update(
                session,
                "stdout",
                started_at=1.0,
                last_output_changed_at=2.0,
                is_final=True,
                exit_code=0,
                render_markdown=True,
            )

        assert result == "output-msg"
        telegram.send_output_update.assert_awaited_once_with(session, "stdout", 1.0, 2.0, True, 0, True)
        discord.send_output_update.assert_awaited_once_with(session, "stdout", 1.0, 2.0, True, 0, True)
        mock_db.clear_pending_deletions.assert_awaited_once_with(session.session_id, deletion_type="feedback")


class TestBroadcastUserInput:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_broadcasts_reflection_metadata_using_fresh_session(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        fresh_session = _make_session(last_input_origin="telegram")
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        with patch("teleclaude.core.adapter_client._output.db.get_session", AsyncMock(return_value=fresh_session)):
            await client.broadcast_user_input(
                session,
                "hello",
                InputOrigin.API.value,
                actor_id="user-1",
                actor_name="Alice",
                actor_avatar_url="https://example.test/avatar.png",
            )

        telegram.send_message.assert_awaited_once()
        discord.send_message.assert_awaited_once()
        metadata = telegram.send_message.await_args.kwargs["metadata"]
        assert telegram.send_message.await_args.args[0] is fresh_session
        assert metadata.reflection_actor_id == "user-1"
        assert metadata.reflection_actor_name == "Alice"
        assert metadata.reflection_actor_avatar_url == "https://example.test/avatar.png"
        assert metadata.reflection_origin == InputOrigin.API.value


class TestChannelUpdates:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_update_channel_title_routes_to_all_ui_adapters(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        with patch("teleclaude.core.adapter_client._channels.db.get_session", AsyncMock(return_value=session)):
            result = await client.update_channel_title(session, "New title")

        assert result is True
        telegram.update_channel_title.assert_awaited_once_with(session, "New title")
        discord.update_channel_title.assert_awaited_once_with(session, "New title")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_delete_channel_returns_true_when_any_adapter_succeeds(self):
        client = AdapterClient()
        session = _make_session()
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        telegram.delete_channel = AsyncMock(return_value=False)
        discord.delete_channel = AsyncMock(return_value=True)
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        result = await client.delete_channel(session)

        assert result is True
        telegram.delete_channel.assert_awaited_once_with(session)
        discord.delete_channel.assert_awaited_once_with(session)
