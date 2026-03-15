"""Characterization tests for session management routes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api import sessions_routes
from teleclaude.api_models import CreateSessionRequest, SendMessageRequest
from teleclaude.core.events import TeleClaudeEvents
from teleclaude.core.models import SessionSnapshot


def _make_request(headers: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(headers=headers or {})


class TestSessionsRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_create_session_returns_400_when_requested_agent_is_disabled(self) -> None:
        """Session creation surfaces disabled-agent validation as an HTTP 400."""
        request = CreateSessionRequest(computer="local", project_path="/repo/demo", agent="claude")
        identity = SimpleNamespace(session_id=None, human_role=None)

        with patch("teleclaude.api.sessions_routes.assert_agent_enabled", side_effect=ValueError("disabled")):
            with pytest.raises(HTTPException) as exc_info:
                await sessions_routes.create_session(request, identity=identity)

        assert exc_info.value.status_code == 400

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_sessions_filters_member_view_to_owned_and_shared_sessions(self) -> None:
        """Member web requests only see their own sessions plus shared sessions."""
        request = _make_request({"x-web-user-email": "member@example.com", "x-web-user-role": "member"})
        sessions = [
            SessionSnapshot(
                session_id="owned",
                last_input_origin=None,
                title="Owned",
                thinking_mode=None,
                active_agent="claude",
                status="active",
                human_email="member@example.com",
                visibility="private",
            ),
            SessionSnapshot(
                session_id="shared",
                last_input_origin=None,
                title="Shared",
                thinking_mode=None,
                active_agent="claude",
                status="active",
                human_email="other@example.com",
                visibility="shared",
            ),
            SessionSnapshot(
                session_id="private",
                last_input_origin=None,
                title="Private",
                thinking_mode=None,
                active_agent="claude",
                status="active",
                human_email="other@example.com",
                visibility="private",
            ),
        ]

        with (
            patch(
                "teleclaude.api.sessions_routes.command_handlers.list_sessions",
                new=AsyncMock(return_value=sessions),
            ),
            patch.object(sessions_routes, "_cache", None),
        ):
            response = await sessions_routes.list_sessions(
                request,
                computer=None,
                include_closed=False,
                all_sessions=False,
                job=None,
                identity=object(),
            )

        assert [session.session_id for session in response] == ["owned", "shared"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_endpoint_returns_existing_direct_link_response_without_dispatching(
        self,
    ) -> None:
        """Work-mode sends return the active direct-link response instead of dispatching a message."""
        request = _make_request()
        message = SendMessageRequest(message="hello")
        direct_link_response: Any = {"status": "error", "mode": "direct", "link_id": "link-1"}

        with (
            patch("teleclaude.api.session_access.check_session_access", new=AsyncMock()),
            patch("teleclaude.api.sessions_routes._load_target_session_for_message", new=AsyncMock(return_value=None)),
            patch(
                "teleclaude.api.sessions_routes._reject_existing_direct_link",
                new=AsyncMock(return_value=direct_link_response),
            ),
            patch("teleclaude.api.sessions_routes._process_api_message", new=AsyncMock()) as process_api_message,
        ):
            response = await sessions_routes.send_message_endpoint(
                request,
                "sess-1",
                message,
                identity=SimpleNamespace(session_id="caller-1"),
            )

        assert response == direct_link_response
        process_api_message.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_end_session_emits_closed_event_for_already_closed_sessions(self) -> None:
        """Already-closed sessions emit the closed event without changing lifecycle state."""
        request = _make_request({"user-agent": "pytest"})
        session = SimpleNamespace(session_id="sess-closed", closed_at="2025-03-15T00:00:00Z", lifecycle_status="closed")

        with (
            patch("teleclaude.api.session_access.check_session_access", new=AsyncMock()),
            patch.object(sessions_routes, "db") as db,
            patch.object(sessions_routes.event_bus, "emit") as emit,
        ):
            db.get_session = AsyncMock(return_value=session)
            db.update_session = AsyncMock()

            response = await sessions_routes.end_session(request, "sess-closed", computer="local", identity=object())

        assert response["status"] == "success"
        emit.assert_called_once()
        assert emit.call_args.args[0] == TeleClaudeEvents.SESSION_CLOSED
        db.update_session.assert_not_awaited()
