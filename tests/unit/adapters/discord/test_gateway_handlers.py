from __future__ import annotations

from types import SimpleNamespace

import pytest

from teleclaude.adapters.discord.gateway_handlers import GatewayHandlersMixin

pytestmark = pytest.mark.unit


class DummyGatewayHandlers(GatewayHandlersMixin):
    def __init__(self) -> None:
        self._help_desk_channel_id = 100
        self._all_sessions_channel_id = 200
        self._project_forum_map = {"proj": 300, "unmapped": None}
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
