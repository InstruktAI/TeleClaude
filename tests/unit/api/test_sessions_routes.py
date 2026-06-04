"""Characterization tests for session management routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api import sessions_routes
from teleclaude.api.sessions_routes import ListSessionsQuery
from teleclaude.api_models import (
    CreateSessionRequest,
    CreateSessionResponseDTO,
    SendMessageRequest,
    SendMessageResponseDTO,
)
from teleclaude.core.models import SessionLaunchKind, SessionSnapshot
from teleclaude.core.origins import InputOrigin


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

        with patch("teleclaude.api.session_create_launch.assert_agent_enabled", side_effect=ValueError("disabled")):
            with pytest.raises(HTTPException) as exc_info:
                await sessions_routes.create_session(request, identity=identity)

        assert exc_info.value.status_code == 400

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_create_session_on_remote_computer_returns_peer_session_without_local_creation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Remote session creation returns the peer-owned session and bypasses local creation."""
        local_computer = "local-machine"
        remote_computer = "remote-machine"
        project_path = "/repo/demo"
        startup_message = "build cluster-followups"
        prepared_metadata = SimpleNamespace(origin="web", human_role="admin")
        client = object()
        remote_response = CreateSessionResponseDTO(
            status="success",
            session_id="remote-session",
            tmux_session_name="tc_remote-session",
            computer=remote_computer,
            agent="codex",
        )
        monkeypatch.setattr(sessions_routes._STATE, "client", None, raising=False)
        monkeypatch.setattr(sessions_routes._STATE, "cache", None)
        monkeypatch.setattr(sessions_routes, "config", SimpleNamespace(computer=SimpleNamespace(name=local_computer)))

        async def dispatch_remote(
            configured_client: object,
            target_computer: str,
            dispatched_request: CreateSessionRequest,
            *,
            identity_metadata: object,
        ) -> CreateSessionResponseDTO:
            if configured_client is not client:
                raise AssertionError("remote route must preserve the configured peer client")
            if target_computer != remote_computer:
                raise AssertionError("remote route must target the requested computer")
            if dispatched_request is not request:
                raise AssertionError("remote route must delegate the request")
            if identity_metadata is not prepared_metadata:
                raise AssertionError("remote route must forward the prepared identity metadata")
            return remote_response

        request = CreateSessionRequest(
            computer=remote_computer,
            project_path=project_path,
            agent="codex",
            thinking_mode="slow",
            message=startup_message,
        )
        identity = SimpleNamespace(session_id=None, human_role=None, email="caller@example.com")
        local_service = SimpleNamespace(create_session=AsyncMock(side_effect=AssertionError("local create invoked")))

        sessions_routes.configure(client=client, cache=None)
        sessions_routes.configure(cache=object())
        with (
            patch("teleclaude.api.sessions_routes.dispatch_session_create_to_peer", new=dispatch_remote),
            patch(
                "teleclaude.api.sessions_routes._prepare_create_session",
                new=AsyncMock(return_value=(prepared_metadata, None, None, None, None)),
            ),
            patch("teleclaude.api.sessions_routes.get_command_service", return_value=local_service),
        ):
            await sessions_routes.create_session(request, identity=identity)

        local_service.create_session.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_create_session_on_local_computer_keeps_legacy_local_response(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Local session creation keeps using the local service and omits peer ownership."""
        local_computer = "local-machine"
        monkeypatch.setattr(sessions_routes._STATE, "client", object(), raising=False)
        monkeypatch.setattr(sessions_routes, "config", SimpleNamespace(computer=SimpleNamespace(name=local_computer)))
        request = CreateSessionRequest(
            computer=local_computer,
            project_path="/repo/demo",
            agent="codex",
            thinking_mode="slow",
        )
        identity = SimpleNamespace(session_id=None, human_role=None, email="caller@example.com")
        local_service = SimpleNamespace(
            create_session=AsyncMock(
                return_value={"session_id": "local-session", "tmux_session_name": "tc_local-session"}
            )
        )
        dispatch_remote = AsyncMock(side_effect=AssertionError("local create must not dispatch to a peer"))

        with (
            patch("teleclaude.api.session_create_launch.assert_agent_enabled", return_value="codex"),
            patch("teleclaude.api.sessions_routes.dispatch_session_create_to_peer", dispatch_remote),
            patch("teleclaude.api.sessions_routes.get_command_service", return_value=local_service),
        ):
            await sessions_routes.create_session(request, identity=identity)

        dispatch_remote.assert_not_awaited()
        local_service.create_session.assert_awaited_once()

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
        direct_link_response = SendMessageResponseDTO(status="error", mode="direct", link_id="link-1")

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

        with patch("teleclaude.api.session_create_launch.assert_agent_enabled", return_value="codex"):
            metadata, _initiator, initial_input, launch_intent, _caller = await sessions_routes._prepare_create_session(
                request, identity
            )

        assert initial_input == "/next-review-build chartest-api-routes"
        assert metadata.title is None
        assert metadata.system_role == "worker"
        assert metadata.job == "reviewer"
        assert metadata.launch_intent is not None
        assert launch_intent is not None
        assert launch_intent.kind == SessionLaunchKind.AGENT_THEN_MESSAGE
        assert launch_intent.message == sessions_routes._rewrite_codex_next_startup_message(
            "/next-review-build chartest-api-routes",
            effective_agent="codex",
        )

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

        with patch("teleclaude.api.session_create_launch.assert_agent_enabled", return_value="claude"):
            metadata, _initiator, initial_input, launch_intent, _caller = await sessions_routes._prepare_create_session(
                request, identity
            )

        assert initial_input == "/next-review-build chartest-api-routes"
        assert metadata.title is None
        assert metadata.launch_intent is not None
        assert launch_intent is not None
        assert launch_intent.kind == SessionLaunchKind.AGENT_THEN_MESSAGE
        assert launch_intent.message == "/next-review-build chartest-api-routes"


class TestWrapMessageWithOrigin:
    """Branch coverage for `_wrap_message_with_origin` and `_machine_origin_marker`.

    Behavioral contract: prepend the caller's machine identity bracket only when
    (a) the message is not already bracket-marked, (b) a caller session exists
    in the database, and (c) the caller carries a machine system_role
    (orchestrator/integrator/system). Worker callers and bare human callers
    pass through unwrapped.
    """

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_bridge_message_passes_through_unwrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Already bracket-marked TeleClaude bridge messages must not be re-wrapped."""
        get_session = AsyncMock()
        monkeypatch.setattr(sessions_routes.db, "get_session", get_session)
        bridge = "[TeleClaude - Peer (peer-uuid) on host]\n\nbody"

        result = await sessions_routes._wrap_message_with_origin(bridge, "caller-uuid")

        assert result == bridge
        get_session.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_orchestrator_dispatch_passes_through_unwrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Already bracket-marked orchestrator dispatches must not be re-wrapped."""
        get_session = AsyncMock()
        monkeypatch.setattr(sessions_routes.db, "get_session", get_session)
        dispatch = "[Orchestrator (orch-uuid) on host]\n\nDispatch reason: upstream-changed"

        result = await sessions_routes._wrap_message_with_origin(dispatch, "caller-uuid")

        assert result == dispatch
        get_session.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_human_caller_without_session_id_returns_unwrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Terminal/web/Telegram callers have no caller_session_id and never get a marker."""
        get_session = AsyncMock()
        monkeypatch.setattr(sessions_routes.db, "get_session", get_session)
        message = "fix the bug"

        result = await sessions_routes._wrap_message_with_origin(message, None)

        assert result == message
        get_session.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unknown_caller_session_returns_unwrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the caller session id does not resolve in the DB, no header is added."""
        monkeypatch.setattr(sessions_routes.db, "get_session", AsyncMock(return_value=None))
        message = "fix the bug"

        result = await sessions_routes._wrap_message_with_origin(message, "ghost-uuid")

        assert result == message

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_worker_caller_returns_unwrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Worker system_role is intentionally absent from the machine label map.

        Worker-to-peer communication routes through the Direct Conversation
        bracket or upstream `DISPATCH_ALLOWED` gating; an automatic marker on
        plain sends would double-mark or mis-label."""
        worker = SimpleNamespace(system_role="worker", computer_name="local")
        monkeypatch.setattr(sessions_routes.db, "get_session", AsyncMock(return_value=worker))
        message = "fix the bug"

        result = await sessions_routes._wrap_message_with_origin(message, "worker-uuid")

        assert result == message

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_orchestrator_caller_prepends_canonical_bracket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Orchestrator system_role triggers the `[Orchestrator (sess) on host]` header."""
        orchestrator = SimpleNamespace(system_role="orchestrator", computer_name="MozBook")
        monkeypatch.setattr(sessions_routes.db, "get_session", AsyncMock(return_value=orchestrator))

        result = await sessions_routes._wrap_message_with_origin("Dispatch body", "orch-uuid")

        assert result == "[Orchestrator (orch-uuid) on MozBook]\n\nDispatch body"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_integrator_caller_prepends_integrator_bracket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        integrator = SimpleNamespace(system_role="integrator", computer_name="MozBook")
        monkeypatch.setattr(sessions_routes.db, "get_session", AsyncMock(return_value=integrator))

        result = await sessions_routes._wrap_message_with_origin("integration message", "int-uuid")

        assert result == "[Integrator (int-uuid) on MozBook]\n\nintegration message"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_system_caller_prepends_system_bracket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        system = SimpleNamespace(system_role="system", computer_name="MozBook")
        monkeypatch.setattr(sessions_routes.db, "get_session", AsyncMock(return_value=system))

        result = await sessions_routes._wrap_message_with_origin("system message", "sys-uuid")

        assert result == "[System (sys-uuid) on MozBook]\n\nsystem message"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_missing_caller_computer_falls_back_to_local_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the caller's session has no computer_name, the local daemon's host fills in."""
        orchestrator = SimpleNamespace(system_role="orchestrator", computer_name=None)
        monkeypatch.setattr(sessions_routes.db, "get_session", AsyncMock(return_value=orchestrator))
        config_stub = SimpleNamespace(computer=SimpleNamespace(name="MozBook"))
        monkeypatch.setattr(sessions_routes, "config", config_stub)

        result = await sessions_routes._wrap_message_with_origin("body", "orch-uuid")

        assert result == "[Orchestrator (orch-uuid) on MozBook]\n\nbody"
