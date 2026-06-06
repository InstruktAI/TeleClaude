"""Functional tests for session identity and human_role behavior.

These tests act as an agent would: create sessions via the real API,
receive tokens, and use those tokens to call further API endpoints.
The full auth stack runs — verify_caller, role clearance, token issuance.
No fallback to admin should exist for sessions without explicit identity.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from teleclaude.api import auth as auth_mod
from teleclaude.api import sessions_routes
from teleclaude.api.session_ownership import LocalOwnership, RemoteOwnership, resolve_session_ownership
from teleclaude.api.session_remote import dispatch_session_close_to_peer
from teleclaude.constants import EVENT_END_SESSION
from teleclaude.core.adapter_client._remote import RemoteDispatchError, _RemoteMixin
from teleclaude.core.command_handlers import _session as session_handler_mod
from teleclaude.core.identity import IdentityContext
from teleclaude.core.models import MessageMetadata, SessionSnapshot
from teleclaude.core.models._session import Session
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import CloseSessionCommand

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SPEC = "project/spec/feature/agent_runtime/session-lifecycle"


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
        self.sent: list[dict[str, object]] = []
        self.reads: list[dict[str, object]] = []

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
        self.dispatches: list[dict[str, object]] = []

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
    snapshot = _snapshot("session-1", computer="PeerComputer")

    ownership = await resolve_session_ownership(
        "session-1",
        db=_OwnershipDb(None),
        cache=_OwnershipCache([snapshot]),
    )

    assert isinstance(ownership, RemoteOwnership)
    assert ownership.computer == "PeerComputer"
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
