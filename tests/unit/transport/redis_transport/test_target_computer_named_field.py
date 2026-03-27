# guard: no-companion
"""Test spec (xfail) for R3: target_computer and actor context promoted to named fields.

target_computer and actor context fields (actor_id, actor_name, actor_role,
actor_agent, actor_computer) must not be injected into channel_metadata — which
no longer exists as a property. They must travel via named fields on the metadata
or command objects.

Remove ``pytestmark = pytest.mark.xfail`` once all tests pass after implementation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTargetComputerNamedField:
    """R3: Redis transport must route target_computer via named field."""

    @pytest.mark.unit
    def test_redis_transport_metadata_has_target_computer_field(self) -> None:
        """RedisTransportMetadata already has target_computer — verify it's the named carrier."""
        from teleclaude.core.models._adapter import RedisTransportMetadata

        meta = RedisTransportMetadata(target_computer="remote-box")
        assert meta.target_computer == "remote-box"
        serialized = meta.to_dict()
        assert serialized["target_computer"] == "remote-box"

    @pytest.mark.unit
    async def test_handle_incoming_message_does_not_inject_target_computer_into_dict(
        self,
    ) -> None:
        """target_computer must not be written to any dict on the metadata.

        After R2+R3, channel_metadata does not exist as a property. target_computer
        must travel via RedisTransportMetadata.target_computer or equivalent named field.
        """
        from teleclaude.transport.redis_transport._transport import RedisTransport
        from teleclaude.types.commands import CreateSessionCommand

        with patch("teleclaude.transport.redis_transport._connection.Redis"):
            transport = RedisTransport(MagicMock())
            transport.redis = AsyncMock()

        captured_commands: list[object] = []

        async def capture_execute(command: object) -> dict[str, object]:  # guard: loose-dict — mock envelope
            captured_commands.append(command)
            return {"status": "success", "data": {"session_id": "sess-test"}}

        transport._execute_command = capture_execute  # pyright: ignore[reportAttributeAccessIssue]
        transport.send_response = AsyncMock()

        raw_data: dict[bytes, bytes] = {
            b"type": b"command",
            b"command": b"new_session",
            b"origin": b"terminal",
            b"project_path": b"/tmp/project",
            b"initiator": b"remote-box",
        }

        await transport._handle_incoming_message("msg-001", raw_data)

        assert len(captured_commands) == 1, "_execute_command must be called exactly once"
        cmd = captured_commands[0]
        assert isinstance(cmd, CreateSessionCommand)

        # channel_metadata property should not exist on the command
        assert not hasattr(cmd, "channel_metadata"), "CreateSessionCommand must not have channel_metadata property"

    @pytest.mark.unit
    def test_redis_mapper_does_not_produce_channel_metadata(self) -> None:
        """Redis mapper must not produce commands with channel_metadata."""
        from teleclaude.core.command_mapper import CommandMapper
        from teleclaude.types.commands import CreateSessionCommand

        cmd = CommandMapper.map_redis_input(
            "new_session",
            origin="terminal",
            initiator="remote-box",
        )
        assert isinstance(cmd, CreateSessionCommand)
        assert not hasattr(cmd, "channel_metadata"), "CreateSessionCommand must not have channel_metadata attribute"


@pytest.mark.xfail(reason="Deferred: Task 7 — actor context named fields not yet added to MessageMetadata")
class TestActorContextNamedFields:
    """R3: Actor context must use named fields, not channel_metadata dicts."""

    @pytest.mark.unit
    def test_message_metadata_has_actor_fields(self) -> None:
        """MessageMetadata must have named fields for actor context."""
        from teleclaude.core.models._snapshot import MessageMetadata

        # These fields must exist on MessageMetadata (xfail spec — fields not yet added)
        meta = MessageMetadata(  # type: ignore[call-arg]
            actor_id="user-123",  # pyright: ignore[reportCallIssue]
            actor_name="Test User",  # pyright: ignore[reportCallIssue]
            actor_role="system",  # pyright: ignore[reportCallIssue]
            actor_agent="system",  # pyright: ignore[reportCallIssue]
            actor_computer="remote-box",  # pyright: ignore[reportCallIssue]
        )
        assert meta.actor_id == "user-123"  # pyright: ignore[reportAttributeAccessIssue]
        assert meta.actor_name == "Test User"  # pyright: ignore[reportAttributeAccessIssue]
        assert meta.actor_role == "system"  # pyright: ignore[reportAttributeAccessIssue]
        assert meta.actor_agent == "system"  # pyright: ignore[reportAttributeAccessIssue]
        assert meta.actor_computer == "remote-box"  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    def test_fanout_does_not_construct_channel_metadata_dict(self) -> None:
        """Fanout coordinator must pass actor context via named fields, not a dict.

        The fanout coordinator at _fanout.py:330 currently constructs a
        channel_metadata dict with actor_id, actor_name, etc. After R3,
        these must be named fields on MessageMetadata.
        """
        import ast

        from teleclaude.core.agent_coordinator import _fanout

        source = ast.parse(open(_fanout.__file__).read())
        for node in ast.walk(source):
            if isinstance(node, ast.keyword) and node.arg == "channel_metadata":
                pytest.fail(
                    "Fanout coordinator must not construct channel_metadata dicts; "
                    "actor context must use named fields on MessageMetadata"
                )
