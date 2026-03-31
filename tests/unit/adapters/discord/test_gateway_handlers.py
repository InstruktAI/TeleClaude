from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import cast

import pytest

from teleclaude.adapters.discord.gateway_handlers import GatewayHandlersMixin
from teleclaude.core.models import MessageMetadata, Session

pytestmark = pytest.mark.unit


class DummyGatewayHandlers(GatewayHandlersMixin):
    def __init__(self) -> None:
        self._help_desk_channel_id = 100
        self._all_sessions_channel_id = 200
        self._project_forum_map = {"proj": 300, "unmapped": None}  # pyright: ignore[reportAttributeAccessIssue]
        self._team_channel_map = {400: "team/project"}
        self._client = SimpleNamespace(user=SimpleNamespace(id=900))
        self._parse_optional_int = lambda value: (
            int(str(value).strip()) if value is not None and str(value).strip().isdigit() else None
        )


def _make_message(
    *,
    author: object | None = None,
    channel_id: str = "999",
    parent_id: str | None = None,
    parent_obj_id: str | None = None,
) -> SimpleNamespace:
    parent = None if parent_obj_id is None else SimpleNamespace(id=parent_obj_id)
    channel = SimpleNamespace(id=channel_id, parent_id=parent_id, parent=parent)
    return SimpleNamespace(author=author, channel=channel)


def test_get_managed_forum_ids_collects_help_desk_all_sessions_and_project_forums() -> None:
    adapter = DummyGatewayHandlers()

    managed_ids = adapter._get_managed_forum_ids()

    assert managed_ids == {100, 200, 300, None}


def test_is_bot_message_treats_missing_bot_and_self_authors_as_bot_messages() -> None:
    adapter = DummyGatewayHandlers()

    assert adapter._is_bot_message(_make_message(author=None)) is True
    assert adapter._is_bot_message(_make_message(author=SimpleNamespace(bot=True, id=1))) is True
    assert adapter._is_bot_message(_make_message(author=SimpleNamespace(bot=False, id=900))) is True
    assert adapter._is_bot_message(_make_message(author=SimpleNamespace(bot=False, id=2))) is False


def test_is_managed_message_short_circuits_when_help_desk_channel_is_unset() -> None:
    adapter = DummyGatewayHandlers()
    adapter._help_desk_channel_id = None

    assert adapter._is_managed_message(_make_message(channel_id="999")) is True


def test_is_managed_message_matches_team_channel_directly() -> None:
    adapter = DummyGatewayHandlers()

    assert adapter._is_managed_message(_make_message(channel_id="400")) is True


def test_is_managed_message_matches_managed_parent_forum() -> None:
    adapter = DummyGatewayHandlers()

    assert adapter._is_managed_message(_make_message(channel_id="401", parent_id="200", parent_obj_id="200")) is True


def test_is_managed_message_rejects_unmanaged_channel_hierarchy() -> None:
    adapter = DummyGatewayHandlers()

    assert adapter._is_managed_message(_make_message(channel_id="401", parent_id="999", parent_obj_id="999")) is False


class DispatchingGatewayHandlers(GatewayHandlersMixin):
    def __init__(self) -> None:
        self._help_desk_channel_id = 100
        self._all_sessions_channel_id = 200
        self._project_forum_map = {}
        self._team_channel_map = {400: "team/project"}
        self._escalation_channel_id = None
        self._guild_id = None
        self._client = SimpleNamespace(user=SimpleNamespace(id=900))
        self._parse_optional_int = lambda value: (
            int(str(value).strip()) if value is not None and str(value).strip().isdigit() else None
        )
        self.dispatched_commands: list[tuple[object, str, MessageMetadata, str, Mapping[str, object]]] = []

    def _is_bot_message(self, _message: object) -> bool:
        return False

    def _is_managed_message(self, _message: object) -> bool:
        return True

    def _extract_audio_attachment(self, _message: object) -> None:
        return None

    def _extract_file_attachments(self, _message: object) -> list[object]:
        return []

    async def _resolve_or_create_session(
        self,
        _message: object,
        first_message: str | None = None,
    ) -> Session | None:
        assert first_message == "hello from discord"
        return cast(
            Session,
            SimpleNamespace(
                session_id="sess-456",
                relay_status=None,
                relay_discord_channel_id=None,
                lifecycle_status="active",
                human_role="member",
            ),
        )

    @staticmethod
    def _is_customer_session(_session: object) -> bool:
        return False

    def _is_help_desk_thread(self, _message: object) -> bool:
        return True

    async def _forward_to_relay_thread(self, _session: object, _text: str, _message: object) -> None:
        raise AssertionError("relay forwarding should not run in this test")

    @staticmethod
    def _discord_actor_name(_author_obj: object, _fallback: str) -> str:
        return "DiscordUser#1234"

    @staticmethod
    def _discord_actor_avatar_url(_author_obj: object) -> str:
        return "https://cdn.discordapp.com/avatars/444555666/abc.png"

    def _metadata(self, **kwargs: object) -> MessageMetadata:
        return MessageMetadata(**kwargs)

    async def _dispatch_command(
        self,
        session: object,
        message_id: str,
        metadata: MessageMetadata,
        event: str,
        payload: Mapping[str, object],
        _fn: object,
    ) -> None:
        self.dispatched_commands.append((session, message_id, metadata, event, payload))

    async def _handle_discord_dm(self, _message: object) -> None:
        raise AssertionError("DM path should not run in this test")

    async def _handle_relay_thread_message(self, _message: object, _text: str) -> None:
        raise AssertionError("Relay path should not run in this test")


async def test_handle_on_message_dispatches_typed_actor_metadata() -> None:
    """Discord managed messages must populate typed actor metadata before dispatch."""
    adapter = DispatchingGatewayHandlers()
    message = SimpleNamespace(
        id="msg-discord-001",
        content="hello from discord",
        author=SimpleNamespace(id="444555666"),
        guild=SimpleNamespace(id="777"),
        channel=SimpleNamespace(id="chan-7", parent_id="200", parent=SimpleNamespace(id="200")),
        attachments=[],
    )

    await adapter._handle_on_message(message)

    assert len(adapter.dispatched_commands) == 1
    session_arg, message_id, metadata, event, payload = adapter.dispatched_commands[0]
    assert isinstance(metadata, MessageMetadata)
    assert session_arg.session_id == "sess-456"
    assert message_id == "msg-discord-001"
    assert event == "process_message"
    assert metadata.actor_id == "discord:444555666"
    assert metadata.actor_name == "DiscordUser#1234"
    assert metadata.actor_avatar_url == "https://cdn.discordapp.com/avatars/444555666/abc.png"
    assert metadata.platform_message_id == "msg-discord-001"
    assert payload == {
        "session_id": "sess-456",
        "text": "hello from discord",
        "origin": "discord",
        "actor_id": "discord:444555666",
        "actor_name": "DiscordUser#1234",
        "actor_avatar_url": "https://cdn.discordapp.com/avatars/444555666/abc.png",
    }
