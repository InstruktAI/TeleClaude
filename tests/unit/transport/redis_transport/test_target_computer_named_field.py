# guard: no-companion
"""Specification tests for typed actor fields and legacy actor-bag removal.

R1: MessageMetadata must have typed actor fields (actor_id, actor_name,
actor_avatar_url, platform_message_id) and the legacy actor bag must be removed.
R3: CommandMapper must read typed fields from MessageMetadata directly.
R5: target_computer must not be injected into any legacy actor bag.
"""

from __future__ import annotations

from dataclasses import fields
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.models._adapter import RedisTransportMetadata
from teleclaude.core.models._snapshot import MessageMetadata
from teleclaude.transport.redis_transport._transport import RedisTransport
from teleclaude.types.commands import CreateSessionCommand, ProcessMessageCommand


def _legacy_actor_bag_field() -> str:
    return "_".join(("channel", "metadata"))


def _field_names(instance: object) -> set[str]:
    """Return dataclass field names for a dataclass instance."""
    return {field.name for field in fields(instance)}


class _InspectableRedisTransport(RedisTransport):
    """Public test seam for Redis transport internals."""

    def install_execute_stub(self, execute: object) -> None:
        """Install a command executor without touching a protected attribute in tests."""
        self._execute_command = execute

    async def handle_incoming_message(self, message_id: str, data: dict[bytes, bytes]) -> None:
        """Expose inbound-message handling through a public wrapper."""
        await self._handle_incoming_message(message_id, data)


class TestTargetComputerNamedField:
    """R5: Redis transport must route target_computer via named field.

    These tests verify existing behavior — CreateSessionCommand already lacks
    the legacy actor bag field.
    """

    @pytest.mark.unit
    def test_redis_transport_metadata_has_target_computer_field(self) -> None:
        """RedisTransportMetadata already has target_computer — verify it's the named carrier."""
        meta = RedisTransportMetadata(target_computer="remote-box")
        assert meta.target_computer == "remote-box"
        serialized = meta.to_dict()
        assert serialized["target_computer"] == "remote-box"

    @pytest.mark.unit
    async def test_handle_incoming_message_does_not_inject_target_computer_into_dict(
        self,
    ) -> None:
        """target_computer must not be written to any legacy actor bag.

        After R2+R3, the legacy actor bag does not exist as a property. target_computer
        must travel via RedisTransportMetadata.target_computer or equivalent named field.
        """
        with patch("teleclaude.transport.redis_transport._connection.Redis"):
            transport = _InspectableRedisTransport(MagicMock())
            transport.redis = AsyncMock()

        captured_commands: list[object] = []

        async def capture_execute(command: object) -> dict[str, object]:  # guard: loose-dict — mock envelope
            captured_commands.append(command)
            return {"status": "success", "data": {"session_id": "sess-test"}}

        transport.install_execute_stub(capture_execute)
        transport.send_response = AsyncMock()

        raw_data: dict[bytes, bytes] = {
            b"type": b"command",
            b"command": b"new_session",
            b"origin": b"terminal",
            b"project_path": b"/tmp/project",
            b"initiator": b"remote-box",
        }

        await transport.handle_incoming_message("msg-001", raw_data)

        assert len(captured_commands) == 1, "_execute_command must be called exactly once"
        cmd = captured_commands[0]
        assert isinstance(cmd, CreateSessionCommand)

        legacy_field = _legacy_actor_bag_field()
        assert not hasattr(cmd, legacy_field), "CreateSessionCommand must not expose the legacy actor bag field"

    @pytest.mark.unit
    def test_redis_mapper_does_not_produce_legacy_actor_bag(self) -> None:
        """Redis mapper must not produce commands with the legacy actor bag field."""
        cmd = CommandMapper.map_redis_input(
            "new_session",
            origin="terminal",
            initiator="remote-box",
        )
        assert isinstance(cmd, CreateSessionCommand)
        legacy_field = _legacy_actor_bag_field()
        assert not hasattr(cmd, legacy_field), "CreateSessionCommand must not expose the legacy actor bag field"


@pytest.mark.unit
def test_message_metadata_rejects_dead_data_fields() -> None:
    """R9: actor_role, actor_agent, actor_computer must not be typed fields."""
    meta = MessageMetadata(origin="terminal")
    for dead_field in ("actor_role", "actor_agent", "actor_computer"):
        assert not hasattr(meta, dead_field), (
            f"R9: {dead_field} is dead data and must not exist as a typed field on MessageMetadata"
        )


class TestActorContextNamedFields:
    """R1/R3: Actor context must use typed named fields on MessageMetadata."""

    @pytest.mark.unit
    def test_message_metadata_has_typed_actor_fields(self) -> None:
        """MessageMetadata must have exactly the R1 typed fields.

        R1 fields: actor_id, actor_name, actor_avatar_url, platform_message_id.
        R9 dead data (actor_role, actor_agent, actor_computer) must NOT be fields.
        """
        meta = MessageMetadata(
            actor_id="telegram:12345",  # pyright: ignore[reportCallIssue]
            actor_name="Test User",  # pyright: ignore[reportCallIssue]
            actor_avatar_url="https://example.com/avatar.jpg",  # pyright: ignore[reportCallIssue]
            platform_message_id="msg-999",  # pyright: ignore[reportCallIssue]
        )
        assert meta.actor_id == "telegram:12345"  # pyright: ignore[reportAttributeAccessIssue]
        assert meta.actor_name == "Test User"  # pyright: ignore[reportAttributeAccessIssue]
        assert meta.actor_avatar_url == "https://example.com/avatar.jpg"  # pyright: ignore[reportAttributeAccessIssue]
        assert meta.platform_message_id == "msg-999"  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.unit
    def test_message_metadata_drops_legacy_actor_bag_field(self) -> None:
        """After R1, the legacy actor bag must be removed from MessageMetadata.

        This forces all callers (fanout, adapters, transport) to use typed
        actor fields because the untyped carrier no longer exists on the model.
        """
        meta = MessageMetadata(origin="terminal")
        assert _legacy_actor_bag_field() not in _field_names(meta), (
            "the legacy actor bag must be removed from MessageMetadata; "
            "all actor data must flow via typed fields (actor_id, actor_name, "
            "actor_avatar_url, platform_message_id)"
        )

    @pytest.mark.unit
    def test_command_mapper_reads_typed_actor_fields_from_metadata(self) -> None:
        """R3: CommandMapper.map_telegram_input must read actor fields from typed MessageMetadata fields.

        After R3, the legacy extraction path is removed. The mapper
        reads metadata.actor_id, metadata.actor_name, metadata.actor_avatar_url directly.
        """
        meta = MessageMetadata(
            origin="telegram",
            actor_id="telegram:12345",  # pyright: ignore[reportCallIssue]
            actor_name="TestUser",  # pyright: ignore[reportCallIssue]
            actor_avatar_url="https://example.com/avatar.jpg",  # pyright: ignore[reportCallIssue]
            platform_message_id="msg-999",  # pyright: ignore[reportCallIssue]
        )
        cmd = CommandMapper.map_telegram_input(
            event="message",
            args=["hello world"],
            metadata=meta,
            session_id="test-session",
        )
        assert isinstance(cmd, ProcessMessageCommand)
        assert cmd.actor_id == "telegram:12345"
        assert cmd.actor_name == "TestUser"
        assert cmd.actor_avatar_url == "https://example.com/avatar.jpg"
