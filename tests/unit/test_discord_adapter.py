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
