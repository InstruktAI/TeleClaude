from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from teleclaude.adapters.discord.channel_ops import ChannelOperationsMixin
from teleclaude.core.models import Session
from teleclaude.core.models._adapter import SessionAdapterMetadata

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


def test_store_channel_id_keeps_help_desk_forum_as_channel_id() -> None:
    adapter = DummyChannelOperations()
    metadata = SessionAdapterMetadata()

    adapter.store_channel_id(metadata, "100")

    discord_meta = metadata.get_ui().get_discord()
    assert discord_meta.channel_id == 100
    assert discord_meta.thread_id is None


def test_store_channel_id_records_thread_id_and_preserves_help_desk_forum() -> None:
    adapter = DummyChannelOperations()
    metadata = SessionAdapterMetadata()

    adapter.store_channel_id(metadata, "999")

    discord_meta = metadata.get_ui().get_discord()
    assert discord_meta.channel_id == 100
    assert discord_meta.thread_id == 999
