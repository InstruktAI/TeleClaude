"""Characterization tests for session management routes."""

# pylint: disable=protected-access

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api import sessions_routes
from teleclaude.api.sessions_routes import ListSessionsQuery
from teleclaude.api_models import CreateSessionRequest, SendMessageRequest
from teleclaude.core.models import SessionLaunchKind, SessionSnapshot
from teleclaude.core.origins import InputOrigin
from teleclaude.paths import COMMANDS_DIR


def _make_request(headers: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(headers=headers or {})


class TestSessionsRoutes:
    """Session route preparation and lifecycle tests."""

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
    async def test_list_sessions_returns_last_agent_stop_at_and_agent_status(self) -> None:
        """List responses surface the deterministic turn-settled fields."""
        request = _make_request()
        sessions = [
            SessionSnapshot(
                session_id="worker-1",
                last_input_origin=None,
                title="Worker",
                thinking_mode=None,
                active_agent="codex",
                status="active",
                last_input_at="2025-02-01T12:00:00+00:00",
                last_agent_stop_at="2025-02-01T12:00:05+00:00",
                agent_status="idle",
            )
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

        assert response[0].last_agent_stop_at == "2025-02-01T12:00:05+00:00"
        assert response[0].agent_status == "idle"

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
        assert response.status_code == 202  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_prepare_create_session_selects_web_origin_when_human_email_provided(self) -> None:
        """When request.human_email is set, origin becomes WEB and typed origin metadata carries email."""
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
            metadata, _initiator, _title, _intent, _caller = await sessions_routes._prepare_create_session(
                request, identity
            )

        assert metadata.origin == InputOrigin.WEB.value
        assert metadata.origin_metadata is not None
        assert metadata.origin_metadata["email"] == "web@example.com"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_prepare_create_session_injects_identity_email_into_origin_metadata(self) -> None:
        """Email from CallerIdentity is injected into typed origin metadata for IdentityResolver."""
        request = CreateSessionRequest(
            computer="local",
            project_path="/repo/demo",
        )
        identity = SimpleNamespace(session_id=None, human_role=None, email="terminal@example.com")

        with patch(
            "teleclaude.api.sessions_routes._build_launch_intent",
            new=AsyncMock(return_value=(None, None)),
        ):
            metadata, _initiator, _title, _intent, _caller = await sessions_routes._prepare_create_session(
                request, identity
            )

        assert metadata.origin == InputOrigin.TERMINAL.value
        assert metadata.origin_metadata is not None
        assert metadata.origin_metadata["email"] == "terminal@example.com"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_prepare_create_session_preserves_explicit_daemon_origin_override(self) -> None:
        """Daemon-internal callers may provide origin/origin_metadata that must survive route preparation."""
        request = CreateSessionRequest.model_validate(
            {
                "computer": "local",
                "project_path": "/repo/demo",
                "title": "WhatsApp: 15551234567",
                "origin": InputOrigin.WHATSAPP.value,
                "origin_metadata": {
                    "phone_number": "15551234567",
                    "platform": "whatsapp",
                },
            }
        )
        identity = SimpleNamespace(session_id="sess-daemon", human_role=None, email="daemon@example.com")

        with patch(
            "teleclaude.api.sessions_routes._build_launch_intent",
            new=AsyncMock(return_value=(None, None)),
        ):
            metadata, _initiator, _title, _intent, _caller = await sessions_routes._prepare_create_session(
                request, identity
            )

        assert metadata.origin == InputOrigin.WHATSAPP.value
        assert metadata.origin_metadata is not None
        assert metadata.origin_metadata["phone_number"] == "15551234567"
        assert metadata.origin_metadata["platform"] == "whatsapp"
        assert "email" not in metadata.origin_metadata

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_prepare_create_session_rejects_non_admin_human_role_override(self) -> None:
        """Authenticated non-admin callers cannot assert a stronger human_role in the body."""
        request = CreateSessionRequest(
            computer="local",
            project_path="/repo/demo",
            human_role="admin",
        )
        identity = SimpleNamespace(session_id="sess-member", human_role="member", email="member@example.com")

        with patch(
            "teleclaude.api.sessions_routes._build_launch_intent",
            new=AsyncMock(return_value=(None, None)),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await sessions_routes._prepare_create_session(request, identity)

        assert exc_info.value.status_code == 403

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_prepare_create_session_allows_admin_human_role_override(self) -> None:
        """Admin identities may explicitly create restricted-role sessions."""
        request = CreateSessionRequest(
            computer="local",
            project_path="/repo/demo",
            human_role="member",
        )
        identity = SimpleNamespace(session_id="sess-admin", human_role="admin", email="admin@example.com")

        with patch(
            "teleclaude.api.sessions_routes._build_launch_intent",
            new=AsyncMock(return_value=(None, None)),
        ):
            metadata, _initiator, _title, _intent, _caller = await sessions_routes._prepare_create_session(
                request, identity
            )

        assert metadata.human_role == "member"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_prepare_create_session_infers_role_from_slash_command_message(self) -> None:
        """When message starts with a mapped slash command, system_role and job are inferred."""
        request = CreateSessionRequest(
            computer="local",
            project_path="/repo/demo",
            message="/next-integrate some-slug",
        )
        identity = SimpleNamespace(session_id=None, human_role=None, email="admin@example.com")

        with patch(
            "teleclaude.api.sessions_routes._build_launch_intent",
            new=AsyncMock(return_value=(None, None)),
        ):
            metadata, _initiator, _title, _intent, _caller = await sessions_routes._prepare_create_session(
                request, identity
            )

        assert metadata.system_role == "integrator"
        assert metadata.job == "integrator"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_prepare_create_session_no_role_inference_for_unmapped_command(self) -> None:
        """Slash commands not in COMMAND_ROLE_MAP leave system_role and job as None."""
        request = CreateSessionRequest(
            computer="local",
            project_path="/repo/demo",
            message="/unknown-command arg",
        )
        identity = SimpleNamespace(session_id=None, human_role=None, email="admin@example.com")

        with patch(
            "teleclaude.api.sessions_routes._build_launch_intent",
            new=AsyncMock(return_value=(None, None)),
        ):
            metadata, _initiator, _title, _intent, _caller = await sessions_routes._prepare_create_session(
                request, identity
            )

        assert metadata.system_role is None
        assert metadata.job is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_prepare_create_session_rewrites_codex_next_message_to_loader_prompt(self) -> None:
        """Codex session creation rewrites `/next-*` startup messages at the API boundary."""
        request = CreateSessionRequest(
            computer="local",
            project_path="/repo/demo",
            agent="codex",
            message="/next-review-build chartest-api-routes",
        )
        identity = SimpleNamespace(session_id="caller-123", human_role="member", email="member@example.com")

        with patch("teleclaude.api.sessions_routes.assert_agent_enabled", return_value="codex"):
            metadata, _initiator, _title, launch_intent, _caller = await sessions_routes._prepare_create_session(
                request, identity
            )

        expected_startup_message = (
            f"Read {COMMANDS_DIR / 'next-review-build.md'} and follow it exactly as "
            "the active instruction set for this session.\n\n"
            "Treat the following as provided inputs to that instruction set:\n"
            "- slug: chartest-api-routes"
        )
        assert metadata.title == "/next-review-build chartest-api-routes"
        assert metadata.system_role == "worker"
        assert metadata.job == "reviewer"
        assert metadata.launch_intent is not None
        assert launch_intent is not None
        assert launch_intent.kind == SessionLaunchKind.AGENT_THEN_MESSAGE
        assert launch_intent.message == expected_startup_message

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_prepare_create_session_keeps_non_codex_next_message_raw(self) -> None:
        """Non-Codex session creation keeps `/next-*` messages unchanged."""
        request = CreateSessionRequest(
            computer="local",
            project_path="/repo/demo",
            agent="claude",
            message="/next-review-build chartest-api-routes",
        )
        identity = SimpleNamespace(session_id="caller-123", human_role="member", email="member@example.com")

        with patch("teleclaude.api.sessions_routes.assert_agent_enabled", return_value="claude"):
            metadata, _initiator, _title, launch_intent, _caller = await sessions_routes._prepare_create_session(
                request, identity
            )

        assert metadata.title == "/next-review-build chartest-api-routes"
        assert metadata.launch_intent is not None
        assert launch_intent is not None
        assert launch_intent.kind == SessionLaunchKind.AGENT_THEN_MESSAGE
        assert launch_intent.message == "/next-review-build chartest-api-routes"
