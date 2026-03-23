"""Characterization tests for session management routes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api import sessions_routes
from teleclaude.api.sessions_routes import ListSessionsQuery
from teleclaude.api_models import CreateSessionRequest, SendMessageRequest
from teleclaude.core.models import SessionSnapshot
from teleclaude.core.origins import InputOrigin


def _make_request(headers: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(headers=headers or {})


class TestSessionsRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_create_session_returns_400_when_requested_agent_is_disabled(self) -> None:
        """Session creation surfaces disabled-agent validation as an HTTP 400."""
        request = CreateSessionRequest(computer="local", project_path="/repo/demo", agent="claude")
        identity = SimpleNamespace(session_id=None, human_role=None, email=None)

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
            patch.object(sessions_routes._STATE, "cache", None),
        ):
            response = await sessions_routes.list_sessions(
                request,
                query=ListSessionsQuery(
                    computer=None,
                    include_closed=False,
                    all_sessions=False,
                    job=None,
                ),
                _identity=object(),
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
    async def test_end_session_dispatches_close_via_command_service(self) -> None:
        """DELETE /sessions dispatches through CommandService.close_session."""
        request = _make_request({"user-agent": "pytest"})

        mock_service = MagicMock()
        mock_service.close_session = AsyncMock()

        with (
            patch("teleclaude.api.session_access.check_session_access", new=AsyncMock()),
            patch("teleclaude.api.sessions_routes.get_command_service", return_value=mock_service),
        ):
            response = await sessions_routes.end_session(request, "sess-1", _identity=object())

        mock_service.close_session.assert_awaited_once()
        assert response.status_code == 202

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_prepare_create_session_selects_web_origin_when_human_email_provided(self) -> None:
        """When request.human_email is set, origin becomes WEB and email is injected into channel_metadata."""
        request = CreateSessionRequest(
            computer="local",
            project_path="/repo/demo",
            human_email="web@example.com",
        )
        identity = SimpleNamespace(session_id=None, human_role=None, email=None)

        with patch(
            "teleclaude.api.sessions_routes._build_launch_intent",
            new=AsyncMock(return_value=(None, None)),
        ):
            metadata, _title, _intent, _caller = await sessions_routes._prepare_create_session(request, identity)

        assert metadata.origin == InputOrigin.WEB.value
        assert metadata.channel_metadata is not None
        assert metadata.channel_metadata["email"] == "web@example.com"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_prepare_create_session_injects_identity_email_into_channel_metadata(self) -> None:
        """Email from CallerIdentity is injected into channel_metadata for IdentityResolver."""
        request = CreateSessionRequest(
            computer="local",
            project_path="/repo/demo",
        )
        identity = SimpleNamespace(session_id=None, human_role=None, email="terminal@example.com")

        with patch(
            "teleclaude.api.sessions_routes._build_launch_intent",
            new=AsyncMock(return_value=(None, None)),
        ):
            metadata, _title, _intent, _caller = await sessions_routes._prepare_create_session(request, identity)

        assert metadata.origin == InputOrigin.TERMINAL.value
        assert metadata.channel_metadata is not None
        assert metadata.channel_metadata["email"] == "terminal@example.com"
