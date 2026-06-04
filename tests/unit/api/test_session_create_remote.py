"""Behavior tests for remote session creation over Redis."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest
from fastapi import HTTPException
from syrupy.assertion import SnapshotAssertion

from teleclaude.api.session_create_remote import REMOTE_CREATE_TIMEOUT_SECONDS, dispatch_session_create_to_peer
from teleclaude.api_models import CreateSessionRequest
from teleclaude.constants import EVENT_NEW_SESSION
from teleclaude.core.models import MessageMetadata, SessionLaunchKind

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient


class _RemoteSessionCreateClient:
    def __init__(
        self,
        *,
        target_computer: str,
        local_computer: str,
        project_path: str,
        startup_message: str,
        session_id: str,
        tmux_session_name: str,
    ) -> None:
        self.target_computer = target_computer
        self.local_computer = local_computer
        self.project_path = project_path
        self.startup_message = startup_message
        self.session_id = session_id
        self.tmux_session_name = tmux_session_name

    async def send_request(
        self,
        computer_name: str,
        command: str,
        metadata: MessageMetadata,
        session_id: str | None = None,
    ) -> str:
        if computer_name != self.target_computer:
            raise AssertionError("remote create must dispatch to the requested computer")
        if command != EVENT_NEW_SESSION:
            raise AssertionError("remote create must use the peer session-create command")
        if session_id is not None:
            raise AssertionError("session create is not scoped to an existing session")
        if metadata.human_role != "admin":
            raise AssertionError("remote create must forward the initiating identity to the peer")
        if metadata.origin != "web":
            raise AssertionError("remote create must carry the client origin, not the computer name")
        if metadata.project_path != self.project_path:
            raise AssertionError("remote create must carry the requested project path")
        launch_intent = metadata.launch_intent
        if launch_intent is None:
            raise AssertionError("remote create must carry a launch intent")
        if launch_intent.kind != SessionLaunchKind.AGENT_THEN_MESSAGE:
            raise AssertionError("remote create with a startup message must launch agent_then_message")
        if launch_intent.message != self.startup_message:
            raise AssertionError("remote create must carry the startup message")
        return "request-1"

    async def read_response(
        self,
        message_id: str,
        timeout: float = 3.0,
        target_computer: str | None = None,
    ) -> str:
        if message_id != "request-1":
            raise AssertionError("remote response must read the request just sent")
        if timeout != REMOTE_CREATE_TIMEOUT_SECONDS:
            raise AssertionError("remote session creation must wait long enough for peer startup")
        if target_computer != self.target_computer:
            raise AssertionError("remote response must read from the peer computer stream")
        return json.dumps(
            {
                "status": "success",
                "data": {
                    "session_id": self.session_id,
                    "tmux_session_name": self.tmux_session_name,
                },
            }
        )


class _RemoteSessionCreateErrorClient(_RemoteSessionCreateClient):
    async def read_response(
        self,
        message_id: str,
        timeout: float = 3.0,
        target_computer: str | None = None,
    ) -> str:
        _ = message_id, timeout, target_computer
        return json.dumps({"status": "error", "error": "peer rejected session create"})


class _RemoteSessionCreateTimeoutClient(_RemoteSessionCreateClient):
    async def read_response(
        self,
        message_id: str,
        timeout: float = 3.0,
        target_computer: str | None = None,
    ) -> str:
        _ = message_id, timeout, target_computer
        raise TimeoutError("peer response timed out")


class _RemoteSessionCreateTransportClient(_RemoteSessionCreateClient):
    async def read_response(
        self,
        message_id: str,
        timeout: float = 3.0,
        target_computer: str | None = None,
    ) -> str:
        _ = message_id, timeout, target_computer
        raise OSError("redis socket unavailable")


class _RemoteSessionCreateAgentClient(_RemoteSessionCreateClient):
    async def send_request(
        self,
        computer_name: str,
        command: str,
        metadata: MessageMetadata,
        session_id: str | None = None,
    ) -> str:
        if computer_name != self.target_computer:
            raise AssertionError("remote create must dispatch to the requested computer")
        if command != EVENT_NEW_SESSION:
            raise AssertionError("remote create must use the peer session-create command")
        if session_id is not None:
            raise AssertionError("session create is not scoped to an existing session")
        launch_intent = metadata.launch_intent
        if launch_intent is None:
            raise AssertionError("remote create must carry a launch intent")
        if launch_intent.kind != SessionLaunchKind.AGENT:
            raise AssertionError("native_session_id alone must not change launch kind")
        if launch_intent.native_session_id != "native-1":
            raise AssertionError("remote create must preserve native_session_id metadata")
        return "request-1"


def _make_client(client: _RemoteSessionCreateClient) -> AdapterClient:
    return cast("AdapterClient", client)


def _make_failure_case(
    client_type: type[_RemoteSessionCreateClient],
) -> tuple[str, str, CreateSessionRequest, _RemoteSessionCreateClient]:
    local_computer = "local-machine"
    remote_computer = "remote-machine"
    project_path = "/repo/demo"
    startup_message = "build cluster-followups"
    client = client_type(
        target_computer=remote_computer,
        local_computer=local_computer,
        project_path=project_path,
        startup_message=startup_message,
        session_id="remote-session",
        tmux_session_name="tc_remote-session",
    )
    request = CreateSessionRequest(
        computer=remote_computer,
        project_path=project_path,
        agent="codex",
        thinking_mode="slow",
        message=startup_message,
    )
    return local_computer, remote_computer, request, client


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_session_create_to_peer_returns_peer_owned_session(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    """Remote create unwraps a peer success envelope into an API response."""
    local_computer = "local-machine"
    remote_computer = "remote-machine"
    project_path = "/repo/demo"
    startup_message = "build cluster-followups"
    client = _RemoteSessionCreateClient(
        target_computer=remote_computer,
        local_computer=local_computer,
        project_path=project_path,
        startup_message=startup_message,
        session_id="remote-session",
        tmux_session_name="tc_remote-session",
    )
    monkeypatch.setattr("teleclaude.api.session_create_launch.assert_agent_enabled", lambda agent: agent)
    request = CreateSessionRequest(
        computer=remote_computer,
        project_path=project_path,
        agent="codex",
        thinking_mode="slow",
        message=startup_message,
    )

    response = await dispatch_session_create_to_peer(
        _make_client(client),
        remote_computer,
        request,
        identity_metadata=MessageMetadata(origin="web", human_role="admin"),
    )

    assert response.model_dump() == snapshot


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_session_create_to_peer_keeps_native_session_id_from_implying_resume(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    """Resume only happens when launch_kind explicitly requests it."""
    local_computer = "local-machine"
    remote_computer = "remote-machine"
    client = _RemoteSessionCreateAgentClient(
        target_computer=remote_computer,
        local_computer=local_computer,
        project_path="/repo/demo",
        startup_message="",
        session_id="remote-session",
        tmux_session_name="tc_remote-session",
    )
    monkeypatch.setattr("teleclaude.api.session_create_launch.assert_agent_enabled", lambda agent: agent)
    request = CreateSessionRequest(
        computer=remote_computer,
        project_path="/repo/demo",
        agent="codex",
        thinking_mode="slow",
        native_session_id="native-1",
    )

    response = await dispatch_session_create_to_peer(
        _make_client(client),
        remote_computer,
        request,
        identity_metadata=MessageMetadata(origin="web", human_role="admin"),
    )

    assert response.model_dump() == snapshot


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_session_create_to_peer_maps_peer_error_to_bad_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote peer rejection surfaces as a gateway failure."""
    _local_computer, remote_computer, request, client = _make_failure_case(_RemoteSessionCreateErrorClient)
    monkeypatch.setattr("teleclaude.api.session_create_launch.assert_agent_enabled", lambda agent: agent)

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_session_create_to_peer(
            _make_client(client),
            remote_computer,
            request,
            identity_metadata=MessageMetadata(origin="web", human_role="admin"),
        )

    assert exc_info.value.status_code == 502


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_session_create_to_peer_maps_peer_timeout_to_gateway_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote peer response timeout surfaces as a gateway timeout."""
    _local_computer, remote_computer, request, client = _make_failure_case(_RemoteSessionCreateTimeoutClient)
    monkeypatch.setattr("teleclaude.api.session_create_launch.assert_agent_enabled", lambda agent: agent)

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_session_create_to_peer(
            _make_client(client),
            remote_computer,
            request,
            identity_metadata=MessageMetadata(origin="web", human_role="admin"),
        )

    assert exc_info.value.status_code == 504


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_session_create_to_peer_maps_transport_failure_to_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transport failures are distinct from peer response timeouts."""
    _local_computer, remote_computer, request, client = _make_failure_case(_RemoteSessionCreateTransportClient)
    monkeypatch.setattr("teleclaude.api.session_create_launch.assert_agent_enabled", lambda agent: agent)

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_session_create_to_peer(
            _make_client(client),
            remote_computer,
            request,
            identity_metadata=MessageMetadata(origin="web", human_role="admin"),
        )

    assert exc_info.value.status_code == 503


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_session_create_to_peer_rejects_invalid_remote_tmux_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsafe peer transport fields fail at the gateway boundary."""
    _local_computer, remote_computer, request, client = _make_failure_case(_RemoteSessionCreateClient)
    client.tmux_session_name = "tc_remote;bad"
    monkeypatch.setattr("teleclaude.api.session_create_launch.assert_agent_enabled", lambda agent: agent)

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_session_create_to_peer(
            _make_client(client),
            remote_computer,
            request,
            identity_metadata=MessageMetadata(origin="web", human_role="admin"),
        )

    assert exc_info.value.status_code == 502
