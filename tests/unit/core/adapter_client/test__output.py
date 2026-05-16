"""Characterization tests for teleclaude.core.adapter_client._output."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.adapter_client._client import AdapterClient
from teleclaude.core.models import CleanupTrigger, MessageMetadata, Session


def _make_session(
    session_id: str = "sess-1",
    last_input_origin: str = "telegram",
    *,
    initiator_session_id: str | None = None,
    human_email: str | None = None,
) -> Session:
    return Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name=f"tmux-{session_id}",
        title="Session",
        last_input_origin=last_input_origin,
        initiator_session_id=initiator_session_id,
        human_email=human_email,
    )


def _make_ui_adapter() -> MagicMock:
    adapter = MagicMock(spec=UiAdapter)
    adapter.ensure_channel = AsyncMock(side_effect=lambda session: session)  # pyright: ignore[reportUnknownLambdaType]
    adapter.send_error_feedback = AsyncMock()
    adapter.send_message = AsyncMock(return_value="message-id")
    adapter.delete_message = AsyncMock(return_value=True)
    adapter.edit_message = AsyncMock(return_value=True)
    adapter.send_file = AsyncMock(return_value="file-msg")
    adapter.send_output_update = AsyncMock(return_value="output-msg")
    adapter.send_threaded_output = AsyncMock(return_value="thread-msg")
    adapter.update_channel_title = AsyncMock(return_value=True)
    adapter.delete_channel = AsyncMock(return_value=True)
    adapter.clear_turn_state = AsyncMock()
    adapter.drop_pending_output = MagicMock(return_value=0)
    adapter.on_session_status = AsyncMock()
    adapter.on_session_updated = AsyncMock()
    return adapter


def _make_base_adapter() -> MagicMock:
    return MagicMock(spec=BaseAdapter)


@pytest.fixture(autouse=True)
def _display_title() -> object:  # pyright: ignore[reportUnusedFunction]
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
        session = _make_session(last_input_origin="terminal")
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
        telegram.ensure_channel.assert_awaited_once_with(session)
        discord.ensure_channel.assert_not_awaited()
        telegram.send_message.assert_awaited_once()
        assert discord.send_message.await_count == 0
        mock_db.add_pending_deletion.assert_awaited_once_with(
            session.session_id,
            "transcript-msg",
            deletion_type="user_input",
        )


class TestBroadcastUserInput:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_non_discord_origin_reflects_only_to_discord(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        client.register_adapter("telegram", _make_ui_adapter())
        client.register_adapter("discord", _make_ui_adapter())

        with (
            patch("teleclaude.core.adapter_client._output.db.get_session", AsyncMock(return_value=session)),
            patch("teleclaude.core.adapter_client._output.get_identity_resolver") as mock_resolver,
            patch.object(client, "_route_to_ui", AsyncMock()) as mock_route,
        ):
            resolver = MagicMock()
            resolver.resolve.return_value = MagicMock(display_name="Alice")
            mock_resolver.return_value = resolver

            await client.broadcast_user_input(session, "hello", "telegram")

        mock_route.assert_awaited_once()
        assert mock_route.await_args.args == (
            session,
            "send_message",
            "hello",
        )
        assert mock_route.await_args.kwargs["include_adapters"] == {"discord"}
        metadata = mock_route.await_args.kwargs["metadata"]
        assert metadata.reflection_origin == "telegram"
        assert metadata.reflection_actor_name == "Alice"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_discord_origin_does_not_emit_duplicate_admin_reflection(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="discord")
        client.register_adapter("discord", _make_ui_adapter())

        with (
            patch("teleclaude.core.adapter_client._output.db.get_session", AsyncMock(return_value=session)),
            patch("teleclaude.core.adapter_client._output.get_identity_resolver") as mock_resolver,
            patch.object(client, "_route_to_ui", AsyncMock()) as mock_route,
        ):
            resolver = MagicMock()
            resolver.resolve.return_value = MagicMock(display_name="Alice")
            mock_resolver.return_value = resolver

            await client.broadcast_user_input(session, "hello", "discord")

        mock_route.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_terminal_origin_uses_human_email_when_terminal_metadata_is_missing(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="terminal", human_email="maurice@instrukt.ai")
        client.register_adapter("discord", _make_ui_adapter())

        with (
            patch("teleclaude.core.adapter_client._output.db.get_session", AsyncMock(return_value=session)),
            patch("teleclaude.core.adapter_client._output.get_identity_resolver") as mock_resolver,
            patch.object(client, "_route_to_ui", AsyncMock()) as mock_route,
        ):
            resolver = MagicMock()
            resolver.resolve_by_email.return_value = MagicMock(
                person_name="Maurice",
                person_email="maurice@instrukt.ai",
            )
            mock_resolver.return_value = resolver

            await client.broadcast_user_input(session, "hello", "terminal")

        resolver.resolve.assert_not_called()
        resolver.resolve_by_email.assert_called_once_with("maurice@instrukt.ai")
        mock_route.assert_awaited_once()
        metadata = mock_route.await_args.kwargs["metadata"]
        assert metadata.reflection_origin == "terminal"
        assert metadata.reflection_actor_name == "Maurice"


class TestThreadState:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_break_threaded_turn_drops_pending_output(self):
        client = AdapterClient()
        session = _make_session()
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        redis = _make_base_adapter()
        telegram.drop_pending_output.return_value = 2
        discord.drop_pending_output.return_value = 1
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)
        client.register_adapter("redis", redis)

        await client.break_threaded_turn(session)

        telegram.drop_pending_output.assert_called_once_with(session.session_id)
        discord.drop_pending_output.assert_called_once_with(session.session_id)
        telegram.clear_turn_state.assert_not_awaited()
        discord.clear_turn_state.assert_not_awaited()


class TestSendOutputUpdate:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_live_output_with_telegram_origin_routes_to_telegram_and_discord_admin(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        client.register_adapter("telegram", _make_ui_adapter())
        client.register_adapter("discord", _make_ui_adapter())

        with patch.object(
            client,
            "_route_to_ui",
            AsyncMock(side_effect=["telegram-msg", "discord-msg"]),
        ) as route_to_ui:
            result = await client.send_output_update(session, "hello", 1.0, 2.0)

        assert result == "telegram-msg"
        assert route_to_ui.await_count == 2
        first_call, second_call = route_to_ui.await_args_list
        assert first_call.kwargs["include_adapters"] == {"telegram"}
        assert second_call.kwargs["include_adapters"] == {"discord"}
        assert first_call.args[1] == "send_output_update"
        assert second_call.args[1] == "send_output_update"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_live_output_with_terminal_origin_routes_to_discord_admin_only(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="terminal")
        client.register_adapter("telegram", _make_ui_adapter())
        client.register_adapter("discord", _make_ui_adapter())

        with patch.object(
            client,
            "_route_to_ui",
            AsyncMock(return_value="discord-msg"),
        ) as route_to_ui:
            result = await client.send_output_update(session, "hello", 1.0, 2.0)

        assert result is None
        route_to_ui.assert_awaited_once()
        call = route_to_ui.await_args
        assert call is not None
        assert call.kwargs["include_adapters"] == {"discord"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_live_output_with_discord_origin_routes_to_discord_only_no_duplicate(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="discord")
        client.register_adapter("telegram", _make_ui_adapter())
        client.register_adapter("discord", _make_ui_adapter())

        with patch.object(
            client,
            "_route_to_ui",
            AsyncMock(return_value="discord-msg"),
        ) as route_to_ui:
            result = await client.send_output_update(session, "hello", 1.0, 2.0)

        assert result == "discord-msg"
        route_to_ui.assert_awaited_once()
        call = route_to_ui.await_args
        assert call is not None
        assert call.kwargs["include_adapters"] == {"discord"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_live_output_with_whatsapp_origin_routes_to_whatsapp_and_discord_admin(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="whatsapp")
        client.register_adapter("whatsapp", _make_ui_adapter())
        client.register_adapter("discord", _make_ui_adapter())

        with patch.object(
            client,
            "_route_to_ui",
            AsyncMock(side_effect=["whatsapp-msg", "discord-msg"]),
        ) as route_to_ui:
            result = await client.send_output_update(session, "hello", 1.0, 2.0)

        assert result == "whatsapp-msg"
        assert route_to_ui.await_count == 2
        first_call, second_call = route_to_ui.await_args_list
        assert first_call.kwargs["include_adapters"] == {"whatsapp"}
        assert second_call.kwargs["include_adapters"] == {"discord"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_live_output_skips_discord_admin_when_discord_adapter_not_registered(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        client.register_adapter("telegram", _make_ui_adapter())

        with patch.object(
            client,
            "_route_to_ui",
            AsyncMock(return_value="telegram-msg"),
        ) as route_to_ui:
            result = await client.send_output_update(session, "hello", 1.0, 2.0)

        assert result == "telegram-msg"
        route_to_ui.assert_awaited_once()
        call = route_to_ui.await_args
        assert call is not None
        assert call.kwargs["include_adapters"] == {"telegram"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_live_output_return_value_is_origin_result_not_admin_result(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        client.register_adapter("telegram", _make_ui_adapter())
        client.register_adapter("discord", _make_ui_adapter())

        with patch.object(
            client,
            "_route_to_ui",
            AsyncMock(side_effect=["origin-result-value", "admin-result-value"]),
        ):
            result = await client.send_output_update(session, "hello", 1.0, 2.0)

        assert result == "origin-result-value"


class TestResolveAdminOutputTarget:
    @pytest.mark.unit
    def test_returns_none_for_discord_origin(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="discord")
        client.register_adapter("discord", _make_ui_adapter())

        target = client._resolve_admin_output_target(session, "discord")

        assert target is None

    @pytest.mark.unit
    def test_returns_discord_for_eligible_telegram_origin(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        client.register_adapter("telegram", _make_ui_adapter())
        client.register_adapter("discord", _make_ui_adapter())

        target = client._resolve_admin_output_target(session, "telegram")

        assert target == "discord"

    @pytest.mark.unit
    def test_returns_none_when_discord_not_registered(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        client.register_adapter("telegram", _make_ui_adapter())

        target = client._resolve_admin_output_target(session, "telegram")

        assert target is None


class TestChannelUpdates:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_update_channel_title_routes_origin_and_admin_lanes_for_telegram_origin(self):
        """Telegram-origin: rename goes to Telegram (origin) and Discord (admin reflection) only."""
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        whatsapp = _make_ui_adapter()
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)
        client.register_adapter("whatsapp", whatsapp)

        with patch("teleclaude.core.adapter_client._channels.db.get_session", AsyncMock(return_value=session)):
            result = await client.update_channel_title(session)

        assert result is True
        telegram.update_channel_title.assert_awaited_once_with(session)
        discord.update_channel_title.assert_awaited_once_with(session)
        whatsapp.update_channel_title.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_update_channel_title_skips_non_origin_non_admin_adapters_for_discord_origin(self):
        """Discord-origin: rename goes to Discord only — Telegram and other adapters MUST NOT be touched.

        Regression guard for the original bug: a Discord-origin session causing
        Telegram.update_channel_title to be invoked and raise AdapterError.
        """
        client = AdapterClient()
        session = _make_session(last_input_origin="discord")
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        whatsapp = _make_ui_adapter()
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)
        client.register_adapter("whatsapp", whatsapp)

        with patch("teleclaude.core.adapter_client._channels.db.get_session", AsyncMock(return_value=session)):
            result = await client.update_channel_title(session)

        assert result is True
        discord.update_channel_title.assert_awaited_once_with(session)
        telegram.update_channel_title.assert_not_awaited()
        whatsapp.update_channel_title.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_update_channel_title_uses_fresh_session_on_origin_and_admin_lanes(self):
        """Stale session passed in is re-read; both lanes receive the fresh instance."""
        client = AdapterClient()
        stale = _make_session(last_input_origin="telegram")
        fresh = _make_session(last_input_origin="telegram")
        fresh.title = "Fresh title"
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        whatsapp = _make_ui_adapter()
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)
        client.register_adapter("whatsapp", whatsapp)

        with patch("teleclaude.core.adapter_client._output.db.get_session", AsyncMock(return_value=fresh)):
            result = await client.update_channel_title(stale)

        assert result is True
        telegram.update_channel_title.assert_awaited_once_with(fresh)
        discord.update_channel_title.assert_awaited_once_with(fresh)
        whatsapp.update_channel_title.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_dispatch_session_status_routes_origin_and_admin_for_telegram_origin(self):
        """Telegram-origin: typing/badge dispatch reaches Telegram (origin) + Discord (admin reflection)."""
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        whatsapp = _make_ui_adapter()
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)
        client.register_adapter("whatsapp", whatsapp)

        with patch("teleclaude.core.adapter_client._output.db.get_session", AsyncMock(return_value=session)):
            await client.dispatch_session_status(session.session_id, "accepted")

        telegram.on_session_status.assert_awaited_once_with(session, "accepted")
        discord.on_session_status.assert_awaited_once_with(session, "accepted")
        whatsapp.on_session_status.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_dispatch_session_status_skips_non_origin_non_admin_for_discord_origin(self):
        """Discord-origin: dispatch reaches Discord only — Telegram/WhatsApp MUST NOT receive it."""
        client = AdapterClient()
        session = _make_session(last_input_origin="discord")
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        whatsapp = _make_ui_adapter()
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)
        client.register_adapter("whatsapp", whatsapp)

        with patch("teleclaude.core.adapter_client._output.db.get_session", AsyncMock(return_value=session)):
            await client.dispatch_session_status(session.session_id, "active")

        discord.on_session_status.assert_awaited_once_with(session, "active")
        telegram.on_session_status.assert_not_awaited()
        whatsapp.on_session_status.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_dispatch_session_status_skips_when_session_not_found(self):
        client = AdapterClient()
        telegram = _make_ui_adapter()
        client.register_adapter("telegram", telegram)

        with patch("teleclaude.core.adapter_client._output.db.get_session", AsyncMock(return_value=None)):
            await client.dispatch_session_status("missing-session", "accepted")

        telegram.on_session_status.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_dispatch_session_status_terminal_origin_still_reaches_admin_reflection(self):
        """Terminal-origin (no UI origin): admin-reflection (Discord) still receives dispatch."""
        client = AdapterClient()
        session = _make_session(last_input_origin="terminal")
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        with patch("teleclaude.core.adapter_client._output.db.get_session", AsyncMock(return_value=session)):
            await client.dispatch_session_status(session.session_id, "accepted")

        discord.on_session_status.assert_awaited_once_with(session, "accepted")
        telegram.on_session_status.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_dispatch_session_status_no_op_when_no_origin_and_no_admin_target(self):
        """Without Discord registered as admin reflection target, terminal-origin sessions get no dispatch."""
        client = AdapterClient()
        session = _make_session(last_input_origin="terminal")
        telegram = _make_ui_adapter()
        client.register_adapter("telegram", telegram)

        with patch("teleclaude.core.adapter_client._output.db.get_session", AsyncMock(return_value=session)):
            await client.dispatch_session_status(session.session_id, "accepted")

        telegram.on_session_status.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_dispatch_session_update_routes_origin_and_admin_for_telegram_origin(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        telegram = _make_ui_adapter()
        discord = _make_ui_adapter()
        whatsapp = _make_ui_adapter()
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)
        client.register_adapter("whatsapp", whatsapp)

        with patch("teleclaude.core.adapter_client._output.db.get_session", AsyncMock(return_value=session)):
            await client.dispatch_session_update(session.session_id, {"active_agent": "codex"})

        telegram.on_session_updated.assert_awaited_once_with(session, {"active_agent": "codex"})
        discord.on_session_updated.assert_awaited_once_with(session, {"active_agent": "codex"})
        whatsapp.on_session_updated.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_dispatch_session_update_skips_when_session_not_found(self):
        client = AdapterClient()
        telegram = _make_ui_adapter()
        client.register_adapter("telegram", telegram)

        with patch("teleclaude.core.adapter_client._output.db.get_session", AsyncMock(return_value=None)):
            await client.dispatch_session_update("missing-session", {"active_agent": "codex"})

        telegram.on_session_updated.assert_not_awaited()

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


class TestOutstandingFinalOutputRepair:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_repairs_discord_admin_for_non_ui_origin_sessions(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="terminal")
        stop_at = datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC)
        session.last_output_raw = "final output"
        session.last_agent_stop_at = stop_at
        session.origin_metadata = {}

        discord = _make_ui_adapter()
        discord.get_last_delivered_at.return_value = None
        client.register_adapter("discord", discord)

        with (
            patch("teleclaude.core.adapter_client._output.db.list_sessions", AsyncMock(return_value=[session])),
            patch("teleclaude.core.adapter_client._output.db.get_session", AsyncMock(return_value=session)),
            patch.object(client, "_route_to_ui", AsyncMock(return_value="discord-msg")) as route_to_ui,
        ):
            repaired = await client.reconcile_outstanding_final_outputs("local")

        assert repaired == 1
        route_to_ui.assert_awaited_once()
        call = route_to_ui.await_args
        assert call is not None
        assert call.kwargs["include_adapters"] == {"discord"}
        assert call.args[2] == "final output"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_reconciles_origin_and_discord_admin_when_final_output_is_undelivered(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="telegram")
        stop_at = datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC)
        session.last_output_raw = "final output"
        session.last_agent_stop_at = stop_at
        session.origin_metadata = {"telegram": {"topic_id": 42}}

        telegram = _make_ui_adapter()
        telegram.get_last_delivered_at.return_value = None
        discord = _make_ui_adapter()
        discord.get_last_delivered_at.return_value = None
        client.register_adapter("telegram", telegram)
        client.register_adapter("discord", discord)

        with (
            patch("teleclaude.core.adapter_client._output.db.list_sessions", AsyncMock(return_value=[session])),
            patch("teleclaude.core.adapter_client._output.db.get_session", AsyncMock(return_value=session)),
            patch.object(client, "_route_to_ui", AsyncMock(return_value="msg")) as route_to_ui,
        ):
            repaired = await client.reconcile_outstanding_final_outputs("local")

        assert repaired == 1
        assert route_to_ui.await_count == 2
        include_adapter_sets = [call.kwargs["include_adapters"] for call in route_to_ui.await_args_list]
        assert {"telegram"} in include_adapter_sets
        assert {"discord"} in include_adapter_sets
        for call in route_to_ui.await_args_list:
            assert call.args[1] == "send_output_update"
            assert call.args[2] == "final output"
            assert call.kwargs["delivery_ts"] == stop_at

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_skips_origin_ui_adapter_when_final_output_already_delivered_after_stop(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="discord")
        stop_at = datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC)
        session.last_output_raw = "final output"
        session.last_agent_stop_at = stop_at
        session.origin_metadata = {"discord": {"thread_id": 99}}

        discord = _make_ui_adapter()
        discord.get_last_delivered_at.return_value = datetime(2026, 4, 3, 12, 1, 0, tzinfo=UTC)
        client.register_adapter("discord", discord)

        with (
            patch("teleclaude.core.adapter_client._output.db.list_sessions", AsyncMock(return_value=[session])),
            patch("teleclaude.core.adapter_client._output.db.get_session", AsyncMock(return_value=session)),
            patch.object(client, "_route_to_ui", AsyncMock(return_value="discord-msg")) as route_to_ui,
        ):
            repaired = await client.reconcile_outstanding_final_outputs("local")

        assert repaired == 0
        route_to_ui.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_skips_origin_ui_adapter_when_destination_metadata_has_been_cleared(self):
        client = AdapterClient()
        session = _make_session(last_input_origin="discord")
        stop_at = datetime(2026, 4, 3, 12, 0, 0, tzinfo=UTC)
        session.last_output_raw = "final output"
        session.last_agent_stop_at = stop_at
        session.origin_metadata = {"discord": {"last_delivered_at": "2026-04-03T11:00:00+00:00"}}

        discord = _make_ui_adapter()
        client.register_adapter("discord", discord)

        with (
            patch("teleclaude.core.adapter_client._output.db.list_sessions", AsyncMock(return_value=[session])),
            patch("teleclaude.core.adapter_client._output.db.get_session", AsyncMock(return_value=session)),
            patch.object(client, "_route_to_ui", AsyncMock(return_value="discord-msg")) as route_to_ui,
        ):
            repaired = await client.reconcile_outstanding_final_outputs("local")

        assert repaired == 0
        route_to_ui.assert_not_awaited()
