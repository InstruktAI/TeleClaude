# guard: no-companion
"""Test specifications for FR-1: Response mode declaration on commands.

Every command subclass must declare its response_mode. FIRE_AND_FORGET commands
must declare a non-null completion_event, enforced at construction time.
IMMEDIATE commands have completion_event=None.

Classification source of truth:
- Input audit "already correct" endpoints → IMMEDIATE (preserves current 200 contract)
- Design doc FIRE_AND_FORGET → endpoints that return 202 with completion signal
- Design doc RECEIPT → heavy async operations returning operation receipt
"""

from __future__ import annotations

import pytest


class TestResponseModeEnum:
    """ResponseMode enum exists with exactly three members."""

    @pytest.mark.unit
    def test_response_mode_has_immediate_member(self) -> None:
        """ResponseMode.IMMEDIATE exists with value 'immediate'."""
        from teleclaude.types.commands import ResponseMode

        assert ResponseMode.IMMEDIATE.value == "immediate"

    @pytest.mark.unit
    def test_response_mode_has_fire_and_forget_member(self) -> None:
        """ResponseMode.FIRE_AND_FORGET exists with value 'fire_and_forget'."""
        from teleclaude.types.commands import ResponseMode

        assert ResponseMode.FIRE_AND_FORGET.value == "fire_and_forget"

    @pytest.mark.unit
    def test_response_mode_has_receipt_member(self) -> None:
        """ResponseMode.RECEIPT exists with value 'receipt'."""
        from teleclaude.types.commands import ResponseMode

        assert ResponseMode.RECEIPT.value == "receipt"

    @pytest.mark.unit
    def test_response_mode_has_exactly_three_members(self) -> None:
        """No extra modes exist — exactly IMMEDIATE, FIRE_AND_FORGET, RECEIPT."""
        from teleclaude.types.commands import ResponseMode

        assert len(ResponseMode) == 3


class TestInternalCommandBaseFields:
    """InternalCommand carries response_mode and completion_event."""

    @pytest.mark.unit
    def test_internal_command_has_response_mode_field(self) -> None:
        """Base InternalCommand exposes response_mode defaulting to IMMEDIATE."""
        from teleclaude.types.commands import CommandType, InternalCommand, ResponseMode

        cmd = InternalCommand(command_type=CommandType.CREATE_SESSION)
        assert cmd.response_mode == ResponseMode.IMMEDIATE

    @pytest.mark.unit
    def test_internal_command_has_completion_event_field(self) -> None:
        """Base InternalCommand exposes completion_event defaulting to None."""
        from teleclaude.types.commands import CommandType, InternalCommand

        cmd = InternalCommand(command_type=CommandType.CREATE_SESSION)
        assert cmd.completion_event is None


class TestImmediateCommandModes:
    """Commands whose endpoints are 'already correct' per input audit declare IMMEDIATE.

    These endpoints currently return 200 and must preserve that contract.
    """

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "command_cls_name,constructor_kwargs",
        [
            ("CreateSessionCommand", {"project_path": "/tmp", "origin": "test"}),
            ("GetSessionDataCommand", {"session_id": "s1"}),
            ("ProcessMessageCommand", {"session_id": "s1", "text": "hi", "origin": "test"}),
            ("KeysCommand", {"session_id": "s1", "key": "Enter"}),
            ("HandleVoiceCommand", {"session_id": "s1", "file_path": "/tmp/v.ogg"}),
            ("HandleFileCommand", {"session_id": "s1", "file_path": "/tmp/f.txt", "filename": "f.txt"}),
            ("StartAgentCommand", {"session_id": "s1", "agent_name": "claude"}),
            ("ResumeAgentCommand", {"session_id": "s1"}),
            ("RunAgentCommand", {"session_id": "s1", "command": "/help", "origin": "test"}),
        ],
        ids=[
            "create_session",
            "get_session_data",
            "process_message",
            "keys",
            "handle_voice",
            "handle_file",
            "start_agent",
            "resume_agent",
            "run_agent_command",
        ],
    )
    def test_immediate_commands_declare_immediate_mode(
        self, command_cls_name: str, constructor_kwargs: dict[str, str]
    ) -> None:
        """Commands for 'already correct' 200 endpoints declare IMMEDIATE mode."""
        import teleclaude.types.commands as cmds
        from teleclaude.types.commands import ResponseMode

        cls = getattr(cmds, command_cls_name)
        instance = cls(**constructor_kwargs)
        assert instance.response_mode == ResponseMode.IMMEDIATE

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "command_cls_name,constructor_kwargs",
        [
            ("CreateSessionCommand", {"project_path": "/tmp", "origin": "test"}),
            ("GetSessionDataCommand", {"session_id": "s1"}),
            ("ProcessMessageCommand", {"session_id": "s1", "text": "hi", "origin": "test"}),
            ("KeysCommand", {"session_id": "s1", "key": "Enter"}),
            ("HandleVoiceCommand", {"session_id": "s1", "file_path": "/tmp/v.ogg"}),
            ("HandleFileCommand", {"session_id": "s1", "file_path": "/tmp/f.txt", "filename": "f.txt"}),
            ("StartAgentCommand", {"session_id": "s1", "agent_name": "claude"}),
            ("ResumeAgentCommand", {"session_id": "s1"}),
            ("RunAgentCommand", {"session_id": "s1", "command": "/help", "origin": "test"}),
        ],
        ids=[
            "create_session",
            "get_session_data",
            "process_message",
            "keys",
            "handle_voice",
            "handle_file",
            "start_agent",
            "resume_agent",
            "run_agent_command",
        ],
    )
    def test_immediate_commands_have_no_completion_event(
        self, command_cls_name: str, constructor_kwargs: dict[str, str]
    ) -> None:
        """IMMEDIATE commands have completion_event=None."""
        import teleclaude.types.commands as cmds

        cls = getattr(cmds, command_cls_name)
        instance = cls(**constructor_kwargs)
        assert instance.completion_event is None


class TestFireAndForgetCommandModes:
    """Commands classified as FIRE_AND_FORGET declare that mode and a completion_event.

    These are mutations that return 202 with a completion signal.
    """

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "command_cls_name,constructor_kwargs",
        [
            ("RestartAgentCommand", {"session_id": "s1"}),
            ("CloseSessionCommand", {"session_id": "s1"}),
        ],
        ids=[
            "restart_agent",
            "close_session",
        ],
    )
    def test_fire_and_forget_commands_declare_ff_mode(
        self, command_cls_name: str, constructor_kwargs: dict[str, str]
    ) -> None:
        """FIRE_AND_FORGET commands declare that response mode."""
        import teleclaude.types.commands as cmds
        from teleclaude.types.commands import ResponseMode

        cls = getattr(cmds, command_cls_name)
        instance = cls(**constructor_kwargs)
        assert instance.response_mode == ResponseMode.FIRE_AND_FORGET

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "command_cls_name,constructor_kwargs",
        [
            ("RestartAgentCommand", {"session_id": "s1"}),
            ("CloseSessionCommand", {"session_id": "s1"}),
        ],
        ids=[
            "restart_agent",
            "close_session",
        ],
    )
    def test_fire_and_forget_commands_have_completion_event(
        self, command_cls_name: str, constructor_kwargs: dict[str, str]
    ) -> None:
        """Every FIRE_AND_FORGET command declares a non-empty completion_event string."""
        import teleclaude.types.commands as cmds

        cls = getattr(cmds, command_cls_name)
        instance = cls(**constructor_kwargs)
        assert isinstance(instance.completion_event, str)
        assert len(instance.completion_event) > 0


class TestSystemCommandDeclaredMode:
    """SystemCommand declares a response mode consistent with its operational pattern."""

    @pytest.mark.unit
    def test_system_command_has_response_mode(self) -> None:
        """SystemCommand declares a response_mode field."""
        from teleclaude.types.commands import ResponseMode, SystemCommand

        cmd = SystemCommand(command="test", args=[])
        assert isinstance(cmd.response_mode, ResponseMode)


class TestFireAndForgetConstructionInvariant:
    """FIRE_AND_FORGET without completion_event must fail at construction time."""

    @pytest.mark.unit
    def test_ff_command_without_completion_event_raises_at_construction(self) -> None:
        """Constructing a FIRE_AND_FORGET command with completion_event=None raises.

        This is the fail-fast invariant from FR-1: enforcement at construction,
        not at dispatch.
        """
        from teleclaude.types.commands import CommandType, InternalCommand, ResponseMode

        with pytest.raises((ValueError, TypeError)):
            InternalCommand(
                command_type=CommandType.CLOSE_SESSION,
                response_mode=ResponseMode.FIRE_AND_FORGET,
                completion_event=None,
            )
