"""Tests for teleclaude.core.session_cleanup — session termination and token revocation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.session_cleanup import _end_escalation_if_active, _terminate_session_inner


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


class TestEndEscalationIfActive:
    """_end_escalation_if_active clears relay state and emits event when escalated."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_active_escalation_is_cleared_and_event_emitted(self):
        session = _make_session(session_id="sess-esc")
        session.relay_status = "active"

        with (
            patch("teleclaude.core.session_cleanup.db") as mock_db,
            patch("teleclaude.core.session_cleanup.event_bus") as mock_event_bus,
        ):
            mock_db.update_session = AsyncMock()

            await _end_escalation_if_active(session)

        mock_db.update_session.assert_called_once_with(
            "sess-esc",
            relay_status=None,
            relay_discord_channel_id=None,
            relay_started_at=None,
        )
        mock_event_bus.emit.assert_called_once()
        assert mock_event_bus.emit.call_args.args[0] == "session.escalation_ended"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_non_escalated_session_is_skipped(self):
        session = _make_session(session_id="sess-no-esc")
        session.relay_status = None

        with (
            patch("teleclaude.core.session_cleanup.db") as mock_db,
            patch("teleclaude.core.session_cleanup.event_bus") as mock_event_bus,
        ):
            mock_db.update_session = AsyncMock()

            await _end_escalation_if_active(session)

        mock_db.update_session.assert_not_called()
        mock_event_bus.emit.assert_not_called()
