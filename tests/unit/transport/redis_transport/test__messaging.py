"""Characterization tests for teleclaude.transport.redis_transport._messaging."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.models import JsonDict
from teleclaude.transport.redis_transport._transport import RedisTransport
from teleclaude.types.commands import ProcessMessageCommand


class _InspectableRedisTransport(RedisTransport):
    """Public test seam for exercising RedisTransport internals."""

    def parse_message(self, data: dict[bytes, bytes]) -> object:
        """Expose message parsing through a public wrapper."""
        return self._parse_redis_message(data)

    async def handle_agent_notification_command(self, command: str, args: list[str]) -> JsonDict:
        """Expose agent-notification handling through a public wrapper."""
        return await self._handle_agent_notification_command(command, args)

    async def handle_system_message(self, data: dict[bytes, bytes]) -> None:
        """Expose system-message handling through a public wrapper."""
        await self._handle_system_message(data)

    async def execute_command(self, command: object) -> JsonDict:
        """Expose command execution through a public wrapper."""
        return await self._execute_command(command)


@pytest.fixture(name="redis_transport")
def fixture_redis_transport() -> _InspectableRedisTransport:
    """Build a Redis transport with the connection layer patched out."""
    with patch("teleclaude.transport.redis_transport._connection.Redis"):
        t = _InspectableRedisTransport(MagicMock())
        t.redis = AsyncMock()
        return t


def _legacy_actor_field_bytes() -> bytes:
    return "_".join(("channel", "metadata")).encode("utf-8")


class TestParseRedisMessage:
    """Characterize Redis message parsing behavior."""

    @pytest.mark.unit
    def test_parses_msg_type_from_bytes(self, redis_transport: RedisTransport) -> None:
        """The parser decodes the message type from bytes."""
        data = {b"type": b"system", b"command": b"restart", b"origin": b"terminal"}
        result = redis_transport.parse_message(data)
        assert result.msg_type == "system"

    @pytest.mark.unit
    def test_parses_session_id_as_none_when_empty(self, redis_transport: RedisTransport) -> None:
        """Empty session ids normalize to None."""
        data = {b"session_id": b"", b"command": b"start_agent", b"origin": b"terminal"}
        result = redis_transport.parse_message(data)
        assert result.session_id is None

    @pytest.mark.unit
    def test_parses_session_id_when_present(self, redis_transport: RedisTransport) -> None:
        """Non-empty session ids are preserved."""
        data = {b"session_id": b"abc-123", b"command": b"process_message", b"origin": b"terminal"}
        result = redis_transport.parse_message(data)
        assert result.session_id == "abc-123"

    @pytest.mark.unit
    def test_raises_when_origin_missing(self, redis_transport: RedisTransport) -> None:
        """Missing origins are rejected."""
        data = {b"command": b"start_agent"}
        with pytest.raises(ValueError, match="missing origin"):
            redis_transport.parse_message(data)

    @pytest.mark.unit
    def test_parses_typed_actor_fields(self, redis_transport: RedisTransport) -> None:
        """Typed actor fields are decoded individually."""
        data = {
            b"command": b"process_message",
            b"actor_id": b"telegram:12345",
            b"actor_name": b"TestUser",
            b"actor_avatar_url": b"https://example.com/avatar.jpg",
            b"platform_message_id": b"msg-123",
            b"origin": b"telegram",
        }
        result = redis_transport.parse_message(data)
        assert result.actor_id == "telegram:12345"
        assert result.actor_name == "TestUser"
        assert result.actor_avatar_url == "https://example.com/avatar.jpg"
        assert result.platform_message_id == "msg-123"

    @pytest.mark.unit
    def test_ignores_legacy_actor_bag(self, redis_transport: RedisTransport) -> None:
        """Legacy actor-bag bytes are ignored by the parser."""
        data = {
            b"command": b"create_session",
            _legacy_actor_field_bytes(): b"not-json",
            b"origin": b"terminal",
        }
        result = redis_transport.parse_message(data)
        assert result.actor_id is None
        assert result.actor_name is None
        assert result.actor_avatar_url is None
        assert result.platform_message_id is None

    @pytest.mark.unit
    def test_parses_launch_intent_as_dict(self, redis_transport: RedisTransport) -> None:
        """Launch-intent JSON is parsed into a dict."""
        intent = {"kind": "new", "agent": "claude"}
        data = {
            b"command": b"create_session",
            b"launch_intent": json.dumps(intent).encode("utf-8"),
            b"origin": b"terminal",
        }
        result = redis_transport.parse_message(data)
        assert result.launch_intent == intent

    @pytest.mark.unit
    def test_launch_intent_none_when_invalid_json(self, redis_transport: RedisTransport) -> None:
        """Invalid launch-intent JSON is ignored."""
        data = {b"command": b"create_session", b"launch_intent": b"bad", b"origin": b"terminal"}
        result = redis_transport.parse_message(data)
        assert result.launch_intent is None

    @pytest.mark.unit
    def test_initiator_none_when_empty(self, redis_transport: RedisTransport) -> None:
        """Empty initiators normalize to None."""
        data = {b"command": b"create_session", b"initiator": b"", b"origin": b"terminal"}
        result = redis_transport.parse_message(data)
        assert result.initiator is None

    @pytest.mark.unit
    def test_parses_project_path_and_title(self, redis_transport: RedisTransport) -> None:
        """Project path and title are preserved."""
        data = {
            b"command": b"create_session",
            b"project_path": b"/repo/myproject",
            b"title": b"My Session",
            b"origin": b"terminal",
        }
        result = redis_transport.parse_message(data)
        assert result.project_path == "/repo/myproject"
        assert result.title == "My Session"


class TestHandleAgentNotificationCommand:
    """Characterize agent-notification command handling."""

    @pytest.mark.unit
    async def test_stop_notification_with_fewer_than_2_args_returns_error(
        self, redis_transport: RedisTransport
    ) -> None:
        """Short stop-notification payloads return an error envelope."""
        result = await redis_transport.handle_agent_notification_command("stop_notification", ["only-one-arg"])
        assert result["status"] == "error"

    @pytest.mark.unit
    async def test_stop_notification_calls_agent_event_handler(self, redis_transport: RedisTransport) -> None:
        """Valid stop notifications notify the agent-event handler."""
        redis_transport.client.agent_event_handler = AsyncMock()
        result = await redis_transport.handle_agent_notification_command(
            "stop_notification", ["session-id", "source-computer"]
        )
        assert result["status"] == "success"
        redis_transport.client.agent_event_handler.assert_called_once()

    @pytest.mark.unit
    async def test_unknown_command_returns_error(self, redis_transport: RedisTransport) -> None:
        """Unknown agent-notification commands return an error envelope."""
        result = await redis_transport.handle_agent_notification_command("unknown_cmd", [])
        assert result["status"] == "error"

    @pytest.mark.unit
    async def test_stop_notification_decodes_base64_title(self, redis_transport: RedisTransport) -> None:
        """Base64 titles are decoded before the handler sees them."""
        redis_transport.client.agent_event_handler = AsyncMock()
        title_b64 = base64.b64encode(b"My Title").decode()
        result = await redis_transport.handle_agent_notification_command(
            "stop_notification", ["sess-id", "comp-name", title_b64]
        )
        assert result["status"] == "success"
        ctx = redis_transport.client.agent_event_handler.call_args[0][0]
        # Title is preserved in the raw mapping of AgentStopPayload
        assert ctx.data.raw.get("title") == "My Title"


class TestHandleSystemMessage:
    """Characterize system-message handling behavior."""

    @pytest.mark.unit
    async def test_emits_system_command_event(self, redis_transport: RedisTransport) -> None:
        """Non-empty system commands emit an event-bus entry."""
        with patch("teleclaude.transport.redis_transport._messaging.event_bus") as mock_bus:
            data = {b"command": b"restart", b"from_computer": b"other-host"}
            await redis_transport.handle_system_message(data)
            mock_bus.emit.assert_called_once()
            args = mock_bus.emit.call_args[0]
            assert args[0] == "system_command"

    @pytest.mark.unit
    async def test_empty_command_does_not_emit_event(self, redis_transport: RedisTransport) -> None:
        """Empty system commands are ignored."""
        with patch("teleclaude.transport.redis_transport._messaging.event_bus") as mock_bus:
            data = {b"command": b"", b"from_computer": b"other-host"}
            await redis_transport.handle_system_message(data)
            mock_bus.emit.assert_not_called()

    @pytest.mark.unit
    async def test_unknown_computer_defaults_to_unknown(self, redis_transport: RedisTransport) -> None:
        """Missing from_computer defaults to 'unknown'."""
        with patch("teleclaude.transport.redis_transport._messaging.event_bus") as mock_bus:
            data = {b"command": b"health_check"}
            await redis_transport.handle_system_message(data)
            ctx = mock_bus.emit.call_args[0][1]
            assert ctx.from_computer == "unknown"


class TestExecuteCommand:
    """Characterize command dispatch behavior."""

    @pytest.mark.unit
    async def test_unsupported_command_type_returns_error_envelope(self, redis_transport: RedisTransport) -> None:
        """Unsupported command objects return an error envelope."""
        result = await redis_transport.execute_command(object())
        assert result["status"] == "error"
        assert "error" in result

    @pytest.mark.unit
    async def test_exception_in_command_returns_error_envelope(self, redis_transport: RedisTransport) -> None:
        """Exceptions from command handlers are surfaced in the error envelope."""
        cmd = ProcessMessageCommand(session_id="s1", text="hi", origin="test")
        with patch("teleclaude.transport.redis_transport._messaging.get_command_service") as mock_svc:
            mock_svc.return_value.process_message = AsyncMock(side_effect=RuntimeError("boom"))
            result = await redis_transport.execute_command(cmd)
        assert result["status"] == "error"
        assert "boom" in str(result["error"])
