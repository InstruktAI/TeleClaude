"""Unit tests for Discord adapter ingress/egress behavior."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from typing_extensions import TypedDict

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.events import SessionStatusContext, SessionUpdatedContext
from teleclaude.core.identity import IdentityContext
from teleclaude.core.models import (
    ChannelMetadata,
    DiscordAdapterMetadata,
    MessageMetadata,
    Session,
    SessionAdapterMetadata,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import KeysCommand, ProcessMessageCommand

if TYPE_CHECKING:
    from teleclaude.adapters.discord_adapter import DiscordAdapter


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
        self.views: list[object] = []

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

    def add_view(self, view: object) -> None:
        self.views.append(view)


class FakeCommand:
    """Minimal app command."""

    def __init__(self, *, name: str, description: str, callback: object) -> None:
        self.name = name
        self.description = description
        self.callback = callback


class FakeCommandTree:
    """Minimal app command tree."""

    def __init__(self, client: object) -> None:
        self.client = client
        self.commands: list[tuple[object, object | None]] = []

    def add_command(self, command: object, guild: object | None = None) -> None:
        self.commands.append((command, guild))

    async def sync(self, *, guild: object | None = None) -> list[object]:
        _ = guild
        return []


class FakeAppCommands:
    """Container for discord.app_commands API."""

    CommandTree = FakeCommandTree
    Command = FakeCommand


class FakeButtonStyle:
    primary = 1


class FakeButton:
    def __init__(self, *, label: str, custom_id: str, style: int) -> None:
        self.label = label
        self.custom_id = custom_id
        self.style = style
        self.callback = None


class FakeView:
    def __init__(self, *, timeout: float | None = None) -> None:
        self.timeout = timeout
        self.children: list[object] = []

    def add_item(self, item: object) -> None:
        self.children.append(item)


class FakeUI:
    View = FakeView
    Button = FakeButton


class FakeDiscordModule:
    """Minimal discord module replacement for tests."""

    Intents = FakeDiscordIntents
    Client = FakeDiscordClient
    app_commands = FakeAppCommands
    ButtonStyle = FakeButtonStyle
    ui = FakeUI

    @staticmethod
    def File(file_path: str) -> object:
        return SimpleNamespace(path=file_path)

    @staticmethod
    def Object(*, id: int) -> object:
        return SimpleNamespace(id=id)


class FakeForumPostThread:
    """Forum post thread mock."""

    def __init__(self, thread_id: int, parent_id: int) -> None:
        self.id = thread_id
        self.parent = SimpleNamespace(id=parent_id)
        self.parent_id = parent_id
        self.messages: dict[int, object] = {}

    def add_message(self, message_id: int, *, content: str, view: object | None) -> object:
        message = SimpleNamespace(id=message_id, content=content, view=view)

        async def _edit(*, content: str, view: object | None = None) -> None:
            message.content = content
            message.view = view

        message.edit = AsyncMock(side_effect=_edit)
        message.pin = AsyncMock(return_value=None)
        self.messages[message_id] = message
        return message

    async def fetch_message(self, message_id: int) -> object:
        message = self.messages.get(message_id)
        if message is None:
            raise RuntimeError("message not found")
        return message


class SessionUpdatedFields(TypedDict):
    native_session_id: str | None


class FakeForumChannel:
    """Forum-like channel mock with discord.py create_thread contract."""

    def __init__(self, channel_id: int, thread_id: int, starter_message_id: int | None = None) -> None:
        self.id = channel_id
        self._thread_id = thread_id
        self._starter_message_id = starter_message_id if starter_message_id is not None else thread_id
        self.created_names: list[str] = []
        self.created_threads: list[FakeForumPostThread] = []

    async def create_thread(self, *, name: str, content: str, view: object | None = None) -> object:
        self.created_names.append(name)
        thread = FakeForumPostThread(thread_id=self._thread_id, parent_id=self.id)
        message = thread.add_message(self._starter_message_id, content=content, view=view)
        self.created_threads.append(thread)
        return SimpleNamespace(thread=thread, message=message)


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

    # Isolate from host config — dev machines have real Discord IDs
    adapter._guild_id = None
    adapter._help_desk_channel_id = None

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
    session.human_role = "customer"
    fake_db = MagicMock()
    fake_db.update_session = AsyncMock()

    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    forum = FakeForumChannel(channel_id=333000, thread_id=777000)
    fake_client.channels[333000] = forum

    adapter._client = fake_client
    adapter._help_desk_channel_id = 333000

    with patch("teleclaude.adapters.discord_adapter.db", fake_db):
        thread_id = await adapter.create_channel(session, "Alice ticket", ChannelMetadata())

    assert thread_id == "777000"
    discord_meta = session.get_metadata().get_ui().get_discord()
    assert discord_meta.channel_id == 333000
    assert discord_meta.thread_id == 777000
    assert discord_meta.thread_topper_message_id == "777000"
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


@pytest.mark.asyncio
async def test_discord_send_message_truncates_over_limit() -> None:
    """send_message should clamp text to Discord's hard message length."""
    adapter = _make_adapter()
    session = _build_session()
    discord_meta = session.get_metadata().get_ui().get_discord()
    discord_meta.channel_id = 444999
    discord_meta.thread_id = 555111

    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    thread = FakeThread(thread_id=555111, parent_id=444999)
    fake_client.channels[555111] = thread
    adapter._client = fake_client

    long_text = "x" * (adapter.max_message_size + 250)
    await adapter.send_message(session, long_text)

    sent_text = thread.sent_texts[0]
    assert len(sent_text) == adapter.max_message_size
    assert sent_text.endswith(adapter._TRUNCATION_SUFFIX)


@pytest.mark.asyncio
async def test_discord_reflection_webhook_truncates_over_limit() -> None:
    """Reflection webhook path should clamp content to Discord's hard message length."""
    adapter = _make_adapter()
    session = _build_session()
    discord_meta = session.get_metadata().get_ui().get_discord()
    discord_meta.channel_id = 444999
    discord_meta.thread_id = 555111

    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    thread = FakeThread(thread_id=555111, parent_id=444999)
    fake_client.channels[555111] = thread
    adapter._client = fake_client

    webhook = MagicMock()
    webhook.send = AsyncMock(return_value=SimpleNamespace(id=9911))

    metadata = MessageMetadata(reflection_actor_name="Alice")
    long_text = "x" * (adapter.max_message_size + 250)

    with patch.object(adapter, "_get_or_create_reflection_webhook", AsyncMock(return_value=webhook)):
        message_id = await adapter.send_message(session, long_text, metadata=metadata)

    assert message_id == "9911"
    assert thread.sent_texts == []
    webhook.send.assert_awaited_once()
    sent_content = webhook.send.await_args.kwargs["content"]
    assert len(sent_content) == adapter.max_message_size
    assert sent_content.endswith(adapter._TRUNCATION_SUFFIX)


@pytest.mark.asyncio
async def test_discord_edit_message_truncates_over_limit() -> None:
    """edit_message should clamp text to Discord's hard message length."""
    adapter = _make_adapter()
    session = _build_session()
    discord_meta = session.get_metadata().get_ui().get_discord()
    discord_meta.channel_id = 444999
    discord_meta.thread_id = 555111

    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    thread = FakeThread(thread_id=555111, parent_id=444999)
    editable = SimpleNamespace(edit=AsyncMock(return_value=None))
    thread.messages[777] = editable
    fake_client.channels[555111] = thread
    adapter._client = fake_client

    long_text = "x" * (adapter.max_message_size + 250)
    edited = await adapter.edit_message(session, "777", long_text)

    assert edited is True
    editable.edit.assert_awaited_once()
    sent_content = editable.edit.await_args.kwargs["content"]
    assert len(sent_content) == adapter.max_message_size
    assert sent_content.endswith(adapter._TRUNCATION_SUFFIX)


@pytest.mark.asyncio
async def test_discord_send_file_truncates_caption_over_limit(tmp_path) -> None:
    """send_file should clamp oversized captions before dispatch."""
    adapter = _make_adapter()
    session = _build_session()
    discord_meta = session.get_metadata().get_ui().get_discord()
    discord_meta.channel_id = 444999
    discord_meta.thread_id = 555111

    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    thread = FakeThread(thread_id=555111, parent_id=444999)
    fake_client.channels[555111] = thread
    adapter._client = fake_client

    file_path = tmp_path / "artifact.txt"
    file_path.write_text("content", encoding="utf-8")
    long_caption = "c" * (adapter.max_message_size + 100)

    await adapter.send_file(session, str(file_path), caption=long_caption)

    sent_caption, _file = thread.sent_files[0]
    assert sent_caption is not None
    assert len(sent_caption) == adapter.max_message_size
    assert sent_caption.endswith(adapter._TRUNCATION_SUFFIX)


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

    adapter._guild_id = None
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

    adapter._guild_id = None
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


# =========================================================================
# Escalation Tests
# =========================================================================


@pytest.mark.asyncio
async def test_escalation_creates_thread_in_escalation_forum() -> None:
    """create_escalation_thread creates a thread in the escalation forum channel."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        adapter = DiscordAdapter(client)

    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    escalation_forum = FakeForumChannel(channel_id=888000, thread_id=999888)
    fake_client.channels[888000] = escalation_forum
    adapter._client = fake_client
    adapter._escalation_channel_id = 888000

    thread_id = await adapter.create_escalation_thread(
        customer_name="Alice",
        reason="Billing issue",
        context_summary="Customer has billing question",
        session_id="sess-123",
    )

    assert thread_id == 999888
    assert "Alice" in escalation_forum.created_names


# =========================================================================
# Close Channel Tests
# =========================================================================


class FakeDeletableThread:
    """Thread mock that supports delete."""

    def __init__(self, thread_id: int, parent_id: int) -> None:
        self.id = thread_id
        self.parent = SimpleNamespace(id=parent_id)
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


@pytest.mark.asyncio
async def test_discord_close_channel_deletes_thread() -> None:
    """close_channel deletes the Discord thread (not archives)."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        adapter = DiscordAdapter(client)

    session = _build_session()
    discord_meta = session.get_metadata().get_ui().get_discord()
    discord_meta.thread_id = 555111

    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    thread = FakeDeletableThread(thread_id=555111, parent_id=444999)
    fake_client.channels[555111] = thread
    adapter._client = fake_client

    result = await adapter.close_channel(session)

    assert result is True
    assert thread.deleted is True


@pytest.mark.asyncio
async def test_handle_on_ready_sets_ready_before_slow_bootstrap() -> None:
    adapter = _make_adapter()
    adapter._client = FakeDiscordClient(intents=FakeDiscordIntents.default())

    infra_entered = asyncio.Event()
    infra_release = asyncio.Event()

    async def _slow_infra() -> None:
        infra_entered.set()
        await infra_release.wait()

    adapter._ensure_discord_infrastructure = AsyncMock(side_effect=_slow_infra)  # type: ignore[method-assign]
    adapter._tree = None

    task = asyncio.create_task(adapter._handle_on_ready())
    await asyncio.wait_for(infra_entered.wait(), timeout=1.0)
    assert adapter._ready_event.is_set() is True
    infra_release.set()
    await task


# =========================================================================
# Threaded Output Metadata Tests
# =========================================================================


def test_discord_build_metadata_for_thread_no_markdownv2() -> None:
    """Discord _build_metadata_for_thread returns metadata without MarkdownV2."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        adapter = DiscordAdapter(client)

    metadata = adapter._build_metadata_for_thread()
    assert metadata.parse_mode is None


# =========================================================================
# Forum Routing Tests
# =========================================================================


def _make_adapter() -> "DiscordAdapter":
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        return DiscordAdapter(client)


def test_get_enabled_agents_filters_disabled_entries() -> None:
    adapter = _make_adapter()
    with patch("teleclaude.adapters.discord_adapter.config") as mock_config:
        mock_config.agents = {
            "claude": SimpleNamespace(enabled=True),
            "gemini": SimpleNamespace(enabled=False),
            "codex": SimpleNamespace(enabled=True),
        }
        assert adapter._get_enabled_agents() == ["claude", "codex"]
        assert adapter._multi_agent is True
        assert adapter._default_agent == "claude"


def test_resolve_project_from_forum_returns_matching_path() -> None:
    adapter = _make_adapter()
    adapter._forum_project_map = {200: "/home/user/proj"}
    assert adapter._resolve_project_from_forum(200) == "/home/user/proj"
    assert adapter._resolve_project_from_forum(999) is None


@pytest.mark.asyncio
async def test_session_launcher_view_builds_buttons_for_enabled_agents() -> None:
    import importlib as py_importlib

    real_import_module = py_importlib.import_module

    def _fake_import_module(name: str, package: str | None = None):
        if name == "discord":
            return FakeDiscordModule
        return real_import_module(name, package)

    with patch("importlib.import_module", side_effect=_fake_import_module):
        from teleclaude.adapters.discord import session_launcher as launcher_module

        launcher_module = py_importlib.reload(launcher_module)
        launch_callback = AsyncMock()
        view = launcher_module.SessionLauncherView(enabled_agents=["claude", "gemini"], on_launch=launch_callback)

    assert view.timeout is None
    assert [child.label for child in view.children] == ["Claude", "Gemini"]
    assert [child.custom_id for child in view.children] == ["launch:claude", "launch:gemini"]

    interaction = SimpleNamespace()
    await view.children[1].callback(interaction)
    launch_callback.assert_awaited_once_with(interaction, "gemini")


@pytest.mark.asyncio
async def test_post_or_update_launcher_pins_new_message() -> None:
    adapter = _make_adapter()
    adapter._client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    adapter._get_enabled_agents = MagicMock(return_value=["claude", "gemini"])  # type: ignore[method-assign]

    forum = FakeForumChannel(channel_id=600, thread_id=700)
    adapter._client.channels[600] = forum

    fake_db = MagicMock()
    fake_db.get_system_setting = AsyncMock(return_value=None)
    fake_db.set_system_setting = AsyncMock()

    with patch("teleclaude.adapters.discord_adapter.db", fake_db):
        await adapter._post_or_update_launcher(600)

    fake_db.get_system_setting.assert_has_awaits(
        [
            call("discord_launcher:600:thread_id"),
            call("discord_launcher:600:message_id"),
            call("discord_launcher:600"),
        ]
    )
    assert forum.created_names == ["Start a session"]
    assert len(forum.created_threads) == 1
    starter = await forum.created_threads[0].fetch_message(700)
    starter.pin.assert_awaited_once()
    fake_db.set_system_setting.assert_has_awaits(
        [
            call("discord_launcher:600:thread_id", "700"),
            call("discord_launcher:600:message_id", "700"),
            call("discord_launcher:600", "700"),
        ]
    )


@pytest.mark.asyncio
async def test_post_or_update_launcher_pins_existing_message() -> None:
    adapter = _make_adapter()
    adapter._client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    adapter._get_enabled_agents = MagicMock(return_value=["claude", "gemini"])  # type: ignore[method-assign]

    forum = FakeForumChannel(channel_id=600, thread_id=700)
    existing_thread = FakeForumPostThread(thread_id=700, parent_id=600)
    existing = existing_thread.add_message(12345, content="Start a session", view=None)
    adapter._client.channels[600] = forum
    adapter._client.channels[700] = existing_thread

    fake_db = MagicMock()
    fake_db.get_system_setting = AsyncMock(side_effect=["700", "12345"])
    fake_db.set_system_setting = AsyncMock()

    with patch("teleclaude.adapters.discord_adapter.db", fake_db):
        await adapter._post_or_update_launcher(600)

    fake_db.get_system_setting.assert_has_awaits(
        [
            call("discord_launcher:600:thread_id"),
            call("discord_launcher:600:message_id"),
        ]
    )
    existing.edit.assert_awaited_once()
    existing.pin.assert_awaited_once()
    assert forum.created_threads == []
    fake_db.set_system_setting.assert_not_awaited()


def _build_session_with(*, human_role: str | None = None, project_path: str | None = None, **kwargs) -> Session:
    return Session(
        session_id="sess-routing",
        computer_name="local",
        tmux_session_name="tc_sess_routing",
        last_input_origin=InputOrigin.DISCORD.value,
        title="Test session",
        adapter_metadata=SessionAdapterMetadata(),
        human_role=human_role,
        project_path=project_path,
        **kwargs,
    )


def test_resolve_target_forum_customer_routes_to_help_desk() -> None:
    """Customer sessions route to the help desk forum."""
    adapter = _make_adapter()
    adapter._help_desk_channel_id = 100
    adapter._all_sessions_channel_id = 200

    session = _build_session_with(human_role="customer")
    assert adapter._resolve_target_forum(session) == 100


def test_resolve_target_forum_project_match() -> None:
    """Sessions with matching project_path route to the project forum."""
    adapter = _make_adapter()
    adapter._help_desk_channel_id = 100
    adapter._all_sessions_channel_id = 200
    adapter._project_forum_map = {"/home/user/project-a": 300}

    session = _build_session_with(project_path="/home/user/project-a")
    assert adapter._resolve_target_forum(session) == 300


def test_resolve_target_forum_project_subdir_match() -> None:
    """Sessions in a subdirectory of a mapped project match the parent."""
    adapter = _make_adapter()
    adapter._help_desk_channel_id = 100
    adapter._all_sessions_channel_id = 200
    adapter._project_forum_map = {"/home/user/project-a": 300}

    session = _build_session_with(project_path="/home/user/project-a/src")
    assert adapter._resolve_target_forum(session) == 300


def test_resolve_target_forum_fallback_to_all_sessions() -> None:
    """Non-customer sessions without a project match fall back to all-sessions."""
    adapter = _make_adapter()
    adapter._help_desk_channel_id = 100
    adapter._all_sessions_channel_id = 200
    adapter._project_forum_map = {"/home/user/project-a": 300}

    session = _build_session_with(project_path="/home/user/other-project")
    assert adapter._resolve_target_forum(session) == 200


def test_resolve_target_forum_no_project_path_falls_back() -> None:
    """Sessions without project_path fall back to all-sessions."""
    adapter = _make_adapter()
    adapter._help_desk_channel_id = 100
    adapter._all_sessions_channel_id = 200

    session = _build_session_with(project_path=None)
    assert adapter._resolve_target_forum(session) == 200


# =========================================================================
# Managed Message Acceptance Tests
# =========================================================================


def test_is_managed_message_accepts_help_desk_thread() -> None:
    """Messages from help desk threads are accepted."""
    adapter = _make_adapter()
    adapter._help_desk_channel_id = 100
    adapter._all_sessions_channel_id = 200

    msg = SimpleNamespace(channel=SimpleNamespace(id=555, parent_id=100, parent=SimpleNamespace(id=100)))
    assert adapter._is_managed_message(msg) is True


def test_is_managed_message_accepts_project_forum_thread() -> None:
    """Messages from project forum threads are accepted."""
    adapter = _make_adapter()
    adapter._help_desk_channel_id = 100
    adapter._all_sessions_channel_id = 200
    adapter._project_forum_map = {"/home/user/proj": 300}

    msg = SimpleNamespace(channel=SimpleNamespace(id=555, parent_id=300, parent=SimpleNamespace(id=300)))
    assert adapter._is_managed_message(msg) is True


def test_is_managed_message_rejects_unmanaged_channel() -> None:
    """Messages from non-managed channels are rejected."""
    adapter = _make_adapter()
    adapter._help_desk_channel_id = 100
    adapter._all_sessions_channel_id = 200

    msg = SimpleNamespace(channel=SimpleNamespace(id=999, parent_id=888, parent=SimpleNamespace(id=888)))
    assert adapter._is_managed_message(msg) is False


def test_is_managed_message_accepts_all_when_unconfigured() -> None:
    """When help_desk is unconfigured, all messages are accepted."""
    adapter = _make_adapter()
    adapter._help_desk_channel_id = None

    msg = SimpleNamespace(channel=SimpleNamespace(id=999, parent_id=None, parent=None))
    assert adapter._is_managed_message(msg) is True


# =========================================================================
# Discord Title Strategy Tests
# =========================================================================


def test_build_thread_title_project_forum_description_only() -> None:
    """In a project-specific forum, title is just the session description."""
    adapter = _make_adapter()
    adapter._all_sessions_channel_id = 200

    session = _build_session_with(project_path="/home/user/proj")
    session.title = "Fix auth flow"
    # target_forum_id != all_sessions -> project forum
    assert adapter._build_thread_title(session, 300) == "Fix auth flow"


def test_build_thread_title_catchall_prefixed() -> None:
    """In the catch-all forum, title is prefixed with short project name."""
    adapter = _make_adapter()
    adapter._all_sessions_channel_id = 200

    session = _build_session_with(project_path="/home/user/my-project")
    session.title = "Fix auth flow"
    title = adapter._build_thread_title(session, 200)
    assert "Fix auth flow" in title
    # Should include a project prefix
    assert title != "Fix auth flow"


def test_build_thread_title_untitled_fallback() -> None:
    """When session has no title, 'Untitled' is used."""
    adapter = _make_adapter()
    adapter._all_sessions_channel_id = 200

    session = _build_session_with(project_path="/home/user/proj")
    session.title = None
    assert adapter._build_thread_title(session, 300) == "Untitled"


# =========================================================================
# Thread Topper Tests
# =========================================================================


def test_build_thread_topper_includes_session_id() -> None:
    """Thread topper includes the TeleClaude session ID."""
    adapter = _make_adapter()
    session = _build_session_with(project_path="/home/user/proj", active_agent="claude", thinking_mode="high")
    result = adapter._build_thread_topper(session)
    assert "tc: sess-routing" in result


def test_build_thread_topper_includes_agent_and_speed() -> None:
    """Thread topper shows agent and thinking mode."""
    adapter = _make_adapter()
    session = _build_session_with(project_path="/home/user/proj", active_agent="claude", thinking_mode="high")
    result = adapter._build_thread_topper(session)
    assert "agent: claude/high" in result


def test_build_thread_topper_handles_missing_native_id() -> None:
    """Thread topper omits ai: line when native_session_id is not set."""
    adapter = _make_adapter()
    session = _build_session_with(project_path="/home/user/proj")
    session.native_session_id = None
    result = adapter._build_thread_topper(session)
    assert "ai:" not in result


def test_build_thread_topper_includes_native_id_when_present() -> None:
    """Thread topper includes ai: line when native_session_id is set."""
    adapter = _make_adapter()
    session = _build_session_with(project_path="/home/user/proj")
    session.native_session_id = "native-abc-123"
    result = adapter._build_thread_topper(session)
    assert "ai: native-abc-123" in result


# =========================================================================
# Infrastructure Validation Tests
# =========================================================================


@pytest.mark.asyncio
async def test_validate_channel_id_returns_id_when_live() -> None:
    """_validate_channel_id returns the ID if the channel is reachable."""
    adapter = _make_adapter()
    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    fake_channel = SimpleNamespace(id=12345)
    fake_client.channels[12345] = fake_channel
    adapter._client = fake_client

    result = await adapter._validate_channel_id(12345)
    assert result == 12345


@pytest.mark.asyncio
async def test_validate_channel_id_returns_none_when_stale() -> None:
    """_validate_channel_id returns None if the channel is not found (stale ID)."""
    adapter = _make_adapter()
    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    # Channel 99999 not in client's channel map → stale
    adapter._client = fake_client

    result = await adapter._validate_channel_id(99999)
    assert result is None


@pytest.mark.asyncio
async def test_validate_channel_id_returns_none_for_none_input() -> None:
    """_validate_channel_id passes through None without touching the client."""
    adapter = _make_adapter()
    result = await adapter._validate_channel_id(None)
    assert result is None


@pytest.mark.asyncio
async def test_ensure_project_forums_clears_stale_id_and_reprovisions() -> None:
    """_ensure_project_forums clears a stale discord_forum ID and re-creates it."""
    adapter = _make_adapter()
    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    # Forum 999 is stale (not in client), guild will create a new forum
    adapter._client = fake_client

    from types import SimpleNamespace as SN

    created_forums: list[str] = []

    async def fake_find_or_create_forum(guild, category, name, topic):
        created_forums.append(name)
        return 777  # new forum ID

    adapter._find_or_create_forum = fake_find_or_create_forum

    # A trusted dir with a stale discord_forum ID
    td = SN(path="/proj/a", name="ProjectA", desc="Project A", discord_forum=999)

    with patch("teleclaude.adapters.discord_adapter.config") as mock_config:
        mock_config.computer.get_all_trusted_dirs.return_value = [td]

        await adapter._ensure_project_forums(guild=SN(), category=None)

    # Stale ID cleared, forum re-created, new ID assigned
    assert "ProjectA" in created_forums
    assert td.discord_forum == 777


@pytest.mark.asyncio
async def test_ensure_project_forums_skips_valid_forum() -> None:
    """_ensure_project_forums skips a trusted dir whose discord_forum ID is live."""
    adapter = _make_adapter()
    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    live_forum = SimpleNamespace(id=444)
    fake_client.channels[444] = live_forum
    adapter._client = fake_client

    from types import SimpleNamespace as SN

    created_forums: list[str] = []

    async def fake_find_or_create_forum(guild, category, name, topic):
        created_forums.append(name)
        return 999

    adapter._find_or_create_forum = fake_find_or_create_forum

    td = SN(path="/proj/b", name="ProjectB", desc="Project B", discord_forum=444)

    with patch("teleclaude.adapters.discord_adapter.config") as mock_config:
        mock_config.computer.get_all_trusted_dirs.return_value = [td]

        await adapter._ensure_project_forums(guild=SN(), category=None)

    # Valid forum → no re-creation
    assert "ProjectB" not in created_forums
    assert td.discord_forum == 444


@pytest.mark.asyncio
async def test_ensure_discord_infrastructure_clears_stale_channel_and_reprovisions() -> None:
    """_ensure_discord_infrastructure clears a stale channel ID and re-provisions it."""
    from types import SimpleNamespace as SN

    adapter = _make_adapter()
    fake_client = FakeDiscordClient(intents=FakeDiscordIntents.default())
    # Channel 999 is stale — not present in client
    adapter._client = fake_client
    adapter._guild_id = 1
    adapter._help_desk_channel_id = 999  # stale

    provisioned: list[str] = []

    async def fake_find_or_create_forum(guild, category, name, topic):
        provisioned.append(name)
        return 888

    async def fake_find_or_create_text_channel(guild, category, name):
        return None

    async def fake_ensure_category(guild, name, existing, changes, key=None):
        return SN()

    adapter._find_or_create_forum = fake_find_or_create_forum
    adapter._find_or_create_text_channel = fake_find_or_create_text_channel
    adapter._ensure_category = fake_ensure_category

    fake_guild = SN(id=1)

    with (
        patch("teleclaude.adapters.discord_adapter.config") as mock_config,
        patch.object(adapter, "_resolve_guild", return_value=fake_guild),
        patch.object(adapter, "_persist_discord_channel_ids"),
        patch.object(adapter, "_persist_project_forum_ids"),
    ):
        mock_config.discord.categories = {}
        mock_config.computer.name = "testbox"
        mock_config.computer.get_all_trusted_dirs.return_value = []
        await adapter._ensure_discord_infrastructure()

    # Stale help_desk_channel_id cleared and Customer Sessions forum re-provisioned
    assert "Customer Sessions" in provisioned
    assert adapter._help_desk_channel_id == 888


# =========================================================================
# Forum Input Routing Tests
# =========================================================================


def test_resolve_forum_context_help_desk_via_parent_obj() -> None:
    """Message in a help desk thread (via parent.id) resolves to help_desk."""
    adapter = _make_adapter()
    adapter._help_desk_channel_id = 333
    adapter._all_sessions_channel_id = 444

    thread = FakeThread(thread_id=555, parent_id=333)  # parent.id = 333
    message = SimpleNamespace(channel=thread)

    with patch("teleclaude.adapters.discord_adapter.config") as mock_config:
        mock_config.computer.help_desk_dir = "/help"
        forum_type, path = adapter._resolve_forum_context(message)

    assert forum_type == "help_desk"
    assert path == "/help"


def test_resolve_forum_context_project_forum() -> None:
    """Message in a project forum thread resolves to project with correct path."""
    adapter = _make_adapter()
    adapter._help_desk_channel_id = 333
    adapter._all_sessions_channel_id = 444
    adapter._project_forum_map = {"/home/user/proj-a": 600}

    thread = FakeThread(thread_id=555, parent_id=600)
    message = SimpleNamespace(channel=thread)

    forum_type, path = adapter._resolve_forum_context(message)

    assert forum_type == "project"
    assert path == "/home/user/proj-a"


def test_resolve_forum_context_all_sessions() -> None:
    """Message in all-sessions forum resolves to all_sessions with first trusted dir."""
    from types import SimpleNamespace as SN

    adapter = _make_adapter()
    adapter._help_desk_channel_id = 333
    adapter._all_sessions_channel_id = 444

    thread = FakeThread(thread_id=555, parent_id=444)
    message = SimpleNamespace(channel=thread)

    td = SN(path="/home/user/workspace")
    with patch("teleclaude.adapters.discord_adapter.config") as mock_config:
        mock_config.computer.help_desk_dir = "/help"
        mock_config.computer.get_all_trusted_dirs.return_value = [td]
        forum_type, path = adapter._resolve_forum_context(message)

    assert forum_type == "all_sessions"
    assert path == "/home/user/workspace"


def test_resolve_forum_context_unknown_defaults_to_help_desk() -> None:
    """Message from an unknown channel defaults to help_desk forum type."""
    adapter = _make_adapter()
    adapter._help_desk_channel_id = 333
    adapter._all_sessions_channel_id = 444
    adapter._project_forum_map = {"/proj": 600}

    thread = FakeThread(thread_id=555, parent_id=999)  # 999 not managed
    message = SimpleNamespace(channel=thread)

    with patch("teleclaude.adapters.discord_adapter.config") as mock_config:
        mock_config.computer.help_desk_dir = "/help"
        forum_type, path = adapter._resolve_forum_context(message)

    assert forum_type == "help_desk"


@pytest.mark.asyncio
async def test_create_session_for_project_forum_uses_resolved_role() -> None:
    """Project forum messages create operator sessions without customer role."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        adapter = DiscordAdapter(client)
        client.register_adapter("discord", adapter)

    adapter._guild_id = None
    adapter._help_desk_channel_id = 333
    adapter._all_sessions_channel_id = 444
    adapter._project_forum_map = {"/home/user/proj": 600}

    session = _build_session()
    fake_db = MagicMock()
    fake_db.get_sessions_by_adapter_metadata = AsyncMock(side_effect=[[], []])
    fake_db.get_session = AsyncMock(return_value=session)
    fake_db.update_session = AsyncMock()

    fake_command_service = MagicMock()
    fake_command_service.create_session = AsyncMock(return_value={"session_id": session.session_id})
    fake_command_service.process_message = AsyncMock()

    # Message from a project forum thread (parent_id=600 matches _project_forum_map)
    thread = FakeThread(thread_id=700, parent_id=600)
    message = SimpleNamespace(
        id=12345,
        content="Start session",
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
    assert create_cmd.project_path == "/home/user/proj"
    assert "human_role" not in create_cmd.channel_metadata


@pytest.mark.asyncio
async def test_create_session_for_help_desk_still_uses_customer_role() -> None:
    """Help desk forum messages still create sessions with human_role='customer'."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        adapter = DiscordAdapter(client)
        client.register_adapter("discord", adapter)

    adapter._guild_id = None
    adapter._help_desk_channel_id = 333
    adapter._all_sessions_channel_id = 444

    session = _build_session()
    fake_db = MagicMock()
    fake_db.get_sessions_by_adapter_metadata = AsyncMock(side_effect=[[], []])
    fake_db.get_session = AsyncMock(return_value=session)
    fake_db.update_session = AsyncMock()

    fake_command_service = MagicMock()
    fake_command_service.create_session = AsyncMock(return_value={"session_id": session.session_id})
    fake_command_service.process_message = AsyncMock()

    # Thread whose parent.id matches help_desk_channel_id
    thread = FakeThread(thread_id=555, parent_id=333)
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
    assert create_cmd.channel_metadata["human_role"] == "customer"


@pytest.mark.asyncio
async def test_create_session_project_forum_defaults_member_when_unresolved() -> None:
    """Project forum messages do not inject customer/member role metadata."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        client = AdapterClient()
        adapter = DiscordAdapter(client)
        client.register_adapter("discord", adapter)

    adapter._guild_id = None
    adapter._help_desk_channel_id = 333
    adapter._all_sessions_channel_id = 444
    adapter._project_forum_map = {"/home/user/proj": 600}

    session = _build_session()
    fake_db = MagicMock()
    fake_db.get_sessions_by_adapter_metadata = AsyncMock(side_effect=[[], []])
    fake_db.get_session = AsyncMock(return_value=session)
    fake_db.update_session = AsyncMock()

    fake_command_service = MagicMock()
    fake_command_service.create_session = AsyncMock(return_value={"session_id": session.session_id})
    fake_command_service.process_message = AsyncMock()

    thread = FakeThread(thread_id=700, parent_id=600)
    message = SimpleNamespace(
        id=12345,
        content="Start session",
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

    create_cmd = fake_command_service.create_session.await_args.args[0]
    assert "human_role" not in create_cmd.channel_metadata


@pytest.mark.asyncio
async def test_create_session_for_message_uses_forum_derived_project() -> None:
    adapter = _make_adapter()
    adapter._forum_project_map = {600: "/home/user/proj-a"}
    adapter._get_enabled_agents = MagicMock(return_value=["codex"])  # type: ignore[method-assign]

    session = _build_session()
    fake_command_service = MagicMock()
    fake_command_service.create_session = AsyncMock(return_value={"session_id": session.session_id})
    fake_db = MagicMock()
    fake_db.get_session = AsyncMock(return_value=session)

    message = SimpleNamespace(
        author=SimpleNamespace(id=999001, display_name="Alice", name="alice"),
        channel=FakeThread(thread_id=700, parent_id=600),
    )

    with (
        patch("teleclaude.adapters.discord_adapter.db", fake_db),
        patch("teleclaude.adapters.discord_adapter.get_command_service", return_value=fake_command_service),
    ):
        await adapter._create_session_for_message(message, "999001", forum_type="project", project_path=None)

    create_cmd = fake_command_service.create_session.await_args.args[0]
    assert create_cmd.project_path == "/home/user/proj-a"
    assert create_cmd.auto_command == "agent codex"
    assert "human_role" not in create_cmd.channel_metadata


@pytest.mark.asyncio
async def test_handle_launcher_click_uses_parent_forum_project_mapping() -> None:
    adapter = _make_adapter()
    adapter._forum_project_map = {600: "/home/user/proj-a"}

    fake_command_service = MagicMock()
    fake_command_service.create_session = AsyncMock(return_value={"session_id": "sess-1"})
    interaction = SimpleNamespace(
        channel=FakeForumPostThread(thread_id=700, parent_id=600),
        channel_id=700,
        response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )

    with patch("teleclaude.adapters.discord_adapter.get_command_service", return_value=fake_command_service):
        await adapter._handle_launcher_click(interaction, "codex")

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    create_cmd = fake_command_service.create_session.await_args.args[0]
    assert create_cmd.project_path == "/home/user/proj-a"
    assert create_cmd.auto_command == "agent codex"
    interaction.followup.send.assert_awaited_once_with("Starting codex...", ephemeral=True)


@pytest.mark.asyncio
async def test_handle_cancel_slash_returns_error_when_no_session_found() -> None:
    adapter = _make_adapter()
    adapter._find_session = AsyncMock(return_value=None)  # type: ignore[method-assign]

    interaction = SimpleNamespace(
        channel=FakeThread(thread_id=444, parent_id=333),
        user=SimpleNamespace(id=999001),
        response=SimpleNamespace(send_message=AsyncMock()),
    )

    await adapter._handle_cancel_slash(interaction)

    interaction.response.send_message.assert_awaited_once_with("No active session in this thread.", ephemeral=True)


@pytest.mark.asyncio
async def test_handle_cancel_slash_dispatches_keys_when_session_exists() -> None:
    adapter = _make_adapter()
    session = _build_session()
    session.session_id = "sess-cancel"
    adapter._find_session = AsyncMock(return_value=session)  # type: ignore[method-assign]

    fake_command_service = MagicMock()
    fake_command_service.keys = AsyncMock()
    interaction = SimpleNamespace(
        channel=FakeThread(thread_id=444, parent_id=333),
        user=SimpleNamespace(id=999001),
        response=SimpleNamespace(send_message=AsyncMock()),
    )

    with patch("teleclaude.adapters.discord_adapter.get_command_service", return_value=fake_command_service):
        await adapter._handle_cancel_slash(interaction)

    interaction.response.send_message.assert_awaited_once_with("Sent CTRL+C", ephemeral=True)
    fake_command_service.keys.assert_awaited_once()
    cmd = fake_command_service.keys.await_args.args[0]
    assert isinstance(cmd, KeysCommand)
    assert cmd.session_id == "sess-cancel"
    assert cmd.key == "cancel"


@pytest.mark.asyncio
async def test_handle_cancel_slash_rejects_non_thread_channel() -> None:
    adapter = _make_adapter()
    adapter._find_session = AsyncMock(return_value=_build_session())  # type: ignore[method-assign]

    interaction = SimpleNamespace(
        channel=SimpleNamespace(id=444),
        user=SimpleNamespace(id=999001),
        response=SimpleNamespace(send_message=AsyncMock()),
    )

    await adapter._handle_cancel_slash(interaction)

    interaction.response.send_message.assert_awaited_once_with("No active session in this thread.", ephemeral=True)
    adapter._find_session.assert_not_awaited()


# ---------------------------------------------------------------------------
# Discord _handle_session_status (I2)
# ---------------------------------------------------------------------------


def _build_session_with_discord_thread(thread_id: int = 555, status_message_id: str | None = None) -> Session:
    meta = SessionAdapterMetadata()
    discord_meta = meta.get_ui().get_discord()
    discord_meta.thread_id = thread_id
    discord_meta.status_message_id = status_message_id
    return Session(
        session_id="sess-status-discord",
        computer_name="local",
        tmux_session_name="tc_status",
        last_input_origin=InputOrigin.DISCORD.value,
        title="Discord: Status Test",
        adapter_metadata=meta,
    )


def _make_status_context(session_id: str = "sess-status-discord") -> SessionStatusContext:
    return SessionStatusContext(
        session_id=session_id,
        status="active_output",
        reason="output_observed",
        timestamp="2026-01-01T00:00:00+00:00",
    )


def _make_updated_context(
    session_id: str = "sess-status-discord",
    *,
    native_session_id: str | None = "native-thread-123",
) -> SessionUpdatedContext:
    updated_fields: SessionUpdatedFields = {"native_session_id": native_session_id}
    return SessionUpdatedContext(session_id=session_id, updated_fields=updated_fields)


@pytest.mark.asyncio
async def test_discord_handle_session_status_sends_new_message_when_no_existing() -> None:
    """Sends a new status message and persists the returned message ID."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        adapter = DiscordAdapter(AdapterClient())

    session = _build_session_with_discord_thread(thread_id=555, status_message_id=None)
    context = _make_status_context()

    fake_db = MagicMock()
    fake_db.get_session = AsyncMock(return_value=session)
    fake_db.update_session = AsyncMock()

    with (
        patch("teleclaude.adapters.discord_adapter.db", fake_db),
        patch("teleclaude.adapters.ui_adapter.db", fake_db),
        patch.object(adapter, "send_message", new_callable=AsyncMock, return_value="9001") as mock_send,
        patch.object(adapter, "edit_message", new_callable=AsyncMock) as mock_edit,
    ):
        await adapter._handle_session_status("SESSION_STATUS", context)

    mock_send.assert_awaited_once()
    mock_edit.assert_not_awaited()
    assert session.get_metadata().get_ui().get_discord().status_message_id == "9001"
    fake_db.update_session.assert_awaited_once()


@pytest.mark.asyncio
async def test_discord_handle_session_status_edits_existing_message() -> None:
    """Edits the existing status message in-place when status_message_id is set."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        adapter = DiscordAdapter(AdapterClient())

    session = _build_session_with_discord_thread(thread_id=555, status_message_id="7777")
    context = _make_status_context()

    fake_db = MagicMock()
    fake_db.get_session = AsyncMock(return_value=session)
    fake_db.update_session = AsyncMock()

    with (
        patch("teleclaude.adapters.discord_adapter.db", fake_db),
        patch("teleclaude.adapters.ui_adapter.db", fake_db),
        patch.object(adapter, "send_message", new_callable=AsyncMock) as mock_send,
        patch.object(adapter, "edit_message", new_callable=AsyncMock, return_value=True) as mock_edit,
    ):
        await adapter._handle_session_status("SESSION_STATUS", context)

    mock_edit.assert_awaited_once()
    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_discord_handle_session_status_falls_back_to_send_when_edit_fails() -> None:
    """Falls back to send when edit returns False, clears old ID, persists new one."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        adapter = DiscordAdapter(AdapterClient())

    session = _build_session_with_discord_thread(thread_id=555, status_message_id="old-id")
    context = _make_status_context()

    fake_db = MagicMock()
    fake_db.get_session = AsyncMock(return_value=session)
    fake_db.update_session = AsyncMock()

    with (
        patch("teleclaude.adapters.discord_adapter.db", fake_db),
        patch("teleclaude.adapters.ui_adapter.db", fake_db),
        patch.object(adapter, "send_message", new_callable=AsyncMock, return_value="new-id") as mock_send,
        patch.object(adapter, "edit_message", new_callable=AsyncMock, return_value=False) as mock_edit,
    ):
        await adapter._handle_session_status("SESSION_STATUS", context)

    mock_edit.assert_awaited_once()
    mock_send.assert_awaited_once()
    assert session.get_metadata().get_ui().get_discord().status_message_id == "new-id"


@pytest.mark.asyncio
async def test_discord_handle_session_status_skips_when_no_thread() -> None:
    """Does nothing when the session has no Discord thread_id."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        adapter = DiscordAdapter(AdapterClient())

    # Session with no thread_id set
    session = _build_session()
    context = _make_status_context(session_id=session.session_id)

    fake_db = MagicMock()
    fake_db.get_session = AsyncMock(return_value=session)
    fake_db.update_session = AsyncMock()

    with (
        patch("teleclaude.adapters.discord_adapter.db", fake_db),
        patch("teleclaude.adapters.ui_adapter.db", fake_db),
        patch.object(adapter, "send_message", new_callable=AsyncMock) as mock_send,
        patch.object(adapter, "edit_message", new_callable=AsyncMock) as mock_edit,
    ):
        await adapter._handle_session_status("SESSION_STATUS", context)

    mock_send.assert_not_awaited()
    mock_edit.assert_not_awaited()
    fake_db.update_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_discord_session_updated_refreshes_thread_topper_with_native_id() -> None:
    """native_session_id update should edit the tracked thread topper message."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        adapter = DiscordAdapter(AdapterClient())

    session = _build_session_with_discord_thread(thread_id=555, status_message_id=None)
    session.native_session_id = "native-thread-999"
    session.get_metadata().get_ui().get_discord().thread_topper_message_id = "4444"
    context = _make_updated_context(session_id=session.session_id, native_session_id=session.native_session_id)

    fake_db = MagicMock()
    fake_db.get_session = AsyncMock(return_value=session)
    fake_db.update_session = AsyncMock()

    with (
        patch("teleclaude.adapters.discord_adapter.db", fake_db),
        patch("teleclaude.adapters.ui_adapter.db", fake_db),
        patch.object(adapter.client, "update_channel_title", new_callable=AsyncMock) as mock_update_title,
        patch.object(adapter, "send_message", new_callable=AsyncMock) as mock_send,
        patch.object(adapter, "edit_message", new_callable=AsyncMock, return_value=True) as mock_edit,
    ):
        await adapter._handle_session_updated("session_updated", context)

    mock_update_title.assert_not_awaited()
    mock_send.assert_not_awaited()
    mock_edit.assert_awaited_once()
    args = mock_edit.await_args.args
    assert args[1] == "4444"
    assert "ai: native-thread-999" in args[2]
    fake_db.update_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_discord_session_updated_uses_thread_id_when_topper_message_missing() -> None:
    """When topper_message_id is absent, fallback to thread_id and persist it."""
    with patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule):
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        adapter = DiscordAdapter(AdapterClient())

    session = _build_session_with_discord_thread(thread_id=555, status_message_id=None)
    session.native_session_id = "native-thread-abc"
    session.get_metadata().get_ui().get_discord().thread_topper_message_id = None
    context = _make_updated_context(session_id=session.session_id, native_session_id=session.native_session_id)

    fake_db = MagicMock()
    fake_db.get_session = AsyncMock(return_value=session)
    fake_db.update_session = AsyncMock()

    with (
        patch("teleclaude.adapters.discord_adapter.db", fake_db),
        patch("teleclaude.adapters.ui_adapter.db", fake_db),
        patch.object(adapter.client, "update_channel_title", new_callable=AsyncMock) as mock_update_title,
        patch.object(adapter, "edit_message", new_callable=AsyncMock, return_value=True) as mock_edit,
    ):
        await adapter._handle_session_updated("session_updated", context)

    mock_update_title.assert_not_awaited()
    mock_edit.assert_awaited_once()
    args = mock_edit.await_args.args
    assert args[1] == "555"
    assert session.get_metadata().get_ui().get_discord().thread_topper_message_id == "555"
    fake_db.update_session.assert_awaited_once()
