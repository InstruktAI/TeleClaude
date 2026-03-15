"""Characterization tests for teleclaude.transport.redis_transport._messaging."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.transport.redis_transport._transport import RedisTransport


@pytest.fixture
def transport() -> RedisTransport:
    with patch("teleclaude.transport.redis_transport._connection.Redis"):
        t = RedisTransport(MagicMock())
        t.redis = AsyncMock()
        return t


class TestParseRedisMessage:
    @pytest.mark.unit
    def test_parses_msg_type_from_bytes(self, transport: RedisTransport) -> None:
        data = {b"type": b"system", b"command": b"restart"}
        result = transport._parse_redis_message(data)
        assert result.msg_type == "system"

    @pytest.mark.unit
    def test_parses_session_id_as_none_when_empty(self, transport: RedisTransport) -> None:
        data = {b"session_id": b"", b"command": b"start_agent"}
        result = transport._parse_redis_message(data)
        assert result.session_id is None

    @pytest.mark.unit
    def test_parses_session_id_when_present(self, transport: RedisTransport) -> None:
        data = {b"session_id": b"abc-123", b"command": b"process_message"}
        result = transport._parse_redis_message(data)
        assert result.session_id == "abc-123"

    @pytest.mark.unit
    def test_defaults_origin_to_redis_when_missing(self, transport: RedisTransport) -> None:
        from teleclaude.core.origins import InputOrigin

        data = {b"command": b"start_agent"}
        result = transport._parse_redis_message(data)
        assert result.origin == InputOrigin.REDIS.value

    @pytest.mark.unit
    def test_parses_channel_metadata_as_dict(self, transport: RedisTransport) -> None:
        meta = {"target_computer": "other"}
        data = {
            b"command": b"create_session",
            b"channel_metadata": json.dumps(meta).encode("utf-8"),
        }
        result = transport._parse_redis_message(data)
        assert result.channel_metadata == meta

    @pytest.mark.unit
    def test_channel_metadata_none_when_invalid_json(self, transport: RedisTransport) -> None:
        data = {b"command": b"create_session", b"channel_metadata": b"not-json"}
        result = transport._parse_redis_message(data)
        assert result.channel_metadata is None

    @pytest.mark.unit
    def test_parses_launch_intent_as_dict(self, transport: RedisTransport) -> None:
        intent = {"kind": "new", "agent": "claude"}
        data = {
            b"command": b"create_session",
            b"launch_intent": json.dumps(intent).encode("utf-8"),
        }
        result = transport._parse_redis_message(data)
        assert result.launch_intent == intent

    @pytest.mark.unit
    def test_launch_intent_none_when_invalid_json(self, transport: RedisTransport) -> None:
        data = {b"command": b"create_session", b"launch_intent": b"bad"}
        result = transport._parse_redis_message(data)
        assert result.launch_intent is None

    @pytest.mark.unit
    def test_initiator_none_when_empty(self, transport: RedisTransport) -> None:
        data = {b"command": b"create_session", b"initiator": b""}
        result = transport._parse_redis_message(data)
        assert result.initiator is None

    @pytest.mark.unit
    def test_parses_project_path_and_title(self, transport: RedisTransport) -> None:
        data = {
            b"command": b"create_session",
            b"project_path": b"/repo/myproject",
            b"title": b"My Session",
        }
        result = transport._parse_redis_message(data)
        assert result.project_path == "/repo/myproject"
        assert result.title == "My Session"


class TestHandleAgentNotificationCommand:
    @pytest.mark.unit
    async def test_stop_notification_with_fewer_than_2_args_returns_error(self, transport: RedisTransport) -> None:
        result = await transport._handle_agent_notification_command("stop_notification", ["only-one-arg"])
        assert result["status"] == "error"

    @pytest.mark.unit
    async def test_stop_notification_calls_agent_event_handler(self, transport: RedisTransport) -> None:
        transport.client.agent_event_handler = AsyncMock()
        result = await transport._handle_agent_notification_command(
            "stop_notification", ["session-id", "source-computer"]
        )
        assert result["status"] == "success"
        transport.client.agent_event_handler.assert_called_once()

    @pytest.mark.unit
    async def test_unknown_command_returns_error(self, transport: RedisTransport) -> None:
        result = await transport._handle_agent_notification_command("unknown_cmd", [])
        assert result["status"] == "error"

    @pytest.mark.unit
    async def test_stop_notification_decodes_base64_title(self, transport: RedisTransport) -> None:
        import base64

        transport.client.agent_event_handler = AsyncMock()
        title_b64 = base64.b64encode(b"My Title").decode()
        result = await transport._handle_agent_notification_command(
            "stop_notification", ["sess-id", "comp-name", title_b64]
        )
        assert result["status"] == "success"
        ctx = transport.client.agent_event_handler.call_args[0][0]
        # Title is preserved in the raw mapping of AgentStopPayload
        assert ctx.data.raw.get("title") == "My Title"


class TestHandleSystemMessage:
    @pytest.mark.unit
    async def test_emits_system_command_event(self, transport: RedisTransport) -> None:
        with patch("teleclaude.transport.redis_transport._messaging.event_bus") as mock_bus:
            data = {b"command": b"restart", b"from_computer": b"other-host"}
            await transport._handle_system_message(data)
            mock_bus.emit.assert_called_once()
            args = mock_bus.emit.call_args[0]
            assert args[0] == "system_command"

    @pytest.mark.unit
    async def test_empty_command_does_not_emit_event(self, transport: RedisTransport) -> None:
        with patch("teleclaude.transport.redis_transport._messaging.event_bus") as mock_bus:
            data = {b"command": b"", b"from_computer": b"other-host"}
            await transport._handle_system_message(data)
            mock_bus.emit.assert_not_called()

    @pytest.mark.unit
    async def test_unknown_computer_defaults_to_unknown(self, transport: RedisTransport) -> None:
        with patch("teleclaude.transport.redis_transport._messaging.event_bus") as mock_bus:
            data = {b"command": b"health_check"}
            await transport._handle_system_message(data)
            ctx = mock_bus.emit.call_args[0][1]
            assert ctx.from_computer == "unknown"


class TestExecuteCommand:
    @pytest.mark.unit
    async def test_unsupported_command_type_returns_error_envelope(self, transport: RedisTransport) -> None:
        result = await transport._execute_command(object())
        assert result["status"] == "error"
        assert "error" in result

    @pytest.mark.unit
    async def test_exception_in_command_returns_error_envelope(self, transport: RedisTransport) -> None:
        from teleclaude.types.commands import ProcessMessageCommand

        cmd = MagicMock(spec=ProcessMessageCommand)
        with patch("teleclaude.transport.redis_transport._messaging.get_command_service") as mock_svc:
            mock_svc.return_value.process_message = AsyncMock(side_effect=RuntimeError("boom"))
            result = await transport._execute_command(cmd)
        assert result["status"] == "error"
        assert "boom" in str(result["error"])
