from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.adapters.discord.infra import InfrastructureMixin

pytestmark = pytest.mark.unit


class DummyDiscordError(Exception):
    def __init__(self, message: str, *, code: int | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class DummyInfrastructure(InfrastructureMixin):
    def __init__(self) -> None:
        self._client = object()
        self._discord = SimpleNamespace(DiscordException=DummyDiscordError)
        self._parse_optional_int = lambda value: (
            int(str(value).strip()) if value is not None and str(value).strip().isdigit() else None
        )
        self._get_channel = AsyncMock(return_value=SimpleNamespace(id=123))
        self._get_enabled_agents = lambda: ["alpha", "beta"]
        self._handle_launcher_click = AsyncMock()
        self._require_async_callable = lambda fn, *, label: fn
        self._is_forum_channel = lambda channel: True

    @property
    def _multi_agent(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_ensure_category_skips_creation_when_create_disabled_and_absent() -> None:
    adapter = DummyInfrastructure()
    adapter._find_or_create_category = AsyncMock()
    guild = SimpleNamespace(categories=[SimpleNamespace(name="Other", id=1)])

    result = await adapter._ensure_category(guild, "Help Desk", {}, {}, create=False)

    assert result is None
    adapter._find_or_create_category.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_category_resolves_existing_when_create_disabled() -> None:
    adapter = DummyInfrastructure()
    adapter._find_or_create_category = AsyncMock()
    existing_cat = SimpleNamespace(name="Help Desk", id=77)
    guild = SimpleNamespace(categories=[existing_cat])
    cat_changes: dict[str, int] = {}

    result = await adapter._ensure_category(guild, "Help Desk", {}, cat_changes, create=False)

    assert result is existing_cat
    assert cat_changes == {"help_desk": 77}
    adapter._find_or_create_category.assert_not_called()


def _wire_infrastructure_spies(adapter: DummyInfrastructure) -> None:
    adapter._guild_id = 123
    adapter._announcements_channel_id = None
    adapter._general_channel_id = None
    adapter._help_desk_channel_id = None
    adapter._escalation_channel_id = None
    adapter._operator_chat_channel_id = None
    adapter._all_sessions_channel_id = None
    adapter._team_channel_map = {}
    adapter._resolve_guild = AsyncMock(return_value=SimpleNamespace())
    adapter._validate_channel_id = AsyncMock(return_value=None)
    adapter._ensure_category = AsyncMock(return_value=SimpleNamespace(id=1))
    adapter._find_or_create_forum = AsyncMock(return_value=None)
    adapter._find_or_create_text_channel = AsyncMock(return_value=None)
    adapter._ensure_project_forums = AsyncMock()
    adapter._sync_project_forum_positions = AsyncMock()
    adapter._build_project_forum_map = MagicMock()
    adapter._ensure_team_channels = AsyncMock()
    adapter._persist_discord_channel_ids = MagicMock()


def _create_flags_by_name(mock: AsyncMock, name_index: int) -> dict[object, bool]:
    return {call.args[name_index]: call.kwargs.get("create", True) for call in mock.await_args_list}


@pytest.mark.asyncio
async def test_ensure_infrastructure_non_master_never_creates_shared_channels() -> None:
    adapter = DummyInfrastructure()
    _wire_infrastructure_spies(adapter)
    fake_config = SimpleNamespace(
        discord=SimpleNamespace(categories={}),
        computer=SimpleNamespace(name="WorkerMac", is_master=False),
    )
    fake_people = SimpleNamespace(people=[SimpleNamespace(name="Alice")])

    with (
        patch("teleclaude.adapters.discord.infra.config", fake_config),
        patch("teleclaude.adapters.discord.infra.load_global_config", return_value=fake_people),
    ):
        await adapter._ensure_discord_infrastructure()

    category_create = _create_flags_by_name(adapter._ensure_category, 1)
    forum_create = _create_flags_by_name(adapter._find_or_create_forum, 2)
    text_create = _create_flags_by_name(adapter._find_or_create_text_channel, 2)

    assert category_create["Operations"] is False
    assert category_create["Help Desk"] is False
    assert category_create["Team"] is False
    assert category_create["Projects - WorkerMac"] is True

    assert forum_create["Customer Sessions"] is False
    assert forum_create["Escalations"] is False
    assert forum_create["Unknown"] is True

    assert text_create["announcements"] is False
    assert text_create["general"] is False
    assert text_create["operator-chat"] is False

    assert adapter._ensure_team_channels.await_args.kwargs.get("create", True) is False
    adapter._ensure_project_forums.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_infrastructure_master_creates_shared_channels() -> None:
    adapter = DummyInfrastructure()
    _wire_infrastructure_spies(adapter)
    fake_config = SimpleNamespace(
        discord=SimpleNamespace(categories={}),
        computer=SimpleNamespace(name="MasterMac", is_master=True),
    )
    fake_people = SimpleNamespace(people=[SimpleNamespace(name="Alice")])

    with (
        patch("teleclaude.adapters.discord.infra.config", fake_config),
        patch("teleclaude.adapters.discord.infra.load_global_config", return_value=fake_people),
    ):
        await adapter._ensure_discord_infrastructure()

    category_create = _create_flags_by_name(adapter._ensure_category, 1)
    forum_create = _create_flags_by_name(adapter._find_or_create_forum, 2)
    text_create = _create_flags_by_name(adapter._find_or_create_text_channel, 2)

    assert category_create["Operations"] is True
    assert category_create["Help Desk"] is True
    assert category_create["Team"] is True

    assert forum_create["Customer Sessions"] is True
    assert forum_create["Escalations"] is True

    assert text_create["announcements"] is True
    assert text_create["operator-chat"] is True

    assert adapter._ensure_team_channels.await_args.kwargs.get("create", True) is True


def test_extract_forum_thread_result_handles_tuple_and_thread_object() -> None:
    adapter = DummyInfrastructure()
    thread = SimpleNamespace(id=1)
    starter_message = SimpleNamespace(id=2)

    tuple_result = adapter._extract_forum_thread_result((thread, starter_message))
    object_result = adapter._extract_forum_thread_result(thread)

    assert tuple_result == (thread, starter_message)
    assert object_result == (thread, None)


@pytest.mark.asyncio
async def test_validate_channel_id_returns_id_only_for_resolvable_channels() -> None:
    adapter = DummyInfrastructure()

    assert await adapter._validate_channel_id(None) is None
    assert await adapter._validate_channel_id(123) == 123

    adapter._get_channel = AsyncMock(return_value=None)

    assert await adapter._validate_channel_id(123) is None


def test_resolve_parent_forum_id_prefers_parent_id_then_parent_object() -> None:
    adapter = DummyInfrastructure()

    assert adapter._resolve_parent_forum_id(SimpleNamespace(parent_id="88", parent=SimpleNamespace(id="99"))) == 88
    assert adapter._resolve_parent_forum_id(SimpleNamespace(parent_id=None, parent=SimpleNamespace(id="99"))) == 99
    assert adapter._resolve_parent_forum_id(SimpleNamespace(parent_id=None, parent=None)) is None


@pytest.mark.asyncio
async def test_build_session_launcher_view_uses_enabled_agents_for_button_labels_and_ids(
    snapshot: SnapshotAssertion,
) -> None:
    adapter = DummyInfrastructure()

    view = adapter._build_session_launcher_view()
    buttons = [(child.label, child.custom_id) for child in view.children]

    assert buttons == snapshot


@pytest.mark.asyncio
async def test_post_or_update_launcher_does_not_recreate_when_existing_launcher_fetch_fails() -> None:
    adapter = DummyInfrastructure()
    forum = SimpleNamespace(id=99, create_thread=AsyncMock())
    thread = SimpleNamespace(
        id=42,
        parent_id=99,
        fetch_message=AsyncMock(side_effect=DummyDiscordError("discord unavailable", status=503)),
    )
    adapter._get_channel = AsyncMock(side_effect=[forum, thread])
    fake_db = MagicMock()
    fake_db.get_system_setting = AsyncMock(side_effect=["42", "77"])
    fake_db.set_system_setting = AsyncMock()

    with patch("teleclaude.adapters.discord.infra.db", fake_db):
        await adapter._post_or_update_launcher(99)

    thread.fetch_message.assert_awaited_once_with(77)
    forum.create_thread.assert_not_called()
    fake_db.set_system_setting.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_or_update_launcher_recreates_legacy_only_records(snapshot: SnapshotAssertion) -> None:
    adapter = DummyInfrastructure()
    launcher_message = SimpleNamespace(id=88, pin=AsyncMock())
    launcher_thread = SimpleNamespace(id=42, edit=AsyncMock())
    forum = SimpleNamespace(id=99, create_thread=AsyncMock(return_value=(launcher_thread, launcher_message)))
    adapter._get_channel = AsyncMock(return_value=forum)
    fake_db = MagicMock()
    fake_db.get_system_setting = AsyncMock(side_effect=[None, None, "77"])
    fake_db.set_system_setting = AsyncMock()

    with patch("teleclaude.adapters.discord.infra.db", fake_db):
        await adapter._post_or_update_launcher(99)

    forum.create_thread.assert_awaited_once()
    settings_writes = [(call.args[0], call.args[1]) for call in fake_db.set_system_setting.await_args_list]
    assert settings_writes == snapshot


@pytest.mark.asyncio
async def test_post_or_update_launcher_surfaces_deleted_existing_launcher() -> None:
    adapter = DummyInfrastructure()
    forum = SimpleNamespace(id=99, create_thread=AsyncMock())
    deleted_message_error = DummyDiscordError("unknown message", code=10008, status=404)
    thread = SimpleNamespace(id=42, parent_id=99, fetch_message=AsyncMock(side_effect=deleted_message_error))
    adapter._get_channel = AsyncMock(side_effect=[forum, thread])
    fake_db = MagicMock()
    fake_db.get_system_setting = AsyncMock(side_effect=["42", "77"])
    fake_db.set_system_setting = AsyncMock()

    with patch("teleclaude.adapters.discord.infra.db", fake_db):
        with pytest.raises(DummyDiscordError) as exc_info:
            await adapter._post_or_update_launcher(99)

    assert exc_info.value is deleted_message_error
    forum.create_thread.assert_not_called()
    fake_db.set_system_setting.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_or_update_launcher_propagates_unexpected_existing_launcher_errors() -> None:
    adapter = DummyInfrastructure()
    forum = SimpleNamespace(id=99, create_thread=AsyncMock())
    unexpected_error = RuntimeError("contract error")
    thread = SimpleNamespace(id=42, parent_id=99, fetch_message=AsyncMock(side_effect=unexpected_error))
    adapter._get_channel = AsyncMock(side_effect=[forum, thread])
    fake_db = MagicMock()
    fake_db.get_system_setting = AsyncMock(side_effect=["42", "77"])
    fake_db.set_system_setting = AsyncMock()

    with patch("teleclaude.adapters.discord.infra.db", fake_db):
        with pytest.raises(RuntimeError) as exc_info:
            await adapter._post_or_update_launcher(99)

    assert exc_info.value is unexpected_error
    forum.create_thread.assert_not_called()
    fake_db.set_system_setting.assert_not_awaited()


@pytest.mark.asyncio
async def test_pin_launcher_thread_suppresses_pin_limit_warning(caplog: pytest.LogCaptureFixture) -> None:
    adapter = DummyInfrastructure()
    thread = SimpleNamespace(
        id=42,
        edit=AsyncMock(
            side_effect=DummyDiscordError(
                "400 Bad Request (error code: 30047): Maximum number pinned threads in this channel reached (1).",
                code=30047,
            )
        ),
    )

    with caplog.at_level("INFO"):
        await adapter._pin_launcher_thread(thread, forum_id=99)

    info_records = [record for record in caplog.records if record.levelno == logging.INFO]
    warning_records = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert [record.args for record in info_records] == [(42, 99)]
    assert warning_records == []


@pytest.mark.asyncio
async def test_pin_launcher_thread_logs_unexpected_failures(caplog: pytest.LogCaptureFixture) -> None:
    adapter = DummyInfrastructure()
    pin_error = DummyDiscordError("boom", code=99999)
    thread = SimpleNamespace(id=42, edit=AsyncMock(side_effect=pin_error))

    with caplog.at_level("WARNING"):
        await adapter._pin_launcher_thread(thread, forum_id=99)

    warning_records = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warning_records) == 1
    assert warning_records[0].args == (42, 99, pin_error)


# Per-computer forum scoping: discord.CategoryChannel.channels derives from
# guild.channels filtered by category_id, so tests model the same shape —
# every forum in the guild carries the category_id it actually belongs to.

MOZMINI_CAT_ID = 200
MOZBOOK_CAT_ID = 300


def _make_forum(*, id: int, name: str, category_id: int, position: int = 0) -> SimpleNamespace:
    return SimpleNamespace(id=id, name=name, category_id=category_id, position=position, edit=AsyncMock())


def _make_category(id: int) -> SimpleNamespace:
    return SimpleNamespace(id=id)


@pytest.mark.asyncio
async def test_find_or_create_forum_creates_new_when_same_name_lives_in_another_category() -> None:
    adapter = DummyInfrastructure()
    foreign_forum = _make_forum(id=10, name="TeleClaude", category_id=MOZBOOK_CAT_ID)
    created_forum = SimpleNamespace(id=20)
    mozmini_cat = _make_category(MOZMINI_CAT_ID)
    guild = SimpleNamespace(
        channels=[foreign_forum],
        create_forum=AsyncMock(return_value=created_forum),
    )

    forum_id = await adapter._find_or_create_forum(guild, mozmini_cat, "TeleClaude", "Sessions for TeleClaude")

    assert forum_id == 20
    guild.create_forum.assert_awaited_once_with(
        name="TeleClaude", topic="Sessions for TeleClaude", category=mozmini_cat
    )


@pytest.mark.asyncio
async def test_find_or_create_forum_returns_existing_forum_in_target_category() -> None:
    adapter = DummyInfrastructure()
    own_forum = _make_forum(id=20, name="TeleClaude", category_id=MOZMINI_CAT_ID)
    mozmini_cat = _make_category(MOZMINI_CAT_ID)
    guild = SimpleNamespace(channels=[own_forum], create_forum=AsyncMock())

    forum_id = await adapter._find_or_create_forum(guild, mozmini_cat, "TeleClaude", "Sessions for TeleClaude")

    assert forum_id == 20
    guild.create_forum.assert_not_awaited()


@pytest.mark.asyncio
async def test_find_or_create_forum_skips_creation_when_create_disabled_and_absent() -> None:
    adapter = DummyInfrastructure()
    mozmini_cat = _make_category(MOZMINI_CAT_ID)
    guild = SimpleNamespace(channels=[], create_forum=AsyncMock())

    forum_id = await adapter._find_or_create_forum(
        guild, mozmini_cat, "Customer Sessions", "Customer support sessions", create=False
    )

    assert forum_id is None
    guild.create_forum.assert_not_awaited()


@pytest.mark.asyncio
async def test_find_or_create_forum_refuses_without_category() -> None:
    adapter = DummyInfrastructure()
    guild = SimpleNamespace(channels=[], create_forum=AsyncMock())

    forum_id = await adapter._find_or_create_forum(guild, None, "TeleClaude", "Sessions for TeleClaude")

    assert forum_id is None
    guild.create_forum.assert_not_awaited()


@pytest.mark.asyncio
async def test_validate_forum_in_category_accepts_forum_in_target_category() -> None:
    adapter = DummyInfrastructure()
    own_forum = _make_forum(id=20, name="TeleClaude", category_id=MOZMINI_CAT_ID)
    adapter._get_channel = AsyncMock(return_value=own_forum)
    mozmini_cat = _make_category(MOZMINI_CAT_ID)

    assert await adapter._validate_forum_in_category(20, mozmini_cat) == 20


@pytest.mark.asyncio
async def test_validate_forum_in_category_rejects_forum_in_other_category() -> None:
    adapter = DummyInfrastructure()
    foreign_forum = _make_forum(id=10, name="TeleClaude", category_id=MOZBOOK_CAT_ID)
    adapter._get_channel = AsyncMock(return_value=foreign_forum)
    mozmini_cat = _make_category(MOZMINI_CAT_ID)

    assert await adapter._validate_forum_in_category(10, mozmini_cat) is None


@pytest.mark.asyncio
async def test_validate_forum_in_category_rejects_missing_channel() -> None:
    adapter = DummyInfrastructure()
    adapter._get_channel = AsyncMock(return_value=None)
    mozmini_cat = _make_category(MOZMINI_CAT_ID)

    assert await adapter._validate_forum_in_category(999, mozmini_cat) is None


@pytest.mark.asyncio
async def test_ensure_project_forums_keeps_stored_forum_in_own_category() -> None:
    adapter = DummyInfrastructure()
    own_forum = _make_forum(id=20, name="TeleClaude", category_id=MOZMINI_CAT_ID)
    adapter._get_channel = AsyncMock(return_value=own_forum)
    mozmini_cat = _make_category(MOZMINI_CAT_ID)
    trusted_dir = SimpleNamespace(name="TeleClaude", desc="App", path="/repo/app", discord_forum=20)
    computer = SimpleNamespace(name="mozmini", get_all_trusted_dirs=lambda: [trusted_dir])
    guild = SimpleNamespace(channels=[own_forum], create_forum=AsyncMock())
    persist = MagicMock()

    with (
        patch("teleclaude.adapters.discord.infra.config.computer", computer),
        patch.object(adapter, "_persist_project_forum_ids", persist),
    ):
        await adapter._ensure_project_forums(guild, mozmini_cat)

    assert trusted_dir.discord_forum == 20
    guild.create_forum.assert_not_awaited()
    persist.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_project_forums_recreates_stored_forum_in_foreign_category() -> None:
    adapter = DummyInfrastructure()
    foreign_forum = _make_forum(id=10, name="TeleClaude", category_id=MOZBOOK_CAT_ID)
    created_forum = SimpleNamespace(id=42)
    adapter._get_channel = AsyncMock(return_value=foreign_forum)
    mozmini_cat = _make_category(MOZMINI_CAT_ID)
    trusted_dir = SimpleNamespace(name="TeleClaude", desc="App", path="/repo/app", discord_forum=10)
    computer = SimpleNamespace(name="mozmini", get_all_trusted_dirs=lambda: [trusted_dir])
    guild = SimpleNamespace(channels=[foreign_forum], create_forum=AsyncMock(return_value=created_forum))
    persist = MagicMock()

    with (
        patch("teleclaude.adapters.discord.infra.config.computer", computer),
        patch.object(adapter, "_persist_project_forum_ids", persist),
    ):
        await adapter._ensure_project_forums(guild, mozmini_cat)

    assert trusted_dir.discord_forum == 42
    guild.create_forum.assert_awaited_once_with(name="TeleClaude", topic="App", category=mozmini_cat)
    persist.assert_called_once_with([("TeleClaude", 42)])


@pytest.mark.asyncio
async def test_ensure_project_forums_creates_when_stored_id_missing() -> None:
    adapter = DummyInfrastructure()
    created_forum = SimpleNamespace(id=42)
    mozmini_cat = _make_category(MOZMINI_CAT_ID)
    trusted_dir = SimpleNamespace(name="TeleClaude", desc="App", path="/repo/app", discord_forum=None)
    computer = SimpleNamespace(name="mozmini", get_all_trusted_dirs=lambda: [trusted_dir])
    guild = SimpleNamespace(channels=[], create_forum=AsyncMock(return_value=created_forum))
    persist = MagicMock()

    with (
        patch("teleclaude.adapters.discord.infra.config.computer", computer),
        patch.object(adapter, "_persist_project_forum_ids", persist),
    ):
        await adapter._ensure_project_forums(guild, mozmini_cat)

    assert trusted_dir.discord_forum == 42
    persist.assert_called_once_with([("TeleClaude", 42)])


@pytest.mark.asyncio
async def test_ensure_project_forums_skips_when_category_missing() -> None:
    adapter = DummyInfrastructure()
    trusted_dir = SimpleNamespace(name="TeleClaude", desc="App", path="/repo/app", discord_forum=20)
    computer = SimpleNamespace(name="mozmini", get_all_trusted_dirs=lambda: [trusted_dir])
    guild = SimpleNamespace(channels=[], create_forum=AsyncMock())
    persist = MagicMock()

    with (
        patch("teleclaude.adapters.discord.infra.config.computer", computer),
        patch.object(adapter, "_persist_project_forum_ids", persist),
    ):
        await adapter._ensure_project_forums(guild, None)

    assert trusted_dir.discord_forum == 20  # unchanged
    guild.create_forum.assert_not_awaited()
    persist.assert_not_called()


@pytest.mark.asyncio
async def test_sync_project_forum_positions_leaves_foreign_forum_alone() -> None:
    adapter = DummyInfrastructure()
    foreign_forum = _make_forum(id=10, name="TeleClaude", category_id=MOZBOOK_CAT_ID, position=5)
    adapter._get_channel = AsyncMock(return_value=foreign_forum)
    mozmini_cat = _make_category(MOZMINI_CAT_ID)
    trusted_dir = SimpleNamespace(name="TeleClaude", desc="App", path="/repo/app", discord_forum=10)
    computer = SimpleNamespace(name="mozmini", get_all_trusted_dirs=lambda: [trusted_dir])

    with patch("teleclaude.adapters.discord.infra.config.computer", computer):
        await adapter._sync_project_forum_positions(mozmini_cat)

    foreign_forum.edit.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_project_forum_positions_reorders_local_forum_without_moving() -> None:
    adapter = DummyInfrastructure()
    own_forum = _make_forum(id=20, name="TeleClaude", category_id=MOZMINI_CAT_ID, position=7)
    adapter._get_channel = AsyncMock(return_value=own_forum)
    mozmini_cat = _make_category(MOZMINI_CAT_ID)
    trusted_dir = SimpleNamespace(name="TeleClaude", desc="App", path="/repo/app", discord_forum=20)
    computer = SimpleNamespace(name="mozmini", get_all_trusted_dirs=lambda: [trusted_dir])

    with patch("teleclaude.adapters.discord.infra.config.computer", computer):
        await adapter._sync_project_forum_positions(mozmini_cat)

    own_forum.edit.assert_awaited_once_with(position=0)


@pytest.mark.asyncio
async def test_sync_project_forum_positions_no_op_when_already_ordered() -> None:
    adapter = DummyInfrastructure()
    own_forum = _make_forum(id=20, name="TeleClaude", category_id=MOZMINI_CAT_ID, position=0)
    adapter._get_channel = AsyncMock(return_value=own_forum)
    mozmini_cat = _make_category(MOZMINI_CAT_ID)
    trusted_dir = SimpleNamespace(name="TeleClaude", desc="App", path="/repo/app", discord_forum=20)
    computer = SimpleNamespace(name="mozmini", get_all_trusted_dirs=lambda: [trusted_dir])

    with patch("teleclaude.adapters.discord.infra.config.computer", computer):
        await adapter._sync_project_forum_positions(mozmini_cat)

    own_forum.edit.assert_not_awaited()
