"""Unit tests for remote session-close forwarding over Redis request/response."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from teleclaude.api.session_remote import (
    REMOTE_CLOSE_TIMEOUT_SECONDS,
    dispatch_session_close_to_peer,
    is_remote_target,
)
from teleclaude.constants import EVENT_END_SESSION
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.models import MessageMetadata
from teleclaude.types.commands import CloseSessionCommand

_PEER_COMPUTER = "beta"
_SESSION_ID = "sess-7"
_MAPPED_SESSION_ID = "sess-42"
_PEER_ERROR_DETAIL = "no such session"


class _RecordingClient:
    """Minimal AdapterClient stand-in capturing the forwarded request."""

    def __init__(self, response: str | None = None, *, read_error: Exception | None = None) -> None:
        self._response = response
        self._read_error = read_error
        self.send_calls: list[tuple[str, str, MessageMetadata, str | None]] = []

    async def send_request(
        self,
        computer_name: str,
        command: str,
        metadata: MessageMetadata,
        session_id: str | None = None,
    ) -> str:
        self.send_calls.append((computer_name, command, metadata, session_id))
        return "msg-1"

    async def read_response(self, message_id: str, timeout: float = 3.0, target_computer: str | None = None) -> str:
        if self._read_error is not None:
            raise self._read_error
        assert self._response is not None
        return self._response


def test_is_remote_target_truth_table() -> None:
    assert is_remote_target(None, "alpha") is False
    assert is_remote_target("", "alpha") is False
    assert is_remote_target("local", "alpha") is False
    assert is_remote_target("alpha", "alpha") is False
    assert is_remote_target("beta", "alpha") is True


def test_inbound_end_session_maps_to_close_command() -> None:
    """The wire contract the forward relies on: peers map EVENT_END_SESSION to a close."""
    cmd = CommandMapper.map_redis_input(EVENT_END_SESSION, session_id=_MAPPED_SESSION_ID, origin="terminal")
    assert isinstance(cmd, CloseSessionCommand)
    assert cmd.session_id == _MAPPED_SESSION_ID


async def test_dispatch_forwards_end_session_command() -> None:
    client = _RecordingClient(response=json.dumps({"status": "success", "data": None}))

    await dispatch_session_close_to_peer(client, _PEER_COMPUTER, _SESSION_ID)

    assert len(client.send_calls) == 1
    computer_name, command, _metadata, session_id = client.send_calls[0]
    assert computer_name == _PEER_COMPUTER
    assert command == EVENT_END_SESSION
    assert session_id == _SESSION_ID


async def test_dispatch_without_client_is_unavailable() -> None:
    with pytest.raises(HTTPException) as exc:
        await dispatch_session_close_to_peer(None, _PEER_COMPUTER, _SESSION_ID)
    assert exc.value.status_code == 503


async def test_dispatch_propagates_peer_error_envelope() -> None:
    client = _RecordingClient(response=json.dumps({"status": "error", "error": _PEER_ERROR_DETAIL}))

    with pytest.raises(HTTPException) as exc:
        await dispatch_session_close_to_peer(client, _PEER_COMPUTER, _SESSION_ID)

    assert exc.value.status_code == 502
    assert _PEER_ERROR_DETAIL in str(exc.value.detail)


async def test_dispatch_timeout_maps_to_gateway_timeout() -> None:
    client = _RecordingClient(read_error=TimeoutError())

    with pytest.raises(HTTPException) as exc:
        await dispatch_session_close_to_peer(client, _PEER_COMPUTER, _SESSION_ID)

    assert exc.value.status_code == 504


async def test_dispatch_invalid_json_is_bad_gateway() -> None:
    client = _RecordingClient(response="not-json")

    with pytest.raises(HTTPException) as exc:
        await dispatch_session_close_to_peer(client, _PEER_COMPUTER, _SESSION_ID)

    assert exc.value.status_code == 502


def test_close_timeout_constant_is_positive() -> None:
    assert REMOTE_CLOSE_TIMEOUT_SECONDS > 0
