"""Tests for [HEADLESS] prefix in Discord-derived display titles."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from teleclaude.adapters.discord.channel_ops import ChannelOperationsMixin
from teleclaude.core.models import Session

pytestmark = pytest.mark.unit


class DummyChannelOperations(ChannelOperationsMixin):
    """Mirrors DummyChannelOperations in test_channel_ops.py but with a different forum map.

    The headless-prefix and title_body responsibilities live on different layers:
    headless_prefix is universal (UiAdapter base) and title_body is the
    Discord-specific decoration. These tests pin the composed display_title.
    """

    def __init__(self, project_forum_map: dict[str, int] | None = None) -> None:
        self._help_desk_channel_id = 100
        self._all_sessions_channel_id = 200
        self._team_channel_map: dict[int, str] = {}
        self._project_forum_map = project_forum_map if project_forum_map is not None else {"/workspace/proj": 400}
        self._trusted_dirs = [SimpleNamespace(path="/workspace/proj", discord_forum=400)]
        self._parse_optional_int = lambda value: (
            int(str(value).strip()) if value is not None and str(value).strip().isdigit() else None
        )

    def headless_prefix(self, session: Session) -> str:
        return "[HEADLESS] " if session.lifecycle_status == "headless" else ""

    def display_title(self, session: Session) -> str:
        return f"{self.headless_prefix(session)}{self.title_body(session)}"


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


def test_display_title_prefixes_headless_in_project_forum() -> None:
    """Headless session routed to a per-project forum: bare title with [HEADLESS] marker."""
    adapter = DummyChannelOperations()
    session = _make_session(lifecycle_status="headless")
    assert adapter.display_title(session) == "[HEADLESS] My Task"


def test_display_title_prefixes_headless_in_catchall_forum() -> None:
    """Headless session routed to the catch-all forum: project short-name + title, with [HEADLESS] marker."""
    # Empty project_forum_map forces fallback to the all_sessions catch-all forum.
    adapter = DummyChannelOperations(project_forum_map={})
    session = _make_session(lifecycle_status="headless")
    title = adapter.display_title(session)
    assert title.startswith("[HEADLESS] ")
    assert "My Task" in title


def test_display_title_no_prefix_for_active_session() -> None:
    """Active (non-headless) session in a project forum: bare title, no marker."""
    adapter = DummyChannelOperations()
    session = _make_session(lifecycle_status="active")
    assert adapter.display_title(session) == "My Task"
