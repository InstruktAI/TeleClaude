"""Unit tests for tmux orphan cleanup exclusions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core import session_cleanup
from teleclaude.core.models import Session


@pytest.mark.asyncio
async def test_cleanup_orphan_tmux_sessions_skips_tui_session() -> None:
    mock_sessions = [
        Session(
            session_id="abc",
            computer_name="local",
            tmux_session_name="tc_abc",
            origin_adapter="telegram",
            title="Test",
        )
    ]
    with (
        patch(
            "teleclaude.core.session_cleanup.tmux_bridge.list_tmux_sessions",
            new=AsyncMock(return_value=["tc_tui", "tc_orphan", "other"]),
        ),
        patch(
            "teleclaude.core.session_cleanup.db.get_all_sessions",
            new=AsyncMock(return_value=mock_sessions),
        ),
        patch(
            "teleclaude.core.session_cleanup.tmux_bridge.kill_session",
            new=AsyncMock(return_value=True),
        ) as kill_session,
    ):
        killed = await session_cleanup.cleanup_orphan_tmux_sessions()

    assert killed == 1
    kill_session.assert_called_once_with("tc_orphan")
