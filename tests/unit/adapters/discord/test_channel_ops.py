"""Tests for teleclaude.adapters.discord.channel_ops."""
# pylint: disable=missing-class-docstring,missing-function-docstring,protected-access,too-few-public-methods,too-many-instance-attributes

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.adapters.discord.channel_ops import ChannelOperationsMixin
from teleclaude.core.models import ChannelMetadata, DiscordAdapterMetadata, Session

pytestmark = pytest.mark.unit


class DummyChannelOperations(ChannelOperationsMixin):
    def __init__(self) -> None:
        self._help_desk_channel_id = 100
        self._all_sessions_channel_id = 200
        self._team_channel_map = {300: "team/project"}
        self._project_forum_map = {"proj": 400}
        self._trusted_dirs = [SimpleNamespace(path="/workspace/proj", discord_forum=400)]
        self._parse_optional_int = lambda value: (
            int(str(value).strip()) if value is not None and str(value).strip().isdigit() else None
        )
        # Forum-thread stub attributes (overridden per test)
        self._client: object = None
        self._get_channel: AsyncMock = AsyncMock()
        self._is_forum_channel = staticmethod(lambda ch: False)
        self._create_forum_thread: AsyncMock = AsyncMock()


def _make_session(*, human_role: str | None) -> Session:
    return Session(
        session_id="session-1",
        computer_name="machine",
        tmux_session_name="tmux-session",
        title="Session",
        human_role=human_role,
    )


def _make_message(*, channel_id: str, parent_id: str | None, parent_obj_id: str | None) -> SimpleNamespace:
    parent = None if parent_obj_id is None else SimpleNamespace(id=parent_obj_id)
    channel = SimpleNamespace(id=channel_id, parent_id=parent_id, parent=parent)
    return SimpleNamespace(channel=channel)


def test_is_customer_session_matches_customer_role_only() -> None:
    adapter = DummyChannelOperations()

    assert adapter._is_customer_session(_make_session(human_role="customer")) is True
    assert adapter._is_customer_session(_make_session(human_role="admin")) is False
    assert adapter._is_customer_session(_make_session(human_role=None)) is False


def test_resolve_forum_context_prefers_team_channel_mapping() -> None:
    adapter = DummyChannelOperations()

    forum_type, forum_path = adapter._resolve_forum_context(
        _make_message(channel_id="300", parent_id=None, parent_obj_id=None)
    )

    assert forum_type == "team"
    assert forum_path == "team/project"


def test_resolve_forum_context_maps_project_forum_parent_to_project_name() -> None:
    adapter = DummyChannelOperations()

    forum_type, forum_path = adapter._resolve_forum_context(
        _make_message(channel_id="401", parent_id="400", parent_obj_id="400")
    )

    assert forum_type == "project"
    assert forum_path == "proj"


def test_resolve_forum_context_falls_back_to_help_desk_for_unknown_parent() -> None:
    adapter = DummyChannelOperations()

    forum_type, forum_path = adapter._resolve_forum_context(
        _make_message(channel_id="999", parent_id="999", parent_obj_id="999")
    )

    assert forum_type == "help_desk"
    assert Path(forum_path).name == "help-desk"


@pytest.mark.asyncio
async def test_create_channel_persists_forum_thread_metadata() -> None:
    """Forum-thread path must write thread_id and channel_id to origin_metadata itself.

    Core no longer provides a fallback metadata write; Discord's create_channel
    is the sole writer for the forum-thread flow.
    """
    adapter = DummyChannelOperations()
    adapter._client = object()  # truthy — adapter is "started"
    adapter._get_channel = AsyncMock(return_value=SimpleNamespace(_type=15))  # forum channel
    adapter._is_forum_channel = staticmethod(lambda ch: True)
    adapter._create_forum_thread = AsyncMock(return_value=(999, "topper-msg-1"))

    session = Session(
        session_id="sess-discord-1",
        computer_name="machine",
        tmux_session_name="tmux",
        title="Test",
        origin_metadata={"discord": DiscordAdapterMetadata(channel_id=None, thread_id=None).to_dict()},
    )
    # Route to project forum 400 via project_forum_map (key must match exactly)
    session.project_path = "proj"

    with patch("teleclaude.adapters.discord.channel_ops.db") as mock_db:
        mock_db.update_origin_metadata = AsyncMock()

        result = await adapter.create_channel(session, "My Thread", ChannelMetadata())

    assert result == "999"
    mock_db.update_origin_metadata.assert_awaited_once()
    call_args = mock_db.update_origin_metadata.call_args
    assert call_args.args[0] == "sess-discord-1"
    assert call_args.args[1] == "discord"
    persisted = call_args.args[2]
    assert persisted.get("thread_id") == 999
    assert persisted.get("channel_id") == 400
