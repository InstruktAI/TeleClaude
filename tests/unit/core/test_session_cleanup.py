"""Tests for teleclaude.core.session_cleanup — session termination and token revocation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_session(session_id: str = "sess-lifecycle") -> MagicMock:
    session = MagicMock()
    session.session_id = session_id
    session.principal = f"system:{session_id}"
    session.human_email = None
    session.human_role = "admin"
    session.tmux_session_name = f"tmux-{session_id}"
    session.project_path = "/tmp/project"
    session.subdir = None
    return session


class TestTerminateSessionRevokesTokens:
    """Closing a session triggers revoke_session_tokens() and cache invalidation."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_terminate_session_calls_revoke_and_invalidate(self):
        """terminate_session calls revoke_session_tokens and invalidate_token_cache."""
        from teleclaude.core.session_cleanup import _terminate_session_inner

        session = _make_session(session_id="sess-lifecycle")

        with (
            patch("teleclaude.core.session_cleanup.db") as mock_db,
            patch("teleclaude.core.session_cleanup.invalidate_token_cache") as mock_invalidate,
            patch("teleclaude.core.session_cleanup.tmux_bridge") as mock_tmux,
            patch("teleclaude.core.session_cleanup.cleanup_session_resources", new_callable=AsyncMock),
            patch("teleclaude.core.session_cleanup.event_bus") as mock_event_bus,
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.revoke_session_tokens = AsyncMock()
            mock_db.update_session = AsyncMock()
            mock_db.close_session = AsyncMock()
            mock_tmux.kill_session = AsyncMock(return_value=True)
            mock_event_bus.emit = AsyncMock()

            await _terminate_session_inner("sess-lifecycle", MagicMock(), reason="test")

        mock_db.revoke_session_tokens.assert_called_once_with("sess-lifecycle")
        mock_invalidate.assert_called_once_with("sess-lifecycle")
