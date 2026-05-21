from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.adapters.discord.infra import InfrastructureMixin

pytestmark = pytest.mark.unit


class DummyDiscordError(Exception):
    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


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
        fetch_message=AsyncMock(side_effect=DummyDiscordError("discord unavailable")),
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
