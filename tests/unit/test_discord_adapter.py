"""Unit tests for Discord adapter ingress/egress behavior."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.models import ChannelMetadata, Session, SessionAdapterMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import ProcessMessageCommand


class FakeDiscordIntents:
    """Minimal discord.Intents replacement for tests."""

    def __init__(self) -> None:
        self.guilds = False
        self.messages = False
        self.message_content = False

    @classmethod
    def default(cls) -> "FakeDiscordIntents":
        return cls()


class FakeDiscordClient:
    """Minimal discord.Client replacement for tests."""

    def __init__(self, *, intents: FakeDiscordIntents) -> None:
        self.intents = intents
        self.user = SimpleNamespace(id=999, name="teleclaude")
        self.channels: dict[int, object] = {}
        self.started_token: str | None = None
        self.closed = False

    def event(self, coro):
        setattr(self, coro.__name__, coro)
        return coro

    async def start(self, token: str) -> None:
        self.started_token = token
        on_ready = getattr(self, "on_ready", None)
        if on_ready is not None:
            await on_ready()

    async def close(self) -> None:
        self.closed = True

    def get_channel(self, channel_id: int) -> object | None:
        return self.channels.get(channel_id)

    async def fetch_channel(self, channel_id: int) -> object | None:
        return self.channels.get(channel_id)


class FakeDiscordModule:
    """Minimal discord module replacement for tests."""

    Intents = FakeDiscordIntents
    Client = FakeDiscordClient

    @staticmethod
    def File(file_path: str) -> object:
        return SimpleNamespace(path=file_path)


class FakeForumChannel:
    """Forum-like channel mock."""

    def __init__(self, channel_id: int, thread_id: int) -> None:
        self.id = channel_id
        self._thread_id = thread_id
        self.created_names: list[str] = []

    async def create_thread(self, *, name: str, content: str) -> object:
        self.created_names.append(name)
        thread = SimpleNamespace(id=self._thread_id)
        _ = content
        return SimpleNamespace(thread=thread)


class FakeThread:
    """Thread-like channel mock."""

    def __init__(self, thread_id: int, parent_id: int) -> None:
        self.id = thread_id
        self.parent = SimpleNamespace(id=parent_id)
        self.sent_texts: list[str] = []
        self.sent_files: list[tuple[str | None, object]] = []
        self.messages: dict[int, object] = {}

    async def send(self, text: str | None = None, *, content: str | None = None, file: object | None = None) -> object:
        if file is not None:
            self.sent_files.append((content, file))
            msg_id = len(self.sent_files) + 8000
        else:
            assert isinstance(text, str)
            self.sent_texts.append(text)
            msg_id = len(self.sent_texts) + 7000
        msg = SimpleNamespace(id=msg_id)
        self.messages[msg_id] = msg
        return msg

    async def fetch_message(self, message_id: int) -> object:
        message = self.messages.get(message_id)
        if message is None:
            message = MagicMock()
            self.messages[message_id] = message
        return message


def _build_session() -> Session:
    return Session(
        session_id="sess-1",
        computer_name="local",
        tmux_session_name="tc_sess_1",
        last_input_origin=InputOrigin.DISCORD.value,
        title="Discord: Alice",
        adapter_metadata=SessionAdapterMetadata(),
    )


@pytest.mark.asyncio
async def test_discord_on_message_creates_session_and_dispatches_process_message() -> None:
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        adapter = DiscordAdapter(client)
        client.register_adapter("discord", adapter)

    session = _build_session()
    fake_db = MagicMock()
    fake_db.get_sessions_by_adapter_metadata = AsyncMock(side_effect=[[], []])
    fake_db.get_session = AsyncMock(return_value=session)
    fake_db.update_session = AsyncMock()

    fake_command_service = MagicMock()
    fake_command_service.create_session = AsyncMock(return_value={"session_id": session.session_id})
    fake_command_service.process_message = AsyncMock()

    thread = FakeThread(thread_id=555111, parent_id=444999)
    message = SimpleNamespace(
        id=12345,
        content="Need help",
        author=SimpleNamespace(id=999001, bot=False, display_name="Alice", name="alice"),
        channel=thread,
        guild=SimpleNamespace(id=202020),
    )

    with (
        patch("teleclaude.adapters.discord_adapter.db", fake_db),
        patch("teleclaude.adapters.ui_adapter.db", fake_db),
        patch("teleclaude.adapters.discord_adapter.get_command_service", return_value=fake_command_service),
    ):
        await adapter._handle_on_message(message)

    fake_command_service.create_session.assert_awaited_once()
    create_cmd = fake_command_service.create_session.await_args.args[0]
    assert create_cmd.origin == InputOrigin.DISCORD.value
    assert create_cmd.channel_metadata["human_role"] == "customer"

    fake_command_service.process_message.assert_awaited_once()
    process_cmd = fake_command_service.process_message.await_args.args[0]
    assert isinstance(process_cmd, ProcessMessageCommand)
    assert process_cmd.text == "Need help"
    assert process_cmd.origin == InputOrigin.DISCORD.value

    discord_meta = session.get_metadata().get_ui().get_discord()
    assert discord_meta.user_id == "999001"
    assert discord_meta.channel_id == 444999
    assert discord_meta.thread_id == 555111


@pytest.mark.asyncio
async def test_discord_create_channel_uses_forum_thread_when_configured() -> None:
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        adapter = DiscordAdapter(client)

    session = _build_session()
    fake_db = MagicMock()
    fake_db.update_session = AsyncMock()

    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    forum = FakeForumChannel(channel_id=333000, thread_id=777000)
    fake_client.channels[333000] = forum

    adapter._client = fake_client
    adapter._help_desk_channel_id = 333000

    with patch("teleclaude.adapters.discord_adapter.db", fake_db):
        thread_id = await adapter.create_channel(session, "Alice ticket", ChannelMetadata(origin=True))

    assert thread_id == "777000"
    discord_meta = session.get_metadata().get_ui().get_discord()
    assert discord_meta.channel_id == 333000
    assert discord_meta.thread_id == 777000
    assert forum.created_names == ["Alice ticket"]


@pytest.mark.asyncio
async def test_discord_send_message_routes_to_thread() -> None:
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        adapter = DiscordAdapter(client)

    session = _build_session()
    discord_meta = session.get_metadata().get_ui().get_discord()
    discord_meta.channel_id = 444999
    discord_meta.thread_id = 555111

    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    thread = FakeThread(thread_id=555111, parent_id=444999)
    fake_client.channels[555111] = thread
    adapter._client = fake_client

    message_id = await adapter.send_message(session, "Agent response")

    assert message_id == "7001"
    assert thread.sent_texts == ["Agent response"]


# =========================================================================
# Channel Gating Tests
# =========================================================================


@pytest.mark.asyncio
async def test_discord_ignores_non_help_desk_channel() -> None:
    """Messages from a random channel are silently dropped when help_desk_channel_id is set."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        adapter = DiscordAdapter(client)
        client.register_adapter("discord", adapter)

    adapter._help_desk_channel_id = 333000

    # Message from a non-help-desk channel (id=999888, no parent)
    message = SimpleNamespace(
        id=12345,
        content="Hello",
        author=SimpleNamespace(id=999001, bot=False, display_name="Alice", name="alice"),
        channel=SimpleNamespace(id=999888, parent_id=None, parent=None),
        guild=SimpleNamespace(id=202020),
    )

    fake_command_service = MagicMock()
    fake_command_service.create_session = AsyncMock()

    with patch("teleclaude.adapters.discord_adapter.get_command_service", return_value=fake_command_service):
        await adapter._handle_on_message(message)

    fake_command_service.create_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_discord_processes_help_desk_forum_thread() -> None:
    """Messages from a thread in the help-desk forum create sessions."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        adapter = DiscordAdapter(client)
        client.register_adapter("discord", adapter)

    adapter._help_desk_channel_id = 333000

    session = _build_session()
    fake_db = MagicMock()
    fake_db.get_sessions_by_adapter_metadata = AsyncMock(side_effect=[[], []])
    fake_db.get_session = AsyncMock(return_value=session)
    fake_db.update_session = AsyncMock()

    fake_command_service = MagicMock()
    fake_command_service.create_session = AsyncMock(return_value={"session_id": session.session_id})
    fake_command_service.process_message = AsyncMock()

    # Thread whose parent_id matches help_desk_channel_id
    thread = FakeThread(thread_id=555111, parent_id=333000)
    message = SimpleNamespace(
        id=12345,
        content="Need help",
        author=SimpleNamespace(id=999001, bot=False, display_name="Alice", name="alice"),
        channel=thread,
        guild=SimpleNamespace(id=202020),
    )

    with (
        patch("teleclaude.adapters.discord_adapter.db", fake_db),
        patch("teleclaude.adapters.ui_adapter.db", fake_db),
        patch("teleclaude.adapters.discord_adapter.get_command_service", return_value=fake_command_service),
    ):
        await adapter._handle_on_message(message)

    fake_command_service.create_session.assert_awaited_once()


@pytest.mark.asyncio
async def test_discord_ignores_wrong_guild() -> None:
    """Messages from a different guild are silently dropped."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        adapter = DiscordAdapter(client)
        client.register_adapter("discord", adapter)

    adapter._guild_id = 111000
    adapter._help_desk_channel_id = 333000

    # Message from a different guild
    thread = FakeThread(thread_id=555111, parent_id=333000)
    message = SimpleNamespace(
        id=12345,
        content="Hello",
        author=SimpleNamespace(id=999001, bot=False, display_name="Alice", name="alice"),
        channel=thread,
        guild=SimpleNamespace(id=999999),  # Wrong guild
    )

    fake_command_service = MagicMock()
    fake_command_service.create_session = AsyncMock()

    with patch("teleclaude.adapters.discord_adapter.get_command_service", return_value=fake_command_service):
        await adapter._handle_on_message(message)

    fake_command_service.create_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_discord_accepts_all_channels_when_unconfigured() -> None:
    """When help_desk_channel_id is None, all channels are accepted (dev/test mode)."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        adapter = DiscordAdapter(client)
        client.register_adapter("discord", adapter)

    adapter._help_desk_channel_id = None  # Unconfigured

    session = _build_session()
    fake_db = MagicMock()
    fake_db.get_sessions_by_adapter_metadata = AsyncMock(side_effect=[[], []])
    fake_db.get_session = AsyncMock(return_value=session)
    fake_db.update_session = AsyncMock()

    fake_command_service = MagicMock()
    fake_command_service.create_session = AsyncMock(return_value={"session_id": session.session_id})
    fake_command_service.process_message = AsyncMock()

    message = SimpleNamespace(
        id=12345,
        content="Need help",
        author=SimpleNamespace(id=999001, bot=False, display_name="Alice", name="alice"),
        channel=SimpleNamespace(id=999888, parent_id=None, parent=None),
        guild=SimpleNamespace(id=202020),
    )

    with (
        patch("teleclaude.adapters.discord_adapter.db", fake_db),
        patch("teleclaude.adapters.ui_adapter.db", fake_db),
        patch("teleclaude.adapters.discord_adapter.get_command_service", return_value=fake_command_service),
    ):
        await adapter._handle_on_message(message)

    fake_command_service.create_session.assert_awaited_once()


# =========================================================================
# Relay Context Collection Tests
# =========================================================================


class FakeHistoryThread:
    """Thread mock that supports async history iteration."""

    def __init__(self, thread_id: int, messages: list[object]) -> None:
        self.id = thread_id
        self._messages = messages

    def history(self, *, after: object = None, limit: int = 200) -> "FakeHistoryThread":
        _ = after, limit
        return self

    def __aiter__(self):
        return self._async_iter()

    async def _async_iter(self):
        for msg in self._messages:
            yield msg


@pytest.mark.asyncio
async def test_relay_context_includes_customer_forwarded_messages() -> None:
    """Bot-forwarded customer messages (matching pattern) appear as Customer in relay context."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        adapter = DiscordAdapter(client)

    # Bot-forwarded customer message
    bot_msg = SimpleNamespace(
        content="**Alice** (discord): I need help with my order",
        author=SimpleNamespace(id=999, bot=True, display_name="teleclaude"),
    )
    # Admin message
    admin_msg = SimpleNamespace(
        content="Let me check that for you",
        author=SimpleNamespace(id=111, bot=False, display_name="AdminBob"),
    )

    fake_thread = FakeHistoryThread(thread_id=555, messages=[bot_msg, admin_msg])
    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    fake_client.channels[555] = fake_thread
    adapter._client = fake_client

    messages = await adapter._collect_relay_messages("555", since=None)

    assert len(messages) == 2
    assert messages[0]["role"] == "Customer"
    assert messages[0]["name"] == "Alice"
    assert messages[0]["content"] == "I need help with my order"
    assert messages[1]["role"] == "Admin"
    assert messages[1]["name"] == "AdminBob"


@pytest.mark.asyncio
async def test_relay_context_excludes_bot_system_messages() -> None:
    """Bot messages that don't match the forwarding pattern are excluded."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        adapter = DiscordAdapter(client)

    # System bot message (no forwarding pattern)
    system_msg = SimpleNamespace(
        content="Initializing Help Desk session...",
        author=SimpleNamespace(id=999, bot=True, display_name="teleclaude"),
    )

    fake_thread = FakeHistoryThread(thread_id=555, messages=[system_msg])
    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    fake_client.channels[555] = fake_thread
    adapter._client = fake_client

    messages = await adapter._collect_relay_messages("555", since=None)
    assert len(messages) == 0


@pytest.mark.asyncio
async def test_relay_context_labels_admin_messages_correctly() -> None:
    """Non-bot messages in relay threads are labelled as Admin."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        adapter = DiscordAdapter(client)

    admin_msg = SimpleNamespace(
        content="I've resolved the issue",
        author=SimpleNamespace(id=111, bot=False, display_name="AdminCarl"),
    )

    fake_thread = FakeHistoryThread(thread_id=555, messages=[admin_msg])
    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    fake_client.channels[555] = fake_thread
    adapter._client = fake_client

    messages = await adapter._collect_relay_messages("555", since=None)
    assert len(messages) == 1
    assert messages[0]["role"] == "Admin"
    assert messages[0]["name"] == "AdminCarl"
