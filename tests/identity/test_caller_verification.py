from __future__ import annotations

import pytest
from fastapi import HTTPException

from teleclaude.api import auth as auth_mod
from teleclaude.api.todo_stamp_routes import _human_gate_caller_stamp_id
from teleclaude.core.db import Db

SPEC = "project/spec/feature/identity/caller-verification"

HUMAN_EMAIL = "maurice@instrukt.ai"
HUMAN_SESSION_ID = "sess-human"
SYSTEM_SESSION_ID = "sess-system"
ANON_SESSION_ID = "sess-anon"
ROLE_ONLY_HUMAN_ROLE = "member"


@pytest.fixture
async def db(monkeypatch: pytest.MonkeyPatch) -> Db:
    """Real in-memory DB wired into the auth module; storage is the only mock."""
    test_db = Db(":memory:")
    await test_db.initialize()
    monkeypatch.setattr(auth_mod, "db", test_db)
    return test_db


async def _make_session(
    test_db: Db,
    session_id: str,
    *,
    system_role: str | None = None,
    human_email: str | None = None,
    human_role: str | None = None,
) -> None:
    await test_db.create_session(
        computer_name="test",
        tmux_session_name=f"tmux-{session_id}",
        last_input_origin="cli",
        title="t",
        session_id=session_id,
        system_role=system_role,
        human_email=human_email,
        human_role=human_role,
        emit_session_started=False,
    )
    auth_mod.invalidate_session_cache(session_id)


@pytest.mark.functional
@pytest.mark.spec(SPEC, "UC-CV-SESSION-PRINCIPAL-HUMAN")
async def test_human_rooted_session_resolves_human_principal_and_clears_gate(db: Db) -> None:
    """A human-rooted session row (human_email, no token) surfaces a human principal
    and is accepted by the human-principal gate."""
    await _make_session(db, HUMAN_SESSION_ID, human_email=HUMAN_EMAIL, human_role="admin")
    expected_principal = f"human:{HUMAN_EMAIL}"

    identity = await auth_mod.verify_caller(x_caller_session_id=HUMAN_SESSION_ID)

    assert identity.principal == expected_principal
    assert _human_gate_caller_stamp_id(identity) == expected_principal


@pytest.mark.functional
@pytest.mark.spec(SPEC, "UC-CV-SESSION-PRINCIPAL-SYSTEM")
async def test_system_role_session_resolves_system_principal_and_gate_refuses(db: Db) -> None:
    """A system-role session row (e.g. an emulated-PO standin) resolves to a system
    principal and is refused by the human-principal gate."""
    await _make_session(db, SYSTEM_SESSION_ID, system_role="orchestrator")
    expected_principal = f"system:{SYSTEM_SESSION_ID}"

    identity = await auth_mod.verify_caller(x_caller_session_id=SYSTEM_SESSION_ID)

    assert identity.principal == expected_principal
    with pytest.raises(HTTPException) as exc_info:
        _human_gate_caller_stamp_id(identity)
    assert exc_info.value.status_code == 403


@pytest.mark.functional
@pytest.mark.spec(SPEC, "UC-CV-SESSION-PRINCIPAL-NONE")
async def test_human_role_only_session_keeps_no_principal_and_authorizes_on_role(db: Db) -> None:
    """A session that carries only a human_role (no principal, no human_email, no
    system_role) — the shape daemon-hosted operations and child-session creation
    produce — authenticates with principal=None while preserving its human_role as
    the authorization basis. The human-principal gate refuses it (no human:<…>)."""
    await _make_session(db, ANON_SESSION_ID, human_role=ROLE_ONLY_HUMAN_ROLE)

    identity = await auth_mod.verify_caller(x_caller_session_id=ANON_SESSION_ID)

    assert identity.principal is None
    assert identity.human_role == ROLE_ONLY_HUMAN_ROLE
    with pytest.raises(HTTPException) as exc_info:
        _human_gate_caller_stamp_id(identity)
    assert exc_info.value.status_code == 403
