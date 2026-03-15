"""Characterization tests for teleclaude.transport.redis_transport._request_response."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.models import MessageMetadata
from teleclaude.transport.redis_transport._transport import RedisTransport


@pytest.fixture
def transport() -> RedisTransport:
    with patch("teleclaude.transport.redis_transport._connection.Redis"):
        t = RedisTransport(MagicMock())
        t.redis = AsyncMock()
        return t


class TestSignalObservation:
    @pytest.mark.unit
    async def test_sets_redis_key_with_ttl(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)

        await transport.signal_observation("target-host", "session-abc", 60)

        mock_redis.setex.assert_called_once()
        key_arg, ttl_arg, _ = mock_redis.setex.call_args.args
        assert key_arg == "observation:target-host:session-abc"
        assert ttl_arg == 60

    @pytest.mark.unit
    async def test_payload_includes_observer_name(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)

        await transport.signal_observation("target-host", "session-abc", 30)

        _, _, payload_str = mock_redis.setex.call_args.args
        payload = json.loads(payload_str)
        assert payload["observer"] == transport.computer_name

    @pytest.mark.unit
    async def test_payload_includes_started_at_timestamp(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        transport._get_redis = AsyncMock(return_value=mock_redis)
        before = time.time()

        await transport.signal_observation("target-host", "session-abc", 30)

        _, _, payload_str = mock_redis.setex.call_args.args
        payload = json.loads(payload_str)
        assert payload["started_at"] >= before


class TestIsSessionObserved:
    @pytest.mark.unit
    async def test_returns_true_when_observation_key_exists(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=1)
        transport._get_redis = AsyncMock(return_value=mock_redis)

        result = await transport.is_session_observed("session-xyz")
        assert result is True

    @pytest.mark.unit
    async def test_returns_false_when_key_absent(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=0)
        transport._get_redis = AsyncMock(return_value=mock_redis)

        result = await transport.is_session_observed("session-xyz")
        assert result is False

    @pytest.mark.unit
    async def test_checks_correct_key_for_self(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=0)
        transport._get_redis = AsyncMock(return_value=mock_redis)

        await transport.is_session_observed("my-session")
        key_arg = mock_redis.exists.call_args.args[0]
        assert key_arg == f"observation:{transport.computer_name}:my-session"


class TestSendRequest:
    @pytest.mark.unit
    async def test_returns_message_id_string(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value=b"1234567890-0")
        transport._get_redis = AsyncMock(return_value=mock_redis)

        result = await transport.send_request("target", "list_sessions", MessageMetadata())
        assert result == "1234567890-0"

    @pytest.mark.unit
    async def test_sends_to_correct_message_stream(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value=b"msg-id-0")
        transport._get_redis = AsyncMock(return_value=mock_redis)

        await transport.send_request("target-computer", "list_sessions", MessageMetadata())
        stream_arg = mock_redis.xadd.call_args.args[0]
        assert stream_arg == "messages:target-computer"

    @pytest.mark.unit
    async def test_includes_command_in_message_data(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value=b"msg-id-0")
        transport._get_redis = AsyncMock(return_value=mock_redis)

        await transport.send_request("target", "restart", MessageMetadata())
        data_arg = mock_redis.xadd.call_args.args[1]
        assert data_arg[b"command"] == b"restart"

    @pytest.mark.unit
    async def test_includes_session_id_when_provided(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value=b"msg-id-0")
        transport._get_redis = AsyncMock(return_value=mock_redis)

        await transport.send_request("target", "process_message", MessageMetadata(), session_id="sess-1")
        data_arg = mock_redis.xadd.call_args.args[1]
        assert data_arg[b"session_id"] == b"sess-1"


class TestSendResponse:
    @pytest.mark.unit
    async def test_returns_response_id_string(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value=b"response-id-0")
        transport._get_redis = AsyncMock(return_value=mock_redis)

        result = await transport.send_response("orig-msg-1", '{"status":"ok"}')
        assert result == "response-id-0"

    @pytest.mark.unit
    async def test_sends_to_output_stream_keyed_by_computer_and_message(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value=b"resp-0")
        transport._get_redis = AsyncMock(return_value=mock_redis)

        await transport.send_response("msg-id-123", "response")
        stream_arg = mock_redis.xadd.call_args.args[0]
        assert stream_arg == f"output:{transport.computer_name}:msg-id-123"

    @pytest.mark.unit
    async def test_payload_contains_chunk_field(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value=b"resp-0")
        transport._get_redis = AsyncMock(return_value=mock_redis)

        await transport.send_response("msg-id", '{"data":"value"}')
        data_arg = mock_redis.xadd.call_args.args[1]
        assert data_arg[b"chunk"] == b'{"data":"value"}'


class TestReadResponse:
    @pytest.mark.unit
    async def test_returns_chunk_data_on_first_message(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        fake_entry = {b"chunk": b'{"result":"ok"}', b"timestamp": b"1234"}
        mock_redis.xread = AsyncMock(return_value=[(b"output:target:msg-1", [(b"entry-0", fake_entry)])])
        transport._get_redis = AsyncMock(return_value=mock_redis)

        result = await transport.read_response("msg-1", timeout=1.0, target_computer="target")
        assert result == '{"result":"ok"}'

    @pytest.mark.unit
    async def test_raises_timeout_error_when_no_response(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.xread = AsyncMock(return_value=[])
        transport._get_redis = AsyncMock(return_value=mock_redis)

        with pytest.raises(TimeoutError):
            await transport.read_response("msg-1", timeout=0.05, target_computer="target")

    @pytest.mark.unit
    def test_poll_output_stream_raises_not_implemented(self, transport: RedisTransport) -> None:
        with pytest.raises(NotImplementedError):
            transport.poll_output_stream("req-id")

    @pytest.mark.unit
    async def test_uses_target_computer_in_stream_name(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.xread = AsyncMock(return_value=[])
        transport._get_redis = AsyncMock(return_value=mock_redis)

        with pytest.raises(TimeoutError):
            await transport.read_response("msg-42", timeout=0.05, target_computer="other-host")
        stream_arg = mock_redis.xread.call_args.args[0]
        assert b"output:other-host:msg-42" in stream_arg


class TestSendSystemCommand:
    @pytest.mark.unit
    async def test_returns_message_id_string(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value=b"sys-msg-0")
        transport._get_redis = AsyncMock(return_value=mock_redis)

        result = await transport.send_system_command("target", "restart")
        assert result == "sys-msg-0"

    @pytest.mark.unit
    async def test_sends_to_target_message_stream(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value=b"id-0")
        transport._get_redis = AsyncMock(return_value=mock_redis)

        await transport.send_system_command("target-machine", "health_check")
        stream_arg = mock_redis.xadd.call_args.args[0]
        assert stream_arg == "messages:target-machine"

    @pytest.mark.unit
    async def test_sets_type_field_to_system(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value=b"id-0")
        transport._get_redis = AsyncMock(return_value=mock_redis)

        await transport.send_system_command("target", "health_check")
        data_arg = mock_redis.xadd.call_args.args[1]
        assert data_arg[b"type"] == b"system"


class TestGetSystemCommandStatus:
    @pytest.mark.unit
    async def test_returns_unknown_when_key_missing(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        transport._get_redis = AsyncMock(return_value=mock_redis)

        result = await transport.get_system_command_status("target", "restart")
        assert result == {"status": "unknown"}

    @pytest.mark.unit
    async def test_returns_parsed_status_dict(self, transport: RedisTransport) -> None:
        status = {"status": "success", "timestamp": "2024-01-01T00:00:00Z"}
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(status).encode())
        transport._get_redis = AsyncMock(return_value=mock_redis)

        result = await transport.get_system_command_status("target", "restart")
        assert result["status"] == "success"

    @pytest.mark.unit
    async def test_returns_error_for_non_dict_response(self, transport: RedisTransport) -> None:
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b'"just-a-string"')
        transport._get_redis = AsyncMock(return_value=mock_redis)

        result = await transport.get_system_command_status("target", "restart")
        assert result["status"] == "error"
