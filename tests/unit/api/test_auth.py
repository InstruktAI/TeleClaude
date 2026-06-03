"""Tests for teleclaude.api.auth — verify_caller token path, clearance checks, principal wiring."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api.auth import (
    CallerIdentity,
    _is_tool_denied,
    clearance_sessions_agent_restart,
    clearance_sessions_run,
    clearance_sessions_start,
    clearance_todos_reactivate,
    clearance_todos_reconcile,
    verify_caller,
)
from teleclaude.cli.telec import CommandAuth, is_command_allowed
from teleclaude.constants import HUMAN_ROLE_MEMBER, HUMAN_ROLE_NEWCOMER, ROLE_WORKER
from teleclaude.core import db_models

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_record(
    session_id: str = "sess-001",
    human_role: str | None = None,
    tmux_session_name: str | None = "tmux-sess-001",
    system_role: str | None = None,
    closed_at: object = None,
    lifecycle_status: str = "active",
) -> MagicMock:
    session = MagicMock()
    session.session_id = session_id
    session.human_role = human_role
    session.tmux_session_name = tmux_session_name
    session.system_role = system_role
    session.human_email = None
    session.closed_at = closed_at
    session.lifecycle_status = lifecycle_status
    return session


def _make_token_record(
    token: str | None = None,
    session_id: str = "sess-001",
    principal: str = "system:sess-001",
    role: str = "admin",
) -> MagicMock:
    record = MagicMock(spec=db_models.SessionToken)
    record.token = token or str(uuid.uuid4())
    record.session_id = session_id
    record.principal = principal
    record.role = role
    return record


class _JsonBodyRequest:
    """Minimal request double for clearance checks that inspect JSON bodies."""

    def __init__(self, body: object) -> None:
        self.headers = {"content-type": "application/json"}
        self._body = body

    async def json(self) -> object:
        return self._body


# ---------------------------------------------------------------------------
# verify_caller() token path
# ---------------------------------------------------------------------------


class TestVerifyCallerTokenPath:
    """Tests for the X-Session-Token path in verify_caller()."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_valid_token_returns_caller_identity(self):
        """A valid token resolves to a CallerIdentity with principal fields."""
        token_record = _make_token_record(principal="system:sess-001", role="admin")
        session = _make_session_record(session_id="sess-001")

        with (
            patch("teleclaude.api.auth._get_cached_token", return_value=None),
            patch("teleclaude.api.auth.db") as mock_db,
            patch("teleclaude.api.auth._get_cached_session", return_value=None),
            patch("teleclaude.api.auth._put_cached_token"),
            patch("teleclaude.api.auth._put_cached_session"),
            patch("teleclaude.api.auth._derive_session_system_role", return_value=None),
        ):
            mock_db.validate_session_token = AsyncMock(return_value=token_record)
            mock_db.get_session = AsyncMock(return_value=session)

            identity = await verify_caller(x_session_token=token_record.token)

        assert isinstance(identity, CallerIdentity)
        assert identity.session_id == "sess-001"
        assert identity.principal == "system:sess-001"
        assert identity.principal_role == "admin"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self):
        """An unknown/expired/revoked token raises HTTP 401."""
        with (
            patch("teleclaude.api.auth._get_cached_token", return_value=None),
            patch("teleclaude.api.auth.db") as mock_db,
        ):
            mock_db.validate_session_token = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await verify_caller(x_session_token="invalid-token")

        assert exc_info.value.status_code == 401

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_token_with_unknown_session_raises_401(self):
        """A valid token pointing to a non-existent session raises HTTP 401."""
        token_record = _make_token_record()

        with (
            patch("teleclaude.api.auth._get_cached_token", return_value=None),
            patch("teleclaude.api.auth.db") as mock_db,
            patch("teleclaude.api.auth._get_cached_session", return_value=None),
            patch("teleclaude.api.auth._put_cached_token"),
        ):
            mock_db.validate_session_token = AsyncMock(return_value=token_record)
            mock_db.get_session = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await verify_caller(x_session_token=token_record.token)

        assert exc_info.value.status_code == 401

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_token_path_takes_priority_over_session_id(self):
        """When both X-Session-Token and X-Caller-Session-Id are present, token wins."""
        token_record = _make_token_record(
            session_id="sess-token",
            principal="system:sess-token",
            role="admin",
        )
        session = _make_session_record(session_id="sess-token")

        with (
            patch("teleclaude.api.auth._get_cached_token", return_value=None),
            patch("teleclaude.api.auth.db") as mock_db,
            patch("teleclaude.api.auth._get_cached_session", return_value=None),
            patch("teleclaude.api.auth._put_cached_token"),
            patch("teleclaude.api.auth._put_cached_session"),
            patch("teleclaude.api.auth._derive_session_system_role", return_value=None),
        ):
            mock_db.validate_session_token = AsyncMock(return_value=token_record)
            mock_db.get_session = AsyncMock(return_value=session)

            identity = await verify_caller(
                x_session_token=token_record.token,
                x_caller_session_id="sess-other",
            )

        assert identity.session_id == "sess-token"
        assert identity.principal == "system:sess-token"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_principal_and_principal_role_populated(self):
        """CallerIdentity.principal and principal_role come from the token record."""
        token_record = _make_token_record(principal="human:alice@example.com", role="admin")
        session = _make_session_record(session_id=token_record.session_id)

        with (
            patch("teleclaude.api.auth._get_cached_token", return_value=None),
            patch("teleclaude.api.auth.db") as mock_db,
            patch("teleclaude.api.auth._get_cached_session", return_value=None),
            patch("teleclaude.api.auth._put_cached_token"),
            patch("teleclaude.api.auth._put_cached_session"),
            patch("teleclaude.api.auth._derive_session_system_role", return_value=None),
        ):
            mock_db.validate_session_token = AsyncMock(return_value=token_record)
            mock_db.get_session = AsyncMock(return_value=session)

            identity = await verify_caller(x_session_token=token_record.token)

        assert identity.principal == "human:alice@example.com"
        assert identity.principal_role == "admin"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cached_token_avoids_db_lookup(self):
        """A token hit in the cache skips the DB validate call."""
        token_record = _make_token_record()
        session = _make_session_record(session_id=token_record.session_id)

        with (
            patch("teleclaude.api.auth._get_cached_token", return_value=token_record),
            patch("teleclaude.api.auth.db") as mock_db,
            patch("teleclaude.api.auth._get_cached_session", return_value=session),
            patch("teleclaude.api.auth._derive_session_system_role", return_value=None),
        ):
            mock_db.validate_session_token = AsyncMock()
            await verify_caller(x_session_token=token_record.token)

        mock_db.validate_session_token.assert_not_called()


# ---------------------------------------------------------------------------
# verify_caller — lifecycle integration (token auth after revocation)
# ---------------------------------------------------------------------------


class TestVerifyCallerLifecycle:
    """Integration tests for verify_caller across the token lifecycle."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_live_token_verify_caller_returns_identity(self):
        """verify_caller() returns CallerIdentity.principal for a live token."""
        record = _make_token_record(principal="system:sess-lifecycle", role="admin")
        session = MagicMock()
        session.session_id = record.session_id
        session.human_role = "admin"
        session.tmux_session_name = f"tmux-{record.session_id}"
        session.system_role = None
        session.human_email = None
        session.closed_at = None
        session.lifecycle_status = "active"

        with (
            patch("teleclaude.api.auth._get_cached_token", return_value=None),
            patch("teleclaude.api.auth.db") as mock_db,
            patch("teleclaude.api.auth._get_cached_session", return_value=None),
            patch("teleclaude.api.auth._put_cached_token"),
            patch("teleclaude.api.auth._put_cached_session"),
            patch("teleclaude.api.auth._derive_session_system_role", return_value=None),
        ):
            mock_db.validate_session_token = AsyncMock(return_value=record)
            mock_db.get_session = AsyncMock(return_value=session)

            identity = await verify_caller(x_session_token=record.token)

        assert isinstance(identity, CallerIdentity)
        assert identity.principal == "system:sess-lifecycle"
        assert identity.principal_role == "admin"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_post_close_token_rejected_in_auth(self):
        """verify_caller() raises 401 after the session token is revoked."""
        with (
            patch("teleclaude.api.auth._get_cached_token", return_value=None),
            patch("teleclaude.api.auth.db") as mock_db,
        ):
            mock_db.validate_session_token = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await verify_caller(x_session_token="old-revoked-token")

        assert exc_info.value.status_code == 401

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_token_for_session_stuck_in_closing_is_rejected(self) -> None:
        """Defense-in-depth: a token whose owning session is mid-teardown must be
        rejected, even if revoke_session_tokens never ran and left the token in the
        ledger. This is the exact failure mode where a cleanup hiccup during close
        previously stranded the session — without this check, the token would
        outlive the session's authority.
        """
        token_record = _make_token_record(session_id="sess-stale")
        session = _make_session_record(
            session_id="sess-stale",
            closed_at=datetime.now(UTC),
            lifecycle_status="closing",
        )

        with (
            patch("teleclaude.api.auth._get_cached_token", return_value=None),
            patch("teleclaude.api.auth._get_cached_session", return_value=None),
            patch("teleclaude.api.auth._put_cached_token"),
            patch("teleclaude.api.auth._put_cached_session"),
            patch("teleclaude.api.auth.db") as mock_db,
        ):
            mock_db.validate_session_token = AsyncMock(return_value=token_record)
            mock_db.get_session = AsyncMock(return_value=session)

            with pytest.raises(HTTPException) as exc_info:
                await verify_caller(x_session_token=token_record.token)

        assert exc_info.value.status_code == 401


async def _orchestrator_token_passes_clearance(
    clearance_dependency: Callable[..., Awaitable[CallerIdentity]],
) -> None:
    token_record = _make_token_record(
        session_id="sess-orchestrator",
        principal="system:sess-orchestrator",
        role="admin",
    )
    session = _make_session_record(
        session_id="sess-orchestrator",
        human_role=None,
        tmux_session_name="tmux-sess-orchestrator",
        system_role="orchestrator",
    )

    with (
        patch("teleclaude.api.auth._get_cached_token", return_value=None),
        patch("teleclaude.api.auth.db") as mock_db,
        patch("teleclaude.api.auth._get_cached_session", return_value=None),
        patch("teleclaude.api.auth._put_cached_token"),
        patch("teleclaude.api.auth._put_cached_session"),
    ):
        mock_db.validate_session_token = AsyncMock(return_value=token_record)
        mock_db.get_session = AsyncMock(return_value=session)

        identity = await verify_caller(x_session_token=token_record.token)
        cleared_identity = await clearance_dependency(identity=identity)

    assert cleared_identity.session_id == "sess-orchestrator"
    assert cleared_identity.system_role == "orchestrator"
    assert cleared_identity.principal == "system:sess-orchestrator"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orchestrator_token_passes_clearance_sessions_start() -> None:
    """clearance_sessions_start admits a token-authenticated orchestrator identity."""
    await _orchestrator_token_passes_clearance(clearance_sessions_start)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orchestrator_token_passes_clearance_sessions_run() -> None:
    """clearance_sessions_run admits a token-authenticated orchestrator identity."""
    await _orchestrator_token_passes_clearance(clearance_sessions_run)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orchestrator_token_passes_clearance_todos_reconcile() -> None:
    """clearance_todos_reconcile admits a token-authenticated orchestrator identity.

    Regression guard for the dual-factor / RBAC boundary on the mutating
    POST /todos/reconcile endpoint — when this was first added the handler
    had no Depends(...) clearance binding, which bypassed the security
    contract documented at the top of todo_routes.py.
    """
    await _orchestrator_token_passes_clearance(clearance_todos_reconcile)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clearance_todos_reconcile_rejects_caller_without_identity() -> None:
    """An unauthenticated caller (no token, no terminal login) must be denied.

    Without either factor verify_caller raises 401, so the clearance dependency
    is never reached for an anonymous caller — that is the documented fail-closed
    behavior of the dual-factor boundary on every mutating todo endpoint, and
    POST /todos/reconcile inherits it via Depends(clearance_todos_reconcile).
    """
    with patch("teleclaude.api.auth._requires_terminal_login", return_value=True):
        with pytest.raises(HTTPException) as exc_info:
            await verify_caller(x_session_token=None, x_telec_email=None)
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# CommandAuth.allows() — the core authorization logic
# ---------------------------------------------------------------------------


class TestCommandAuthAllows:
    """Tests for CommandAuth.allows() — agent-only, human-only, and mixed."""

    @pytest.mark.unit
    def test_agent_allowed_when_system_role_in_set(self):
        auth = CommandAuth(system=frozenset({"worker"}), human=frozenset({"admin"}))
        assert auth.allows(system_role="worker", human_role=None) is True

    @pytest.mark.unit
    def test_agent_denied_when_system_role_not_in_set(self):
        auth = CommandAuth(system=frozenset({"system"}), human=frozenset({"admin"}))
        assert auth.allows(system_role="worker", human_role=None) is False

    @pytest.mark.unit
    def test_human_allowed_when_human_role_in_set(self):
        auth = CommandAuth(system=frozenset({"worker"}), human=frozenset({"admin", "member"}))
        assert auth.allows(system_role=None, human_role="admin") is True

    @pytest.mark.unit
    def test_human_denied_when_human_role_not_in_set(self):
        auth = CommandAuth(system=frozenset({"worker"}), human=frozenset({"member"}))
        assert auth.allows(system_role=None, human_role="admin") is False

    @pytest.mark.unit
    def test_no_roles_returns_false(self):
        auth = CommandAuth(system=frozenset({"worker"}), human=frozenset({"admin"}))
        assert auth.allows(system_role=None, human_role=None) is False

    @pytest.mark.unit
    def test_escalate_blocks_admin(self):
        """sessions escalate uses _HR_ALL_NON_ADMIN — admin is not in the set."""
        auth = CommandAuth(
            system=frozenset({"worker", "system", "integrator"}),
            human=frozenset({"member", "contributor", "newcomer", "customer"}),
        )
        assert auth.allows(system_role=None, human_role="admin") is False
        assert auth.allows(system_role=None, human_role="member") is True
        assert auth.allows(system_role="worker", human_role=None) is True


# ---------------------------------------------------------------------------
# is_command_allowed() — 3-param interface
# ---------------------------------------------------------------------------


class TestIsCommandAllowed:
    """Tests for is_command_allowed() with resolved roles (no principal fallback)."""

    @pytest.mark.unit
    def test_admin_allowed_for_standard_commands(self):
        assert is_command_allowed("sessions list", system_role=None, human_role="admin") is True

    @pytest.mark.unit
    def test_no_roles_denied(self):
        assert is_command_allowed("sessions list", system_role=None, human_role=None) is False

    @pytest.mark.unit
    def test_unknown_command_denied(self):
        assert is_command_allowed("nonexistent command", system_role=None, human_role="admin") is False

    @pytest.mark.unit
    def test_escalate_blocks_admin_human(self):
        assert is_command_allowed("sessions escalate", system_role=None, human_role="admin") is False

    @pytest.mark.unit
    def test_escalate_allows_member(self):
        assert is_command_allowed("sessions escalate", system_role=None, human_role="member") is True

    @pytest.mark.unit
    def test_escalate_allows_worker_agent(self):
        assert is_command_allowed("sessions escalate", system_role="worker", human_role=None) is True

    @pytest.mark.unit
    def test_restart_command_available_to_worker_agents(self):
        assert is_command_allowed("sessions restart", system_role=ROLE_WORKER, human_role=None) is True


# ---------------------------------------------------------------------------
# Restart clearance — self restart is caller-owned, arbitrary restart is privileged
# ---------------------------------------------------------------------------


class TestAgentRestartClearance:
    """Tests for argument-aware authorization on the session restart endpoint."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_worker_agent_can_restart_own_session(self):
        identity = CallerIdentity(
            session_id="sess-001",
            system_role=ROLE_WORKER,
            human_role=None,
            tmux_session_name="tmux-sess-001",
        )

        result = await clearance_sessions_agent_restart(
            _JsonBodyRequest({"self_restart": True}),
            "sess-001",
            identity,
        )

        assert result is identity

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_worker_agent_cannot_restart_another_session(self):
        identity = CallerIdentity(
            session_id="sess-001",
            system_role=ROLE_WORKER,
            human_role=None,
            tmux_session_name="tmux-sess-001",
        )

        with pytest.raises(HTTPException) as exc_info:
            await clearance_sessions_agent_restart(
                _JsonBodyRequest({"self_restart": True}),
                "sess-002",
                identity,
            )

        assert exc_info.value.status_code == 403
        assert "telec sessions restart" in str(exc_info.value.detail)
        assert "telec sessions run" not in str(exc_info.value.detail)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_admin_can_restart_arbitrary_session(self):
        identity = CallerIdentity(
            session_id="",
            system_role=None,
            human_role="admin",
            tmux_session_name=None,
        )

        result = await clearance_sessions_agent_restart(
            _JsonBodyRequest({}),
            "sess-002",
            identity,
        )

        assert result is identity


# ---------------------------------------------------------------------------
# _is_tool_denied wiring — principal fallback lives here now
# ---------------------------------------------------------------------------


class TestIsToolDeniedPrincipalWiring:
    """Verify _is_tool_denied resolves principal_role when human_role is absent."""

    @pytest.mark.unit
    def test_principal_role_used_when_human_role_absent(self):
        identity = CallerIdentity(
            session_id="sess-001",
            system_role=None,
            human_role=None,
            tmux_session_name=None,
            principal="system:sess-001",
            principal_role="admin",
        )

        assert _is_tool_denied("sessions list", identity) is False

    @pytest.mark.unit
    def test_human_role_takes_precedence_over_principal_role(self):
        identity = CallerIdentity(
            session_id="sess-001",
            system_role=None,
            human_role="admin",
            tmux_session_name=None,
            principal="system:sess-001",
            principal_role="customer",
        )

        assert _is_tool_denied("sessions list", identity) is False

    @pytest.mark.unit
    def test_no_principal_no_human_role_denies(self):
        identity = CallerIdentity(
            session_id="sess-001",
            system_role=None,
            human_role=None,
            tmux_session_name=None,
            principal=None,
            principal_role=None,
        )

        assert _is_tool_denied("sessions list", identity) is True

    @pytest.mark.unit
    def test_principal_without_principal_role_denies(self):
        identity = CallerIdentity(
            session_id="sess-001",
            system_role=None,
            human_role=None,
            tmux_session_name=None,
            principal="system:sess-001",
            principal_role=None,
        )

        assert _is_tool_denied("sessions list", identity) is True


# ---------------------------------------------------------------------------
# Single-owner mode — implicit admin without login
# ---------------------------------------------------------------------------


class TestSingleOwnerImplicitAdmin:
    """In single-owner mode (0-1 registered people), unidentified callers are admin."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tmux_caller_no_login_single_owner_gets_admin(self):
        """Tmux caller without login in single-owner mode gets admin."""
        with (
            patch("teleclaude.api.auth._resolve_terminal_role", return_value=None),
            patch("teleclaude.api.auth._requires_terminal_login", return_value=False),
        ):
            identity = await verify_caller(
                x_tmux_session="tc_tui",
            )

        assert identity.human_role == "admin"
        assert identity.system_role is None
        assert identity.tmux_session_name == "tc_tui"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_non_tmux_caller_no_login_single_owner_gets_admin(self):
        """Non-tmux caller without login in single-owner mode gets admin."""
        with (
            patch("teleclaude.api.auth._resolve_terminal_role", return_value=None),
            patch("teleclaude.api.auth._requires_terminal_login", return_value=False),
        ):
            identity = await verify_caller()

        assert identity.human_role == "admin"
        assert identity.system_role is None
        assert identity.tmux_session_name is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_multi_user_no_login_raises_401(self):
        """Any caller without login in multi-user mode raises 401."""
        with (
            patch("teleclaude.api.auth._resolve_terminal_role", return_value=None),
            patch("teleclaude.api.auth._requires_terminal_login", return_value=True),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await verify_caller(x_tmux_session="tc_tui")

            assert exc_info.value.status_code == 401


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clearance_todos_reactivate_allows_member() -> None:
    """clearance_todos_reactivate admits a human with MEMBER role."""
    identity = CallerIdentity(
        session_id="sess-1",
        system_role=None,
        human_role=HUMAN_ROLE_MEMBER,
        tmux_session_name=None,
    )

    cleared = await clearance_todos_reactivate(identity=identity)
    assert cleared is identity


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clearance_todos_reactivate_refuses_newcomer() -> None:
    """clearance_todos_reactivate denies a human with NEWCOMER role."""
    identity = CallerIdentity(
        session_id="sess-1",
        system_role=None,
        human_role=HUMAN_ROLE_NEWCOMER,
        tmux_session_name=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        await clearance_todos_reactivate(identity=identity)
    assert exc_info.value.status_code == 403
    assert "telec todo reactivate" in str(exc_info.value.detail)
