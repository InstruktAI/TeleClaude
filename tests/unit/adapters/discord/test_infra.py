from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from teleclaude.adapters.discord.infra import InfrastructureMixin

pytestmark = pytest.mark.unit


class DummyDiscordError(Exception):
    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class DummyInfrastructure(InfrastructureMixin):
    def __init__(self) -> None:
        self._parse_optional_int = lambda value: (
            int(str(value).strip()) if value is not None and str(value).strip().isdigit() else None
        )
        self._get_channel = AsyncMock(return_value=SimpleNamespace(id=123))
        self._get_enabled_agents = lambda: ["alpha", "beta"]
        self._handle_launcher_click = AsyncMock()
        self._require_async_callable = lambda fn, *, label: fn


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
async def test_build_session_launcher_view_uses_enabled_agents_for_button_labels_and_ids() -> None:
    adapter = DummyInfrastructure()

    view = adapter._build_session_launcher_view()
    buttons = [(child.label, child.custom_id) for child in view.children]

    assert buttons == [("Alpha", "launch:alpha"), ("Beta", "launch:beta")]


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

    assert "Skipped pinning Discord launcher thread 42 in forum 99" in caplog.text
    assert "Failed to pin Discord launcher thread 42 in forum 99" not in caplog.text


@pytest.mark.asyncio
async def test_pin_launcher_thread_logs_unexpected_failures(caplog: pytest.LogCaptureFixture) -> None:
    adapter = DummyInfrastructure()
    thread = SimpleNamespace(id=42, edit=AsyncMock(side_effect=DummyDiscordError("boom", code=99999)))

    with caplog.at_level("WARNING"):
        await adapter._pin_launcher_thread(thread, forum_id=99)

    assert "Failed to pin Discord launcher thread 42 in forum 99: boom" in caplog.text
