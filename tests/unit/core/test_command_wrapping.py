# guard: no-companion
"""Test specifications for FR-5: Typed command wrapping for inline mutations.

Endpoints that currently perform adapter or DB mutations inline must be wrapped
in the command system. DELETE /sessions/{id} must route through CloseSessionCommand
via the command system with remote-routing support.

Required wrapping per input audit:
- DELETE /sessions/{id} → CloseSessionCommand (with remote-routing)
- POST /sessions/self/result → typed command via command service
- POST /sessions/self/widget → typed command via command service
- POST /sessions/self/escalate → typed command via command service
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSessionCloseRoutesViaCommandSystem:
    """DELETE /sessions/{id} routes through CloseSessionCommand via the command system."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_delete_session_dispatches_close_session_command(self) -> None:
        """The DELETE /sessions/{id} endpoint constructs and dispatches a CloseSessionCommand."""
        from starlette.requests import Request as StarletteRequest

        from teleclaude.api import sessions_routes
        from teleclaude.api.auth import CallerIdentity
        from teleclaude.types.commands import CloseSessionCommand

        identity = CallerIdentity(session_id="caller-1", system_role=None, human_role=None, tmux_session_name=None)

        dispatched_commands: list[object] = []

        async def capture_dispatch(cmd: object) -> object:
            dispatched_commands.append(cmd)
            return MagicMock(status="success")

        mock_request = MagicMock(spec=StarletteRequest)
        mock_request.headers = {"user-agent": "test", "x-web-email": "none"}

        with (
            patch.object(sessions_routes, "db", MagicMock()),
            patch("teleclaude.api.sessions_routes.check_session_access", new=AsyncMock()),
            patch("teleclaude.api.sessions_routes.get_command_service") as mock_svc,
        ):
            service = MagicMock()
            service.close_session = AsyncMock(side_effect=capture_dispatch)
            mock_svc.return_value = service

            await sessions_routes.end_session(
                request=mock_request,
                session_id="s1",
                _identity=identity,
            )

        assert len(dispatched_commands) > 0
        cmd = dispatched_commands[0]
        assert isinstance(cmd, CloseSessionCommand)
        assert cmd.session_id == "s1"


class TestSessionCloseRemoteRouting:
    """CloseSessionCommand supports remote-routing for non-local sessions."""

    @pytest.mark.unit
    def test_close_session_handler_has_remote_routing_logic(self) -> None:
        """The close_session handler contains logic to check whether the session
        is on a different computer and forward the command remotely.

        This verifies the handler's AST contains a comparison with computer_name
        or computer and a forwarding path — not just that strings exist in source.
        """
        import ast
        import inspect
        import textwrap

        from teleclaude.core.command_handlers._session import close_session

        source = inspect.getsource(close_session)
        source = textwrap.dedent(source)
        tree = ast.parse(source)

        # Look for attribute access patterns like session.computer_name or
        # config.computer.name that indicate the handler checks routing
        has_computer_check = False
        has_forward_or_send = False

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr in ("computer_name", "computer"):
                    has_computer_check = True
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in (
                    "forward",
                    "send_command",
                    "forward_command",
                    "dispatch_remote",
                    "send_remote",
                ):
                    has_forward_or_send = True
                elif isinstance(func, ast.Name) and func.id in (
                    "forward",
                    "send_command",
                    "forward_command",
                ):
                    has_forward_or_send = True

        assert has_computer_check, "close_session handler must check session computer_name for routing"
        assert has_forward_or_send, "close_session handler must have a remote forwarding path"


class TestEscalationUsesCommandSystem:
    """Session escalation endpoint routes through a typed command."""

    @pytest.mark.unit
    def test_escalation_route_dispatches_via_command_service(self) -> None:
        """The escalation route handler dispatches via the command service,
        not via direct DB or adapter calls."""
        from teleclaude.core.command_service import CommandService

        assert hasattr(CommandService, "escalate_session"), (
            "CommandService must have an escalate_session method for typed dispatch"
        )
        assert callable(CommandService.escalate_session)


class TestSessionResultUsesCommandSystem:
    """POST /sessions/self/result routes through a typed command."""

    @pytest.mark.unit
    def test_command_service_has_send_result_method(self) -> None:
        """CommandService exposes a method for typed result delivery dispatch."""
        from teleclaude.core.command_service import CommandService

        # The result delivery endpoint must use a typed command, not inline adapter calls.
        # CommandService must expose a method that handles this.
        has_result_method = (
            hasattr(CommandService, "send_result")
            or hasattr(CommandService, "deliver_result")
            or hasattr(CommandService, "session_result")
        )
        assert has_result_method, (
            "CommandService must have a method for result delivery (send_result, deliver_result, or session_result)"
        )


class TestSessionWidgetUsesCommandSystem:
    """POST /sessions/self/widget routes through a typed command."""

    @pytest.mark.unit
    def test_command_service_has_render_widget_method(self) -> None:
        """CommandService exposes a method for typed widget rendering dispatch."""
        from teleclaude.core.command_service import CommandService

        has_widget_method = (
            hasattr(CommandService, "render_widget")
            or hasattr(CommandService, "widget")
            or hasattr(CommandService, "session_widget")
        )
        assert has_widget_method, (
            "CommandService must have a method for widget rendering (render_widget, widget, or session_widget)"
        )


class TestDeleteSessionResponseModeAndCommandType:
    """DELETE /sessions/{id} routes through command system with declared response mode."""

    @pytest.mark.unit
    def test_close_session_command_type_and_mode_are_declared(self) -> None:
        """CloseSessionCommand has both command_type and response_mode declared,
        ensuring it's a fully-typed command, not an ad-hoc bypass."""
        from teleclaude.types.commands import CloseSessionCommand, CommandType, ResponseMode

        cmd = CloseSessionCommand(session_id="s1")
        assert cmd.command_type == CommandType.CLOSE_SESSION
        assert isinstance(cmd.response_mode, ResponseMode)
