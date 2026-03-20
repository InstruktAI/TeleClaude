"""Functional tests for session identity and human_role behavior.

These tests act as an agent would: create sessions via the real API,
receive tokens, and use those tokens to call further API endpoints.
The full auth stack runs — verify_caller, role clearance, token issuance.
No fallback to admin should exist for sessions without explicit identity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]


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
# 1. Single-user terminal caller → admin role on session record
# ---------------------------------------------------------------------------


async def test_single_user_session_gets_admin_from_auth(api: AsyncClient) -> None:
    """In single-user mode, a terminal caller gets admin from the auth layer.

    The session record must have human_role='admin' — not because of a model
    default, but because verify_caller resolved the single-user identity.
    """
    data = await _create_session(api)
    session = await _get_session_from_db(api, data["session_id"])
    assert session is not None
    assert session.human_role == "admin"


# ---------------------------------------------------------------------------
# 2. Explicit human_role in request is preserved
# ---------------------------------------------------------------------------


async def test_explicit_member_role_preserved(api: AsyncClient) -> None:
    """When the request carries human_role='member', the session record
    must reflect that — not silently upgrade to admin.
    """
    data = await _create_session(api, human_role="member")
    session = await _get_session_from_db(api, data["session_id"])
    assert session.human_role == "member"


# ---------------------------------------------------------------------------
# 3. System session (with metadata.system_role) gets no human_role fallback
# ---------------------------------------------------------------------------


async def test_system_session_has_no_human_role_fallback(api: AsyncClient) -> None:
    """A system session created with system_role metadata should not get
    human_role='admin' from a fallback. human_role comes from the auth
    layer (single-user → admin in this test), not from a model default.
    """
    data = await _create_session(
        api,
        metadata={"system_role": "system"},
    )
    session = await _get_session_from_db(api, data["session_id"])
    assert session.session_metadata is not None
    assert session.session_metadata.system_role == "system"
    # human_role is set by auth (single-user → admin), not by fallback
    assert session.human_role == "admin"


# ---------------------------------------------------------------------------
# 4. Child session inherits parent's human_role
# ---------------------------------------------------------------------------


async def test_child_inherits_parent_human_role(api: AsyncClient) -> None:
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
    assert child.human_role == "member"
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


async def test_token_auth_with_null_human_role(api: AsyncClient) -> None:
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
    from teleclaude.api import auth as auth_mod

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
    from teleclaude.core.models._session import Session

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
    from teleclaude.core.models._session import Session

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


async def test_restricted_role_jailed_to_help_desk(api: AsyncClient, tmp_path: Path) -> None:
    """A session with human_role='newcomer' (non-admin, no system_role)
    should be jailed to the help-desk directory.
    """
    help_desk = tmp_path / "help-desk"
    help_desk.mkdir(parents=True, exist_ok=True)

    data = await _create_session(api, human_role="newcomer")
    session = await _get_session_from_db(api, data["session_id"])
    assert session.project_path is not None
    assert session.project_path.endswith("help-desk")
