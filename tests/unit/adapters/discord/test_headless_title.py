"""Tests for [HEADLESS] prefix in Discord thread titles."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from teleclaude.adapters.discord.channel_ops import ChannelOperationsMixin
from teleclaude.core.models import Session

pytestmark = pytest.mark.unit


class DummyChannelOperations(ChannelOperationsMixin):
    def __init__(self) -> None:
        self._help_desk_channel_id = 100
        self._all_sessions_channel_id = 200
        self._team_channel_map: dict[int, str] = {}
        self._project_forum_map = {"proj": 400}
        self._trusted_dirs = [SimpleNamespace(path="/workspace/proj", discord_forum=400)]
        self._parse_optional_int = lambda value: (
            int(str(value).strip()) if value is not None and str(value).strip().isdigit() else None
        )


def _make_session(
    *,
    lifecycle_status: str = "active",
    title: str = "My Task",
    project_path: str = "/workspace/proj",
    subdir: str | None = None,
) -> Session:
    return Session(
        session_id="session-1",
        computer_name="machine",
        tmux_session_name="tmux-session",
        title=title,
        lifecycle_status=lifecycle_status,
        project_path=project_path,
        subdir=subdir,
    )


def test_build_thread_title_prefixes_headless_in_project_forum() -> None:
    adapter = DummyChannelOperations()
    session = _make_session(lifecycle_status="headless")
    title = adapter._build_thread_title(session, target_forum_id=400)
    assert title == "[HEADLESS] My Task"


def test_build_thread_title_prefixes_headless_in_catchall_forum() -> None:
    adapter = DummyChannelOperations()
    session = _make_session(lifecycle_status="headless")
    title = adapter._build_thread_title(session, target_forum_id=200)
    assert title.startswith("[HEADLESS] ")
    # Catch-all includes project name prefix
    assert "My Task" in title


def test_build_thread_title_no_prefix_for_active_session() -> None:
    adapter = DummyChannelOperations()
    session = _make_session(lifecycle_status="active")
    title = adapter._build_thread_title(session, target_forum_id=400)
    assert not title.startswith("[HEADLESS]")
    assert title == "My Task"
