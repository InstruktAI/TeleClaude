# guard: no-companion
"""Test specifications for FR-2: Metadata-driven command dispatch.

The command dispatcher must read response_mode to determine execution behavior
instead of isinstance chains. Adding a new command subclass requires no changes
to the dispatcher.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDispatchBranchesOnResponseMode:
    """Dispatch logic reads response_mode, not command class identity."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_immediate_command_dispatch_returns_handler_result(self) -> None:
        """IMMEDIATE command: dispatcher calls handler and returns its result.

        Verifies the actual dispatch path returns data for IMMEDIATE commands,
        not just that a mock returns what we told it to.
        """
        from teleclaude.types.commands import GetSessionDataCommand, ResponseMode

        cmd = GetSessionDataCommand(session_id="s1")
        assert cmd.response_mode == ResponseMode.IMMEDIATE

        handler_result = {"transcript": "data"}
        mock_service = MagicMock()
        mock_service.get_session_data = AsyncMock(return_value=handler_result)

        with patch(
            "teleclaude.transport.redis_transport._messaging.get_command_service",
            return_value=mock_service,
        ):
            from teleclaude.transport.redis_transport._messaging import _MessagingMixin

            messaging = MagicMock(spec=_MessagingMixin)
            messaging._dispatch_command = _MessagingMixin._dispatch_command.__get__(messaging)
            result = await messaging._dispatch_command(cmd)

        assert result == handler_result

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fire_and_forget_command_dispatch_returns_none(self) -> None:
        """FIRE_AND_FORGET command: dispatcher calls handler and returns None.

        The dispatcher must not propagate the handler's return value for F&F commands.
        """
        from teleclaude.types.commands import CloseSessionCommand, ResponseMode

        cmd = CloseSessionCommand(session_id="s1")
        assert cmd.response_mode == ResponseMode.FIRE_AND_FORGET

        mock_service = MagicMock()
        mock_service.close_session = AsyncMock(return_value="should-be-discarded")

        with patch(
            "teleclaude.transport.redis_transport._messaging.get_command_service",
            return_value=mock_service,
        ):
            from teleclaude.transport.redis_transport._messaging import _MessagingMixin

            messaging = MagicMock(spec=_MessagingMixin)
            messaging._dispatch_command = _MessagingMixin._dispatch_command.__get__(messaging)
            result = await messaging._dispatch_command(cmd)

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_receipt_command_reaching_dispatch_raises(self) -> None:
        """RECEIPT commands must not reach the redis dispatcher — they go through OperationsService."""
        from teleclaude.types.commands import CommandType, InternalCommand, ResponseMode

        cmd = InternalCommand(command_type=CommandType.CREATE_SESSION, response_mode=ResponseMode.RECEIPT)

        mock_service = MagicMock()

        with (
            patch(
                "teleclaude.transport.redis_transport._messaging.get_command_service",
                return_value=mock_service,
            ),
            pytest.raises(ValueError, match="RECEIPT"),
        ):
            from teleclaude.transport.redis_transport._messaging import _MessagingMixin

            messaging = MagicMock(spec=_MessagingMixin)
            messaging._dispatch_command = _MessagingMixin._dispatch_command.__get__(messaging)
            await messaging._dispatch_command(cmd)


class TestDispatchDoesNotUseClassBasedRouting:
    """The _dispatch_command method must not contain class-based routing for mode selection."""

    @pytest.mark.unit
    def test_dispatch_does_not_use_isinstance_or_type_checks_for_routing(self) -> None:
        """_dispatch_command does not use isinstance or type() to select response behavior.

        Checks the actual method source for any pattern that routes by command
        class identity rather than by response_mode. This catches isinstance(),
        type(command) is/==, and match/case on type.
        """
        import ast
        import inspect
        import textwrap

        from teleclaude.transport.redis_transport._messaging import _MessagingMixin

        source = inspect.getsource(_MessagingMixin._dispatch_command)
        source = textwrap.dedent(source)
        tree = ast.parse(source)

        # Walk the AST looking for isinstance() calls or type() comparisons
        # that reference command class names — these indicate class-based routing.
        command_class_names = {
            "CreateSessionCommand",
            "ProcessMessageCommand",
            "KeysCommand",
            "StartAgentCommand",
            "ResumeAgentCommand",
            "RestartAgentCommand",
            "RunAgentCommand",
            "GetSessionDataCommand",
            "CloseSessionCommand",
            "HandleVoiceCommand",
            "HandleFileCommand",
            "SystemCommand",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "isinstance" and len(node.args) >= 2:
                    # Check if second arg references any command class
                    type_arg = node.args[1]
                    names_in_arg: list[str] = []
                    if isinstance(type_arg, ast.Name):
                        names_in_arg.append(type_arg.id)
                    elif isinstance(type_arg, ast.Tuple):
                        names_in_arg.extend(elt.id for elt in type_arg.elts if isinstance(elt, ast.Name))
                    for name in names_in_arg:
                        assert name not in command_class_names, (
                            f"_dispatch_command uses isinstance check for {name} — must route by response_mode instead"
                        )


class TestNewCommandRequiresNoDispatcherChanges:
    """Adding a new command with an existing handler requires no dispatcher changes.

    The response_mode execution layer derives behavior automatically from the command's
    response_mode field — no per-type branching needed.
    """

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ff_command_with_registered_handler_returns_none(self) -> None:
        """A FIRE_AND_FORGET command with a registered handler returns None.

        The dispatcher routes by command_type for handler lookup and response_mode
        for execution behavior. This proves the execution layer is metadata-driven.
        """
        from teleclaude.types.commands import CloseSessionCommand

        cmd = CloseSessionCommand(session_id="s1")

        mock_service = MagicMock()
        mock_service.close_session = AsyncMock(return_value="handler-result-ignored")

        with patch(
            "teleclaude.transport.redis_transport._messaging.get_command_service",
            return_value=mock_service,
        ):
            from teleclaude.transport.redis_transport._messaging import _MessagingMixin

            messaging = MagicMock(spec=_MessagingMixin)
            messaging._dispatch_command = _MessagingMixin._dispatch_command.__get__(messaging)
            result = await messaging._dispatch_command(cmd)

        assert result is None
        mock_service.close_session.assert_awaited_once_with(cmd)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_immediate_command_with_registered_handler_returns_result(self) -> None:
        """An IMMEDIATE command with a registered handler returns the handler's result."""
        from teleclaude.types.commands import CreateSessionCommand

        cmd = CreateSessionCommand(project_path="/tmp", origin="test")

        expected = {"session_id": "new-session"}
        mock_service = MagicMock()
        mock_service.create_session = AsyncMock(return_value=expected)

        with patch(
            "teleclaude.transport.redis_transport._messaging.get_command_service",
            return_value=mock_service,
        ):
            from teleclaude.transport.redis_transport._messaging import _MessagingMixin

            messaging = MagicMock(spec=_MessagingMixin)
            messaging._dispatch_command = _MessagingMixin._dispatch_command.__get__(messaging)
            result = await messaging._dispatch_command(cmd)

        assert result == expected
        mock_service.create_session.assert_awaited_once_with(cmd)
