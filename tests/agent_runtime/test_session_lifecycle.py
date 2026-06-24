"""Functional tests for session identity and human_role behavior.

These tests act as an agent would: create sessions via the real API,
receive tokens, and use those tokens to call further API endpoints.
The full auth stack runs — verify_caller, role clearance, token issuance.
No fallback to admin should exist for sessions without explicit identity.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypedDict
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

import teleclaude.core.agent_coordinator._coordinator as coordinator_mod
from teleclaude.api import auth as auth_mod
from teleclaude.api import sessions_actions_routes, sessions_routes
from teleclaude.api.session_ownership import LocalOwnership, RemoteOwnership, resolve_session_ownership
from teleclaude.api.session_remote import dispatch_session_close_to_peer, dispatch_session_keys_to_peer
from teleclaude.cli import api_client as api_client_mod
from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.constants import EVENT_END_SESSION, ROLE_ORCHESTRATOR, ROLE_WORKER, WORKTREE_DIR, JobRole, SlashCommand
from teleclaude.core.adapter_client._remote import RemoteDispatchError, _RemoteMixin
from teleclaude.core.agent_coordinator import AgentCoordinator
from teleclaude.core.command_handlers import _session as session_handler_mod
from teleclaude.core.events import AgentEventContext, AgentHookEvents, build_agent_payload
from teleclaude.core.identity import IdentityContext
from teleclaude.core.models import MessageMetadata, SessionSnapshot
from teleclaude.core.models._session import Session
from teleclaude.core.next_machine.runtime.sessions import find_live_session_for_slug, live_slug_holder
from teleclaude.core.next_machine.session_hold import clear_active_runner_for_session_end
from teleclaude.core.operation_caller_identity import reset_caller_session_id, set_caller_session_id
from teleclaude.core.origins import InputOrigin
from teleclaude.core.todos_db import get_todos_db
from teleclaude.project_root import resolve_state_root
from teleclaude.types.commands import CloseSessionCommand
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.todos import TodoState

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SPEC = "project/spec/feature/agent_runtime/session-lifecycle"


class _RemoteDispatchRecord(TypedDict):
    computer: str
    command: str
    session_id: str | None


class _RemoteReadRecord(TypedDict):
    message_id: str
    target_computer: str | None
    timeout: float


class _RemoteCloseDispatchRecord(TypedDict):
    target_computer: str
    command: str
    origin: str | None
    session_id: str | None
    timeout: float
    wait_for_response: bool


class _RemoteDispatchHarness(_RemoteMixin):
    """Small transport harness for command-stream remote dispatch behavior."""

    def __init__(
        self,
        response_text: str | None = None,
        *,
        read_error: BaseException | None = None,
    ) -> None:
        self.response_text = response_text
        self.read_error = read_error
        self.sent: list[_RemoteDispatchRecord] = []
        self.reads: list[_RemoteReadRecord] = []

    async def send_request(
        self,
        computer_name: str,
        command: str,
        metadata: MessageMetadata,
        session_id: str | None = None,
    ) -> str:
        del metadata
        self.sent.append(
            {
                "computer": computer_name,
                "command": command,
                "session_id": session_id,
            }
        )
        return "message-1"

    async def read_response(
        self,
        message_id: str,
        timeout: float = 3.0,
        target_computer: str | None = None,
    ) -> str:
        self.reads.append(
            {
                "message_id": message_id,
                "target_computer": target_computer,
                "timeout": timeout,
            }
        )
        if self.read_error is not None:
            raise self.read_error
        if self.response_text is None:
            raise AssertionError("response_text is required when read_response is reached")
        return self.response_text


class _RemoteCloseClient:
    def __init__(self, dispatch_error: BaseException | None = None) -> None:
        self.dispatch_error = dispatch_error
        self.dispatches: list[_RemoteCloseDispatchRecord] = []

    async def dispatch_remote_command(
        self,
        target_computer: str,
        command: str,
        metadata: MessageMetadata,
        *,
        session_id: str | None = None,
        timeout: float = 3.0,
        wait_for_response: bool = True,
    ) -> object:
        self.dispatches.append(
            {
                "target_computer": target_computer,
                "command": command,
                "origin": metadata.origin,
                "session_id": session_id,
                "timeout": timeout,
                "wait_for_response": wait_for_response,
            }
        )
        if self.dispatch_error is not None:
            raise self.dispatch_error
        return None


class _OwnershipDb:
    def __init__(self, session: Session | None) -> None:
        self.session = session

    async def get_session(self, session_id: str) -> Session | None:
        if self.session is None or self.session.session_id != session_id:
            return None
        return self.session


class _OwnershipCache:
    def __init__(self, sessions: list[SessionSnapshot]) -> None:
        self.sessions = sessions

    def get_sessions(self, computer: str | None = None) -> list[SessionSnapshot]:
        if computer is None:
            return self.sessions
        return [session for session in self.sessions if session.computer == computer]


def _snapshot(
    session_id: str,
    *,
    computer: str = "PeerComputer",
    human_email: str | None = None,
    human_role: str | None = None,
) -> SessionSnapshot:
    return SessionSnapshot(
        session_id=session_id,
        last_input_origin="terminal",
        title="remote session",
        thinking_mode="slow",
        active_agent="claude",
        status="active",
        computer=computer,
        human_email=human_email,
        human_role=human_role,
    )


def _install_member_identity_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    class _MemberIdentityResolver:
        registered_people_count = 1
        is_multi_user = False

        @staticmethod
        def resolve_by_email(email: str) -> IdentityContext:
            return IdentityContext(
                person_name="Member",
                person_email=email.strip().lower(),
                person_role="member",
            )

    monkeypatch.setattr(auth_mod, "get_identity_resolver", lambda: _MemberIdentityResolver())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_session(
    api: AsyncClient,
    *,
    human_role: str | None = None,
    human_email: str | None = None,
    metadata: dict | None = None,
    project_path: str | None = None,
) -> dict:
    """POST /sessions and return the response JSON."""
    payload: dict = {
        "computer": "TestComputer",
        "project_path": project_path or "/tmp",
        "agent": "claude",
        "thinking_mode": "fast",
        "title": "functional-test",
        "launch_kind": "empty",
    }
    if human_role is not None:
        payload["human_role"] = human_role
    if human_email is not None:
        payload["human_email"] = human_email
    if metadata is not None:
        payload["metadata"] = metadata
    resp = await api.post("/sessions", json=payload)
    assert resp.status_code == 200, f"session creation failed: {resp.text}"
    return resp.json()


async def _get_session_from_db(api: AsyncClient, session_id: str) -> Any:
    """Load session directly from DB (attached to the client by conftest)."""
    return await api.db.get_session(session_id)


# ---------------------------------------------------------------------------
# Remote dispatch primitive
# ---------------------------------------------------------------------------


async def test_remote_dispatch_returns_success_envelope_data() -> None:
    envelope = json.dumps({"status": "success", "data": {"accepted": True}})
    client = _RemoteDispatchHarness(envelope)

    data = await client.dispatch_remote_command(
        "PeerComputer",
        EVENT_END_SESSION,
        MessageMetadata(origin=InputOrigin.TERMINAL.value),
        session_id="session-1",
        timeout=12.0,
    )

    assert data == {"accepted": True}
    assert client.sent == [
        {
            "computer": "PeerComputer",
            "command": EVENT_END_SESSION,
            "session_id": "session-1",
        }
    ]
    assert client.reads == [
        {
            "message_id": "message-1",
            "target_computer": "PeerComputer",
            "timeout": 12.0,
        }
    ]


async def test_remote_dispatch_error_envelope_raises_domain_error() -> None:
    envelope = json.dumps({"status": "error", "error": "peer rejected close"})
    client = _RemoteDispatchHarness(envelope)

    with pytest.raises(RemoteDispatchError):
        await client.dispatch_remote_command(
            "PeerComputer",
            EVENT_END_SESSION,
            MessageMetadata(origin=InputOrigin.TERMINAL.value),
            session_id="session-1",
        )


async def test_remote_dispatch_timeout_propagates() -> None:
    client = _RemoteDispatchHarness(read_error=TimeoutError())

    with pytest.raises(TimeoutError):
        await client.dispatch_remote_command(
            "PeerComputer",
            EVENT_END_SESSION,
            MessageMetadata(origin=InputOrigin.TERMINAL.value),
            session_id="session-1",
        )


async def test_remote_dispatch_fire_and_forget_sends_command_without_reading_response() -> None:
    client = _RemoteDispatchHarness()

    data = await client.dispatch_remote_command(
        "PeerComputer",
        EVENT_END_SESSION,
        MessageMetadata(origin=InputOrigin.TERMINAL.value),
        session_id="session-1",
        wait_for_response=False,
    )

    assert data is None
    assert client.sent == [
        {
            "computer": "PeerComputer",
            "command": EVENT_END_SESSION,
            "session_id": "session-1",
        }
    ]
    assert client.reads == []


# ---------------------------------------------------------------------------
# Session ownership resolver
# ---------------------------------------------------------------------------


async def test_session_ownership_resolver_prefers_local_database() -> None:
    local = Session(
        session_id="session-1",
        computer_name="TestComputer",
        tmux_session_name="tc-session-1",
        title="local session",
    )

    ownership = await resolve_session_ownership(
        "session-1",
        db=_OwnershipDb(local),
        cache=_OwnershipCache([_snapshot("session-1")]),
    )

    assert isinstance(ownership, LocalOwnership)
    assert ownership.session is local


async def test_session_ownership_resolver_returns_cached_remote_owner() -> None:
    peer = "PeerComputer"
    snapshot = _snapshot("session-1", computer=peer)

    ownership = await resolve_session_ownership(
        "session-1",
        db=_OwnershipDb(None),
        cache=_OwnershipCache([snapshot]),
    )

    assert isinstance(ownership, RemoteOwnership)
    assert ownership.computer == peer
    assert ownership.snapshot is snapshot


async def test_session_ownership_resolver_returns_none_for_unknown_session() -> None:
    ownership = await resolve_session_ownership(
        "missing-session",
        db=_OwnershipDb(None),
        cache=_OwnershipCache([_snapshot("session-1")]),
    )

    assert ownership is None


# ---------------------------------------------------------------------------
# Remote close command handler
# ---------------------------------------------------------------------------


async def test_close_session_for_peer_owned_row_dispatches_command_typed_remote_close(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del api
    client = _RemoteCloseClient()
    session = Session(
        session_id="session-1",
        computer_name="PeerComputer",
        tmux_session_name="tc-session-1",
        title="remote session",
    )
    monkeypatch.setattr(session_handler_mod.tmux_bridge, "session_exists", AsyncMock(return_value=False))

    await session_handler_mod.close_session.__wrapped__(
        session,
        CloseSessionCommand(session_id="session-1"),
        client,
    )

    assert client.dispatches == [
        {
            "target_computer": "PeerComputer",
            "command": EVENT_END_SESSION,
            "origin": InputOrigin.TERMINAL.value,
            "session_id": "session-1",
            "timeout": 3.0,
            "wait_for_response": False,
        }
    ]


async def test_close_session_for_locally_present_row_does_not_dispatch_remote_close(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del api
    client = _RemoteCloseClient()
    session = Session(
        session_id="session-1",
        computer_name="PeerComputer",
        tmux_session_name="tc-session-1",
        title="local session",
    )
    terminate = AsyncMock(return_value=True)
    monkeypatch.setattr(session_handler_mod.tmux_bridge, "session_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(session_handler_mod, "terminate_session", terminate)
    monkeypatch.setattr(session_handler_mod.event_bus, "emit", lambda *args, **kwargs: None)

    await session_handler_mod.close_session.__wrapped__(
        session,
        CloseSessionCommand(session_id="session-1"),
        client,
    )

    assert client.dispatches == []
    terminate.assert_awaited_once()


# ---------------------------------------------------------------------------
# Remote close API helper
# ---------------------------------------------------------------------------


async def test_dispatch_session_close_to_peer_uses_request_response_primitive() -> None:
    client = _RemoteCloseClient()

    await dispatch_session_close_to_peer(client, "PeerComputer", "session-1")

    assert client.dispatches == [
        {
            "target_computer": "PeerComputer",
            "command": EVENT_END_SESSION,
            "origin": "terminal",
            "session_id": "session-1",
            "timeout": 30.0,
            "wait_for_response": True,
        }
    ]


async def test_dispatch_session_close_to_peer_maps_target_error_to_bad_gateway() -> None:
    client = _RemoteCloseClient(RemoteDispatchError("peer rejected close"))

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_session_close_to_peer(client, "PeerComputer", "session-1")

    assert exc_info.value.status_code == 502


async def test_dispatch_session_close_to_peer_maps_transport_error_to_unavailable() -> None:
    client = _RemoteCloseClient(RuntimeError("redis unavailable"))

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_session_close_to_peer(client, "PeerComputer", "session-1")

    assert exc_info.value.status_code == 503


async def test_dispatch_session_close_to_peer_maps_timeout_to_gateway_timeout() -> None:
    client = _RemoteCloseClient(TimeoutError())

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_session_close_to_peer(client, "PeerComputer", "session-1")

    assert exc_info.value.status_code == 504


# ---------------------------------------------------------------------------
# Remote send-keys API helper
# ---------------------------------------------------------------------------


async def test_dispatch_session_keys_to_peer_forwards_key_command_string() -> None:
    client = _RemoteCloseClient()

    await dispatch_session_keys_to_peer(client, "PeerComputer", "session-1", "enter", ["1"])

    assert client.dispatches == [
        {
            "target_computer": "PeerComputer",
            "command": "enter 1",
            "origin": InputOrigin.TERMINAL.value,
            "session_id": "session-1",
            "timeout": 10.0,
            "wait_for_response": True,
        }
    ]


async def test_dispatch_session_keys_to_peer_maps_target_error_to_bad_gateway() -> None:
    client = _RemoteCloseClient(RemoteDispatchError("peer rejected keys"))

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_session_keys_to_peer(client, "PeerComputer", "session-1", "enter", ["1"])

    assert exc_info.value.status_code == 502


async def test_dispatch_session_keys_to_peer_maps_transport_error_to_unavailable() -> None:
    client = _RemoteCloseClient(RuntimeError("redis unavailable"))

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_session_keys_to_peer(client, "PeerComputer", "session-1", "enter", ["1"])

    assert exc_info.value.status_code == 503


async def test_dispatch_session_keys_to_peer_maps_timeout_to_gateway_timeout() -> None:
    client = _RemoteCloseClient(TimeoutError())

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_session_keys_to_peer(client, "PeerComputer", "session-1", "enter", ["1"])

    assert exc_info.value.status_code == 504


async def test_dispatch_session_keys_to_peer_rejects_non_key_command_before_dispatch() -> None:
    """A key outside the key-command vocabulary is rejected before forming the peer command.

    Guards against forwarding an arbitrary command name (e.g. ``end_session``) that the
    peer mapper would resolve into a privileged command the keys clearance never granted.
    """
    client = _RemoteCloseClient()

    with pytest.raises(HTTPException) as exc_info:
        await dispatch_session_keys_to_peer(client, "PeerComputer", "session-1", "end_session", [])

    assert exc_info.value.status_code == 400
    assert client.dispatches == []


# ---------------------------------------------------------------------------
# Remote send-keys API boundary
# ---------------------------------------------------------------------------


async def test_send_keys_for_peer_targeted_session_dispatches_remote_and_does_not_run_locally(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adopting a peer-owned headless session forwards the key to the owning peer.

    Regression for the reported 500 ("Session ... not found - this should not happen"):
    the endpoint must dispatch to the owning peer instead of resolving the key against
    the local DB, which never holds a peer-owned session row.
    """
    client = _RemoteCloseClient()
    local_keys = AsyncMock()
    monkeypatch.setattr(sessions_actions_routes._STATE, "client", client)
    monkeypatch.setattr(sessions_actions_routes, "get_command_service", lambda: SimpleNamespace(keys=local_keys))

    response = await api.post(
        "/sessions/remote-session/keys",
        params={"computer": "PeerComputer"},
        json={"key": "enter", "count": 1},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    local_keys.assert_not_awaited()
    assert client.dispatches == [
        {
            "target_computer": "PeerComputer",
            "command": "enter 1",
            "origin": InputOrigin.TERMINAL.value,
            "session_id": "remote-session",
            "timeout": 10.0,
            "wait_for_response": True,
        }
    ]


async def test_send_keys_for_local_target_runs_locally_and_does_not_dispatch_remote(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A send-keys request with no remote target executes against the local session store."""
    client = _RemoteCloseClient()
    local_keys = AsyncMock()
    monkeypatch.setattr(sessions_actions_routes._STATE, "client", client)
    monkeypatch.setattr(sessions_actions_routes, "get_command_service", lambda: SimpleNamespace(keys=local_keys))

    response = await api.post(
        "/sessions/local-session/keys",
        json={"key": "enter", "count": 1},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    local_keys.assert_awaited_once()
    assert client.dispatches == []


async def test_send_keys_for_peer_rejects_non_key_command_without_dispatch(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A peer-targeted request whose key is not a key command is rejected before peer dispatch.

    Regression guard: the keys route is cleared for send-keys, not session close, so it must
    not forward ``end_session`` (which the peer mapper resolves to CloseSessionCommand).
    """
    client = _RemoteCloseClient()
    local_keys = AsyncMock()
    monkeypatch.setattr(sessions_actions_routes._STATE, "client", client)
    monkeypatch.setattr(sessions_actions_routes, "get_command_service", lambda: SimpleNamespace(keys=local_keys))

    response = await api.post(
        "/sessions/remote-session/keys",
        params={"computer": "PeerComputer"},
        json={"key": "end_session"},
    )

    assert response.status_code == 400
    local_keys.assert_not_awaited()
    assert client.dispatches == []


# ---------------------------------------------------------------------------
# Remote close API boundary
# ---------------------------------------------------------------------------


async def test_delete_remote_session_forwards_to_cached_owner_and_returns_completion_event(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RemoteCloseClient()
    cache = _OwnershipCache(
        [
            _snapshot(
                "remote-session",
                computer="PeerComputer",
                human_email="owner@example.com",
                human_role="member",
            )
        ]
    )
    _install_member_identity_resolver(monkeypatch)
    monkeypatch.setattr(sessions_routes._STATE, "client", client)
    monkeypatch.setattr(sessions_routes._STATE, "cache", cache)

    response = await api.delete(
        "/sessions/remote-session",
        params={"computer": "PeerComputer"},
        headers={
            "x-web-user-email": "owner@example.com",
            "x-web-user-role": "member",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["completion_event"] == CloseSessionCommand(session_id="remote-session").completion_event
    assert body["message"]
    assert client.dispatches == [
        {
            "target_computer": "PeerComputer",
            "command": EVENT_END_SESSION,
            "origin": InputOrigin.TERMINAL.value,
            "session_id": "remote-session",
            "timeout": 30.0,
            "wait_for_response": True,
        }
    ]


async def test_delete_remote_session_rejects_non_owner_web_identity(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _OwnershipCache(
        [
            _snapshot(
                "remote-session",
                computer="PeerComputer",
                human_email="owner@example.com",
                human_role="member",
            )
        ]
    )
    _install_member_identity_resolver(monkeypatch)
    monkeypatch.setattr(sessions_routes._STATE, "client", _RemoteCloseClient())
    monkeypatch.setattr(sessions_routes._STATE, "cache", cache)

    response = await api.delete(
        "/sessions/remote-session",
        params={"computer": "PeerComputer"},
        headers={
            "x-web-user-email": "other@example.com",
            "x-web-user-role": "member",
        },
    )

    assert response.status_code == 403


async def test_delete_local_session_continues_when_manual_hold_interlock_fails(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = await _create_session(api)
    session_id = session["session_id"]
    hold = AsyncMock(side_effect=RuntimeError("hold failed"))
    close = AsyncMock()
    service = SimpleNamespace(close_session=close)
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", hold)
    monkeypatch.setattr(sessions_routes, "get_command_service", lambda: service)

    # No x-session-token / x-caller-session-id → human principal (empty
    # identity.session_id), so this manual close holds the driven todo (ADR-0036).
    response = await api.delete(f"/sessions/{session_id}")

    assert response.status_code == 202
    body = response.json()
    assert body["completion_event"] == CloseSessionCommand(session_id=session_id).completion_event
    hold.assert_awaited_once_with(api.db, session_id)
    close.assert_awaited_once_with(CloseSessionCommand(session_id=session_id))


async def test_delete_human_close_sets_hold(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0036: a human-initiated close (empty identity.session_id) holds the todo."""
    session = await _create_session(api)
    session_id = session["session_id"]
    hold = AsyncMock()
    close = AsyncMock()
    service = SimpleNamespace(close_session=close)
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", hold)
    monkeypatch.setattr(sessions_routes, "get_command_service", lambda: service)

    # No session token → human principal.
    response = await api.delete(f"/sessions/{session_id}")

    assert response.status_code == 202
    hold.assert_awaited_once_with(api.db, session_id)
    close.assert_awaited_once_with(CloseSessionCommand(session_id=session_id))


async def test_delete_self_close_by_agent_does_not_hold(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0036: an agent self-end (token-auth, non-empty identity.session_id) does not hold."""
    session = await _create_session(api)
    session_id = session["session_id"]
    token = await api.db.issue_session_token(session_id, f"system:{session_id}", "admin")
    hold = AsyncMock()
    close = AsyncMock()
    service = SimpleNamespace(close_session=close)
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", hold)
    monkeypatch.setattr(sessions_routes, "get_command_service", lambda: service)

    # Agent identity via session token → non-empty identity.session_id.
    response = await api.delete(
        f"/sessions/{session_id}",
        headers={"x-session-token": token},
    )

    assert response.status_code == 202
    hold.assert_not_awaited()
    close.assert_awaited_once_with(CloseSessionCommand(session_id=session_id))


_SELF_END_SPEC = "project/spec/feature/identity/self-end-authorization-bypass"


@pytest.mark.spec(_SELF_END_SPEC, "UC-SE1")
async def test_self_end_parentless_driver_accepted(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    cluster_event_bus: None,
) -> None:
    """A parentless worker driver may end its own session past the verb band."""
    session = await _create_session(api)
    session_id = session["session_id"]
    # working_slug derives system_role=worker; initiator_session_id stays None (driver).
    await api.db.update_session(session_id, working_slug="some-slug")
    token = await api.db.issue_session_token(session_id, f"system:{session_id}", ROLE_WORKER)
    close = AsyncMock()
    service = SimpleNamespace(close_session=close)
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", AsyncMock())
    monkeypatch.setattr(sessions_routes, "get_command_service", lambda: service)

    response = await api.delete(f"/sessions/{session_id}", headers={"x-session-token": token})

    assert response.status_code == 202
    close.assert_awaited_once_with(CloseSessionCommand(session_id=session_id))


@pytest.mark.spec(_SELF_END_SPEC, "UC-SE2")
async def test_self_end_sub_worker_rejected(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    cluster_event_bus: None,
) -> None:
    """A worker self-end with an orchestrating parent falls through to a 403."""
    session = await _create_session(api)
    session_id = session["session_id"]
    # initiator_session_id set → the session has an orchestrating parent (sub-worker).
    await api.db.update_session(session_id, working_slug="some-slug", initiator_session_id="parent-session")
    token = await api.db.issue_session_token(session_id, f"system:{session_id}", ROLE_WORKER)
    close = AsyncMock()
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", AsyncMock())
    monkeypatch.setattr(sessions_routes, "get_command_service", lambda: SimpleNamespace(close_session=close))

    response = await api.delete(f"/sessions/{session_id}", headers={"x-session-token": token})

    assert response.status_code == 403
    close.assert_not_awaited()


@pytest.mark.spec(_SELF_END_SPEC, "UC-SE3")
async def test_self_end_worker_ending_other_rejected(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    cluster_event_bus: None,
) -> None:
    """A worker ending a DIFFERENT session is rejected by the standard rule."""
    caller = await _create_session(api)
    caller_id = caller["session_id"]
    target = await _create_session(api)
    target_id = target["session_id"]
    await api.db.update_session(caller_id, working_slug="some-slug")
    token = await api.db.issue_session_token(caller_id, f"system:{caller_id}", ROLE_WORKER)
    close = AsyncMock()
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", AsyncMock())
    monkeypatch.setattr(sessions_routes, "get_command_service", lambda: SimpleNamespace(close_session=close))

    response = await api.delete(f"/sessions/{target_id}", headers={"x-session-token": token})

    assert response.status_code == 403
    close.assert_not_awaited()


@pytest.mark.spec(_SELF_END_SPEC, "UC-SE4")
async def test_self_end_integrator_ending_other_accepted(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    cluster_event_bus: None,
) -> None:
    """An in-band system role ending a DIFFERENT session passes the standard rule."""
    caller = await _create_session(api)
    caller_id = caller["session_id"]
    target = await _create_session(api)
    target_id = target["session_id"]
    await api.db.update_session(caller_id, system_role="integrator")
    token = await api.db.issue_session_token(caller_id, f"system:{caller_id}", "integrator")
    close = AsyncMock()
    service = SimpleNamespace(close_session=close)
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", AsyncMock())
    monkeypatch.setattr(sessions_routes, "get_command_service", lambda: service)

    response = await api.delete(f"/sessions/{target_id}", headers={"x-session-token": token})

    assert response.status_code == 202
    close.assert_awaited_once_with(CloseSessionCommand(session_id=target_id))


@pytest.mark.spec(_SELF_END_SPEC, "UC-SE5")
async def test_self_end_terminal_caller_uses_human_band(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal caller (empty session_id) is evaluated against the human band."""
    session = await _create_session(api)
    session_id = session["session_id"]
    close = AsyncMock()
    service = SimpleNamespace(close_session=close)
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", AsyncMock())
    monkeypatch.setattr(sessions_routes, "get_command_service", lambda: service)

    # No session token → single-user terminal admin via the human band.
    response = await api.delete(f"/sessions/{session_id}")

    assert response.status_code == 202
    close.assert_awaited_once_with(CloseSessionCommand(session_id=session_id))


@pytest.mark.spec(_SELF_END_SPEC, "UC-SE5")
async def test_self_end_terminal_caller_outside_band_rejected(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal caller whose role is outside the end human band is rejected."""
    session = await _create_session(api)
    session_id = session["session_id"]

    class _ContributorIdentityResolver:
        registered_people_count = 1
        is_multi_user = False

        @staticmethod
        def resolve_by_email(email: str) -> IdentityContext:
            return IdentityContext(
                person_name="Contributor",
                person_email=email.strip().lower(),
                person_role="contributor",
            )

    monkeypatch.setattr(auth_mod, "get_identity_resolver", lambda: _ContributorIdentityResolver())
    close = AsyncMock()
    monkeypatch.setattr(sessions_routes, "hold_todo_for_manual_session_close", AsyncMock())
    monkeypatch.setattr(sessions_routes, "get_command_service", lambda: SimpleNamespace(close_session=close))

    # Terminal caller (no token → empty session_id) resolving to contributor,
    # which is outside the `telec sessions end` human band {admin, member}.
    response = await api.delete(f"/sessions/{session_id}", headers={"x-web-user-email": "contrib@example.com"})

    assert response.status_code == 403
    close.assert_not_awaited()


async def test_delete_remote_session_rejects_requested_computer_mismatch(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _OwnershipCache(
        [
            _snapshot(
                "remote-session",
                computer="PeerComputer",
                human_email="owner@example.com",
                human_role="member",
            )
        ]
    )
    _install_member_identity_resolver(monkeypatch)
    monkeypatch.setattr(sessions_routes._STATE, "client", _RemoteCloseClient())
    monkeypatch.setattr(sessions_routes._STATE, "cache", cache)

    response = await api.delete(
        "/sessions/remote-session",
        params={"computer": "OtherComputer"},
        headers={
            "x-web-user-email": "owner@example.com",
            "x-web-user-role": "member",
        },
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 1. Single-user terminal caller → admin role on session record
# ---------------------------------------------------------------------------


@pytest.mark.spec(_SPEC, "UC-SL20")
async def test_single_user_session_gets_admin_from_auth(api: AsyncClient, snapshot) -> None:
    """In single-user mode, a terminal caller gets admin from the auth layer.

    The session record must have human_role='admin' — not because of a model
    default, but because verify_caller resolved the single-user identity.
    """
    data = await _create_session(api)
    session = await _get_session_from_db(api, data["session_id"])
    assert session is not None
    assert {"human_role": session.human_role} == snapshot


# ---------------------------------------------------------------------------
# 2. Explicit human_role in request is preserved
# ---------------------------------------------------------------------------


async def test_explicit_member_role_preserved(api: AsyncClient, snapshot) -> None:
    """When the request carries human_role='member', the session record
    must reflect that — not silently upgrade to admin.
    """
    data = await _create_session(api, human_role="member")
    session = await _get_session_from_db(api, data["session_id"])
    assert {"human_role": session.human_role} == snapshot


# ---------------------------------------------------------------------------
# 3. System session (with metadata.system_role) gets no human_role fallback
# ---------------------------------------------------------------------------


async def test_system_session_has_no_human_role_fallback(api: AsyncClient, snapshot) -> None:
    """A system session created with system_role metadata should not get
    human_role='admin' from a fallback. human_role comes from the auth
    layer (single-user → admin in this test), not from a model default.
    """
    data = await _create_session(
        api,
        metadata={"system_role": "system"},
    )
    session = await _get_session_from_db(api, data["session_id"])
    # human_role is set by auth (single-user → admin), not by a fallback.
    assert {"system_role": session.system_role, "human_role": session.human_role} == snapshot


# ---------------------------------------------------------------------------
# 4. Child session inherits parent's human_role
# ---------------------------------------------------------------------------


@pytest.mark.spec(_SPEC, "UC-SL2")
async def test_child_inherits_parent_human_role(api: AsyncClient, snapshot) -> None:
    """When an agent session spawns a child via POST /sessions with
    x-caller-session-id, the child should inherit the parent's human_role.
    """
    parent_data = await _create_session(api, human_role="member")
    parent_id = parent_data["session_id"]
    parent_tmux = parent_data["tmux_session_name"]

    # Child creation: agent calls from within parent session context.
    child_resp = await api.post(
        "/sessions",
        json={
            "computer": "TestComputer",
            "project_path": "/tmp",
            "agent": "claude",
            "thinking_mode": "fast",
            "title": "child-session",
            "launch_kind": "empty",
        },
        headers={
            "x-caller-session-id": parent_id,
            "x-tmux-session": parent_tmux,
        },
    )
    assert child_resp.status_code == 200, f"child creation failed: {child_resp.text}"
    child = await _get_session_from_db(api, child_resp.json()["session_id"])
    assert {"human_role": child.human_role} == snapshot
    assert child.initiator_session_id == parent_id


# ---------------------------------------------------------------------------
# 4b. Daemon-hosted operation caller authenticates without a foreign tmux factor
# ---------------------------------------------------------------------------


async def test_operation_caller_authorizes_without_ambient_tmux(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A daemon-hosted lifecycle operation builds caller identity headers from the
    contextvar override while holding no tmux pane. Honoring the caller-verification
    contract's pane-less caveat (``docs/project/spec/feature/identity/caller-verification.md``
    Known caveats: identity-context-spawned tasks without a tmux pane authenticate by
    sending no tmux signal), the client must omit ``x-tmux-session`` rather than attach
    the daemon's foreign ambient tmux session — which would 403 the caller as a session
    identity mismatch. Drives the real header-building path into the real auth boundary
    and asserts the authorization outcome (not the header dict).
    """
    caller = await _create_session(api, human_role="member")
    caller_id = caller["session_id"]

    # The daemon process has no tmux pane, so the ambient read resolves to a foreign
    # session; the operation runner installs only the caller session id via the override.
    monkeypatch.setattr(TelecAPIClient, "_read_tmux_session_name", lambda self: "tc_foreign-daemon")
    monkeypatch.setattr(api_client_mod, "get_session_token", lambda: None)
    monkeypatch.setattr(api_client_mod, "read_current_session_email", lambda: None)

    token = set_caller_session_id(caller_id)
    try:
        headers = TelecAPIClient()._build_identity_headers()
    finally:
        reset_caller_session_id(token)

    resp = await api.post(
        "/sessions",
        json={
            "computer": "TestComputer",
            "project_path": "/tmp",
            "agent": "claude",
            "thinking_mode": "fast",
            "title": "operation-dispatch",
            "launch_kind": "empty",
        },
        headers=headers,
    )

    assert resp.status_code == 200, f"operation caller rejected: {resp.status_code} {resp.text}"
    child = await _get_session_from_db(api, resp.json()["session_id"])
    assert child.initiator_session_id == caller_id


# ---------------------------------------------------------------------------
# 5. Token-authenticated session can call API endpoints
# ---------------------------------------------------------------------------


async def test_token_auth_allows_session_list(api: AsyncClient) -> None:
    """An agent session with a valid token can call GET /sessions.

    The token must authenticate successfully and the endpoint must return 200.
    Sessions in 'initializing' status are excluded from list by default, so we
    verify auth works (200) rather than checking session membership.
    """
    data = await _create_session(api)
    session_id = data["session_id"]

    # Issue a token (simulating what the daemon does at session bootstrap).
    token = await api.db.issue_session_token(session_id, f"system:{session_id}", "admin")

    resp = await api.get(
        "/sessions",
        params={"all": "true"},
        headers={"x-session-token": token},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# 6. Token for a session with human_role=None still works
# ---------------------------------------------------------------------------


async def test_token_auth_with_null_human_role(api: AsyncClient, cluster_event_bus: None) -> None:
    """A system-spawned session may have human_role=None in the DB.
    Token auth should still work — principal_role from the token record
    is used for clearance when human_role is absent.
    """
    # Create session, then manually clear human_role to simulate a system session.
    data = await _create_session(api)
    session_id = data["session_id"]
    await api.db.update_session(session_id, human_role=None)

    token = await api.db.issue_session_token(session_id, f"system:{session_id}", "admin")

    resp = await api.get(
        "/sessions",
        headers={"x-session-token": token},
    )
    assert resp.status_code == 200


@pytest.mark.spec(_SPEC, "UC-SL22")
async def test_closed_session_snapshots_report_idle_agent_status(snapshot) -> None:
    now = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)

    def session_snapshot(
        session_id: str,
        *,
        lifecycle_status: str,
        closed_at: datetime | None,
        last_input_at: datetime | None,
        last_agent_stop_at: datetime | None,
    ) -> dict[str, str | None]:
        session = Session(
            session_id=session_id,
            computer_name="TestComputer",
            tmux_session_name=session_id,
            title=session_id,
            active_agent="claude",
            lifecycle_status=lifecycle_status,
            closed_at=closed_at,
            last_activity=now,
            last_message_sent_at=last_input_at,
            last_agent_stop_at=last_agent_stop_at,
        )
        projected = SessionSnapshot.from_db_session(session)
        return {
            "status": projected.status,
            "closed_at": projected.closed_at,
            "last_agent_stop_at": projected.last_agent_stop_at,
            "agent_status": projected.agent_status,
        }

    projections = {
        "closed_status_without_stop": session_snapshot(
            "closed-status",
            lifecycle_status="closed",
            closed_at=None,
            last_input_at=now - timedelta(minutes=10),
            last_agent_stop_at=None,
        ),
        "closing_status_without_stop": session_snapshot(
            "closing-status",
            lifecycle_status="closing",
            closed_at=None,
            last_input_at=now - timedelta(minutes=10),
            last_agent_stop_at=None,
        ),
        "closed_at_marker_without_stop": session_snapshot(
            "closed-at-marker",
            lifecycle_status="active",
            closed_at=now - timedelta(minutes=1),
            last_input_at=now - timedelta(minutes=10),
            last_agent_stop_at=None,
        ),
        "active_without_stop": session_snapshot(
            "active-status",
            lifecycle_status="active",
            closed_at=None,
            last_input_at=now - timedelta(minutes=10),
            last_agent_stop_at=None,
        ),
        "stopped_without_later_input": session_snapshot(
            "stopped-status",
            lifecycle_status="active",
            closed_at=None,
            last_input_at=now - timedelta(minutes=10),
            last_agent_stop_at=now - timedelta(minutes=5),
        ),
        "input_after_stop": session_snapshot(
            "input-after-stop",
            lifecycle_status="active",
            closed_at=None,
            last_input_at=now - timedelta(minutes=2),
            last_agent_stop_at=now - timedelta(minutes=5),
        ),
    }

    assert projections == snapshot


@pytest.mark.spec(_SPEC, "UC-SL23")
@pytest.mark.parametrize(
    ("event_type", "payload_data"),
    [
        (
            AgentHookEvents.AGENT_SESSION_START,
            {
                "session_id": "native-reviewer",
                "transcript_path": "/tmp/reviewer-transcript.jsonl",
            },
        ),
        (AgentHookEvents.AGENT_STOP, {"prompt": "review complete"}),
        (AgentHookEvents.TOOL_USE, {"tool_name": "Read"}),
        (AgentHookEvents.USER_PROMPT_SUBMIT, {"prompt": "please continue"}),
    ],
)
async def test_activity_hook_activates_initializing_session_for_live_lookup(
    api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    cluster_event_bus: None,
    event_type: str,
    payload_data: dict[str, str],
) -> None:
    del cluster_event_bus
    slug = "reviewer-not-alive-regression"
    subdir = f"{WORKTREE_DIR}/{slug}"
    title = "/next-review-build reviewer-not-alive-regression"

    monkeypatch.setattr(coordinator_mod, "db", api.db)
    monkeypatch.setattr(coordinator_mod, "schedule_slow_work", lambda **_kwargs: None)
    monkeypatch.setattr(
        coordinator_mod.polling_coordinator,
        "schedule_session_projection",
        AsyncMock(return_value=None),
    )

    coordinator = AgentCoordinator(
        client=AsyncMock(),
        tts_manager=AsyncMock(),
    )
    monkeypatch.setattr(coordinator, "_extract_agent_output", AsyncMock(return_value=None))
    monkeypatch.setattr(coordinator, "_notify_session_listener", AsyncMock(return_value=None))
    monkeypatch.setattr(coordinator, "_forward_stop_to_initiator", AsyncMock(return_value=None))
    monkeypatch.setattr(coordinator, "_signal_projection_activity", AsyncMock(return_value=None))

    target = await api.db.create_session(
        computer_name="TestComputer",
        tmux_session_name="tc-target",
        last_input_origin=InputOrigin.TERMINAL.value,
        title=title,
        subdir=subdir,
        lifecycle_status="initializing",
        active_agent="claude",
        emit_session_started=False,
    )
    protected_statuses = {
        "headless": await api.db.create_session(
            computer_name="TestComputer",
            tmux_session_name="tc-headless",
            last_input_origin=InputOrigin.TERMINAL.value,
            title=title,
            subdir=subdir,
            lifecycle_status="headless",
            active_agent="claude",
            emit_session_started=False,
        ),
        "closing": await api.db.create_session(
            computer_name="TestComputer",
            tmux_session_name="tc-closing",
            last_input_origin=InputOrigin.TERMINAL.value,
            title=title,
            subdir=subdir,
            lifecycle_status="closing",
            active_agent="claude",
            emit_session_started=False,
        ),
        "closed": await api.db.create_session(
            computer_name="TestComputer",
            tmux_session_name="tc-closed",
            last_input_origin=InputOrigin.TERMINAL.value,
            title=title,
            subdir=subdir,
            lifecycle_status="closed",
            active_agent="claude",
            emit_session_started=False,
        ),
    }

    assert await find_live_session_for_slug(api.db, slug, "/next-review-build") is None

    for session in [target, *protected_statuses.values()]:
        await coordinator.handle_event(
            AgentEventContext(
                session_id=session.session_id,
                event_type=event_type,
                data=build_agent_payload(event_type, payload_data),
            )
        )

    repaired = await api.db.get_session(target.session_id)
    assert repaired is not None
    expected_native_fields = {}
    if event_type == AgentHookEvents.AGENT_SESSION_START:
        expected_native_fields = {
            "native_session_id": "native-reviewer",
            "native_log_file": "/tmp/reviewer-transcript.jsonl",
        }
    assert {
        "lifecycle_status": repaired.lifecycle_status,
        "native_session_id": repaired.native_session_id,
        "native_log_file": repaired.native_log_file,
    } == {
        "lifecycle_status": "active",
        "native_session_id": expected_native_fields.get("native_session_id"),
        "native_log_file": expected_native_fields.get("native_log_file"),
    }
    assert await find_live_session_for_slug(api.db, slug, "/next-review-build") == target.session_id

    for expected_status, session in protected_statuses.items():
        current = await api.db.get_session(session.session_id)
        assert current is not None
        assert current.lifecycle_status == expected_status


# ---------------------------------------------------------------------------
# 7. Session without identity or token is rejected
# ---------------------------------------------------------------------------


async def test_no_identity_no_token_rejected_in_multiuser(api: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """In multi-user mode, a caller with no headers at all gets 401."""
    monkeypatch.setattr(auth_mod, "_requires_terminal_login", lambda: True)

    resp = await api.get("/sessions")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 8. Session model default is None, not admin
# ---------------------------------------------------------------------------


async def test_session_model_default_is_none() -> None:
    """The Session dataclass must default human_role to None.
    This is the foundational invariant — no silent admin escalation.
    """
    session = Session(
        session_id="test",
        computer_name="test",
        tmux_session_name="test",
        title="test",
    )
    assert session.human_role is None


# ---------------------------------------------------------------------------
# 9. from_dict deserialization preserves None
# ---------------------------------------------------------------------------


async def test_from_dict_preserves_null_human_role() -> None:
    """Session.from_dict must not coerce missing human_role to admin."""
    session = Session.from_dict(
        {
            "session_id": "test",
            "computer_name": "test",
            "tmux_session_name": "test",
            "title": "test",
        }
    )
    assert session.human_role is None


# ---------------------------------------------------------------------------
# 10. Restricted role gets jailed to help-desk
# ---------------------------------------------------------------------------


@pytest.mark.spec(_SPEC, "UC-SL21")
async def test_restricted_role_jailed_to_help_desk(api: AsyncClient, tmp_path: Path, snapshot) -> None:
    """A session with human_role='newcomer' (non-admin, no system_role)
    should be jailed to the help-desk directory.
    """
    help_desk = tmp_path / "help-desk"
    help_desk.mkdir(parents=True, exist_ok=True)

    data = await _create_session(api, human_role="newcomer")
    session = await _get_session_from_db(api, data["session_id"])
    assert session.project_path is not None
    assert {"jailed_dir": Path(session.project_path).name} == snapshot


# ---------------------------------------------------------------------------
# 11. Worker-class commands dispatched via sessions/run are contained
# ---------------------------------------------------------------------------


async def _dispatch_run_session(
    api: AsyncClient,
    *,
    command: str,
    args: str,
    headers: dict[str, str] | None = None,
) -> Any:
    """POST /sessions/run and return the raw response."""
    return await api.post(
        "/sessions/run",
        json={
            "computer": "TestComputer",
            "command": command,
            "args": args,
            "project": "/tmp",
            "agent": "claude",
            "thinking_mode": "fast",
        },
        headers=headers or {},
    )


@pytest.mark.parametrize(
    ("command", "args", "expected_job", "expected_working_slug"),
    [
        (SlashCommand.NEXT_REVIEW_COMMITS, "abc123def4567890", JobRole.REVIEWER, None),
        (SlashCommand.NEXT_BUGS_FIX, "bug-slug", JobRole.FIXER, "bug-slug"),
        (SlashCommand.NEXT_CREATE_ART, "art-mood-board", JobRole.ARTIST, "art-mood-board"),
        (SlashCommand.NEXT_CREATE_HTML, "html-artifact", JobRole.FRONTENDER, "html-artifact"),
    ],
)
async def test_worker_class_dispatch_is_tagged_and_contained(
    api: AsyncClient,
    command: SlashCommand,
    args: str,
    expected_job: JobRole,
    expected_working_slug: str | None,
) -> None:
    """Worker-class command sessions are tagged as workers and cannot dispatch."""
    dispatch_resp = await _dispatch_run_session(api, command=f"/{command.value}", args=args)
    assert dispatch_resp.status_code == 200, f"dispatch failed: {dispatch_resp.text}"
    worker_session_id = dispatch_resp.json()["session_id"]

    worker = await _get_session_from_db(api, worker_session_id)
    assert worker is not None
    assert {
        "system_role": worker.system_role,
        "job": worker.job,
        "working_slug": worker.working_slug,
    } == {
        "system_role": ROLE_WORKER,
        "job": expected_job.value,
        "working_slug": expected_working_slug,
    }

    token = await api.db.issue_session_token(worker_session_id, f"system:{worker_session_id}", "admin")
    worker_headers = {"x-session-token": token}

    run_resp = await _dispatch_run_session(
        api,
        command=f"/{SlashCommand.NEXT_BUILD.value}",
        args="some-slug",
        headers=worker_headers,
    )
    assert run_resp.status_code == 403

    start_resp = await api.post(
        "/sessions",
        json={
            "computer": "TestComputer",
            "project_path": "/tmp",
            "agent": "claude",
            "thinking_mode": "fast",
            "title": "grandchild",
            "launch_kind": "empty",
        },
        headers=worker_headers,
    )
    assert start_resp.status_code == 403


# ---------------------------------------------------------------------------
# Lifecycle driver-start dedup — create-door boundary
# ---------------------------------------------------------------------------


async def _seed_driven_todo(
    api: AsyncClient,
    project_root: Path,
    slug: str,
    holder_id: str,
    *,
    as_orchestrator: bool,
) -> None:
    """Seed a live driver for ``slug`` in ``project_root``: a live holder session
    plus a todo whose ``active_runner`` points at it. An orchestrator holder also
    registers as the registry owner; a worker holder is seen only via active_runner.
    """
    await api.db.create_session(
        computer_name="TestComputer",
        tmux_session_name=f"tmux-{holder_id}",
        last_input_origin="terminal",
        title=f"holder {slug}",
        session_id=holder_id,
        system_role=ROLE_ORCHESTRATOR if as_orchestrator else ROLE_WORKER,
        project_path=str(project_root),
        working_slug=slug,
        emit_session_started=False,
    )
    todos_db = await get_todos_db(project_root)
    await todos_db.add_to_todo(slug, after=None)
    await todos_db.write_state(
        slug,
        TodoState(
            schema_version=5,
            kind="change",
            lifecycle_phase=LifecyclePhase.PREPARED.value,
            active_runner=holder_id,
        ).model_dump(exclude_none=True),
    )


async def _bound_session_ids(api: AsyncClient, slug: str) -> list[str]:
    sessions = await api.db.list_sessions(include_closed=True)
    return [s.session_id for s in sessions if s.working_slug == slug]


async def test_run_session_refuses_duplicate_orchestrator_driver(api: AsyncClient, tmp_path: Path) -> None:
    project = tmp_path / "orch-conflict"
    project.mkdir()
    holder = "holder-orch"
    await _seed_driven_todo(api, resolve_state_root(project), "orch-slug", holder, as_orchestrator=True)

    resp = await api.post(
        "/sessions/run",
        json={
            "computer": "TestComputer",
            "command": "/next-work",
            "args": "orch-slug",
            "project": str(project),
            "agent": "claude",
        },
    )

    assert resp.status_code == 409, resp.text
    assert holder in resp.text
    assert await _bound_session_ids(api, "orch-slug") == [holder]


async def test_run_session_refuses_duplicate_task_runner(api: AsyncClient, tmp_path: Path) -> None:
    project = tmp_path / "task-conflict"
    project.mkdir()
    holder = "holder-task"
    await _seed_driven_todo(api, resolve_state_root(project), "task-slug", holder, as_orchestrator=False)

    resp = await api.post(
        "/sessions/run",
        json={
            "computer": "TestComputer",
            "command": "/next-run-task",
            "args": "task-slug",
            "project": str(project),
            "agent": "claude",
        },
    )

    assert resp.status_code == 409, resp.text
    assert holder in resp.text
    assert await _bound_session_ids(api, "task-slug") == [holder]


async def test_run_session_allows_worker_child_spawn_for_held_slug(api: AsyncClient, tmp_path: Path) -> None:
    project = tmp_path / "worker-allow"
    project.mkdir()
    holder = "holder-w"
    await _seed_driven_todo(api, resolve_state_root(project), "held-slug", holder, as_orchestrator=True)

    resp = await api.post(
        "/sessions/run",
        json={
            "computer": "TestComputer",
            "command": "/next-build",
            "args": "held-slug",
            "project": str(project),
            "agent": "claude",
        },
    )

    assert resp.status_code == 200, resp.text
    bound = await _bound_session_ids(api, "held-slug")
    assert holder in bound
    assert len(bound) == 2


async def test_create_session_refuses_duplicate_driver_on_worktree(api: AsyncClient, tmp_path: Path) -> None:
    project = tmp_path / "tree-conflict"
    project.mkdir()
    holder = "holder-tree"
    await _seed_driven_todo(api, resolve_state_root(project), "tree-slug", holder, as_orchestrator=True)

    resp = await api.post(
        "/sessions",
        json={
            "computer": "TestComputer",
            "project_path": str(project),
            "agent": "claude",
            "thinking_mode": "fast",
            "subdir": f"{WORKTREE_DIR}/tree-slug",
            "message": "/next-work tree-slug",
        },
    )

    assert resp.status_code == 409, resp.text
    assert holder in resp.text
    assert await _bound_session_ids(api, "tree-slug") == [holder]


_VERSIONING_SPEC = "project/spec/feature/workflow/artifact-versioning"


@pytest.mark.spec(_VERSIONING_SPEC, "UC-WAV14")
async def test_write_acquired_claim_releases_when_driving_session_ends(api: AsyncClient, tmp_path: Path) -> None:
    """A claim that a session acquired by writing releases when that session ends:
    active_runner is cleared, leaving the slug with no live driver."""
    project = tmp_path / "claim-release"
    project.mkdir()
    project_root = resolve_state_root(project)
    holder = "holder-claim"
    slug = "release-slug"
    await _seed_driven_todo(api, project_root, slug, holder, as_orchestrator=False)

    assert await live_slug_holder(api.db, project_root, slug, holder) == holder

    result = await clear_active_runner_for_session_end(api.db, holder)

    assert result.mutated is True
    todos_db = await get_todos_db(project_root)
    state = await todos_db.read_state(slug)
    assert state is not None
    assert not state.get("active_runner")
    assert await live_slug_holder(api.db, project_root, slug, None) is None
