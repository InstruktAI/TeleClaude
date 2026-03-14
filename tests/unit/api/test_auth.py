"""Tests for teleclaude.api.auth — verify_caller token path, clearance checks, principal wiring."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api.auth import CallerIdentity, verify_caller

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_record(
    session_id: str = "sess-001",
    human_role: str | None = None,
    tmux_session_name: str | None = "tmux-sess-001",
    system_role: str | None = None,
) -> MagicMock:
    session = MagicMock()
    session.session_id = session_id
    session.human_role = human_role
    session.tmux_session_name = tmux_session_name
    session.system_role = system_role
    session.human_email = None
    return session


def _make_token_record(
    token: str | None = None,
    session_id: str = "sess-001",
    principal: str = "system:sess-001",
    role: str = "admin",
    expires_at: str | None = None,
    revoked_at: str | None = None,
) -> MagicMock:
    from teleclaude.core import db_models

    record = MagicMock(spec=db_models.SessionToken)
    record.token = token or str(uuid.uuid4())
    record.session_id = session_id
    record.principal = principal
    record.role = role
    record.expires_at = expires_at or (datetime.now(UTC) + timedelta(hours=24)).isoformat()
    record.revoked_at = revoked_at
    return record


def _make_request() -> MagicMock:
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = "127.0.0.1"
    return req


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
        request = _make_request()

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

            identity = await verify_caller(request=request, x_session_token=token_record.token)

        assert isinstance(identity, CallerIdentity)
        assert identity.session_id == "sess-001"
        assert identity.principal == "system:sess-001"
        assert identity.principal_role == "admin"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self):
        """An unknown/expired/revoked token raises HTTP 401."""
        request = _make_request()

        with (
            patch("teleclaude.api.auth._get_cached_token", return_value=None),
            patch("teleclaude.api.auth.db") as mock_db,
        ):
            mock_db.validate_session_token = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await verify_caller(request=request, x_session_token="invalid-token")

        assert exc_info.value.status_code == 401

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_token_with_unknown_session_raises_401(self):
        """A valid token pointing to a non-existent session raises HTTP 401."""
        token_record = _make_token_record()
        request = _make_request()

        with (
            patch("teleclaude.api.auth._get_cached_token", return_value=None),
            patch("teleclaude.api.auth.db") as mock_db,
            patch("teleclaude.api.auth._get_cached_session", return_value=None),
            patch("teleclaude.api.auth._put_cached_token"),
        ):
            mock_db.validate_session_token = AsyncMock(return_value=token_record)
            mock_db.get_session = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await verify_caller(request=request, x_session_token=token_record.token)

        assert exc_info.value.status_code == 401

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_token_path_takes_priority_over_session_id(self):
        """When both X-Session-Token and X-Caller-Session-Id are present, token wins."""
        token_record = _make_token_record(
            session_id="sess-token", principal="system:sess-token", role="admin",
        )
        session = _make_session_record(session_id="sess-token")
        request = _make_request()

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
                request=request,
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
        request = _make_request()

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

            identity = await verify_caller(request=request, x_session_token=token_record.token)

        assert identity.principal == "human:alice@example.com"
        assert identity.principal_role == "admin"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cached_token_avoids_db_lookup(self):
        """A token hit in the cache skips the DB validate call."""
        token_record = _make_token_record()
        session = _make_session_record(session_id=token_record.session_id)
        request = _make_request()

        with (
            patch("teleclaude.api.auth._get_cached_token", return_value=token_record),
            patch("teleclaude.api.auth.db") as mock_db,
            patch("teleclaude.api.auth._get_cached_session", return_value=session),
            patch("teleclaude.api.auth._derive_session_system_role", return_value=None),
        ):
            mock_db.validate_session_token = AsyncMock()
            await verify_caller(request=request, x_session_token=token_record.token)

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
        request = _make_request()

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

            identity = await verify_caller(request=request, x_session_token=record.token)

        assert isinstance(identity, CallerIdentity)
        assert identity.principal == "system:sess-lifecycle"
        assert identity.principal_role == "admin"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_post_close_token_rejected_in_auth(self):
        """verify_caller() raises 401 after the session token is revoked."""
        request = _make_request()

        with (
            patch("teleclaude.api.auth._get_cached_token", return_value=None),
            patch("teleclaude.api.auth.db") as mock_db,
        ):
            mock_db.validate_session_token = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await verify_caller(request=request, x_session_token="old-revoked-token")

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# CommandAuth.allows() — the core authorization logic
# ---------------------------------------------------------------------------


class TestCommandAuthAllows:
    """Tests for CommandAuth.allows() — agent-only, human-only, and mixed."""

    @pytest.mark.unit
    def test_agent_allowed_when_system_role_in_set(self):
        from teleclaude.cli.telec import CommandAuth

        auth = CommandAuth(system=frozenset({"worker"}), human=frozenset({"admin"}))
        assert auth.allows(system_role="worker", human_role=None) is True

    @pytest.mark.unit
    def test_agent_denied_when_system_role_not_in_set(self):
        from teleclaude.cli.telec import CommandAuth

        auth = CommandAuth(system=frozenset({"orchestrator"}), human=frozenset({"admin"}))
        assert auth.allows(system_role="worker", human_role=None) is False

    @pytest.mark.unit
    def test_human_allowed_when_human_role_in_set(self):
        from teleclaude.cli.telec import CommandAuth

        auth = CommandAuth(system=frozenset({"worker"}), human=frozenset({"admin", "member"}))
        assert auth.allows(system_role=None, human_role="admin") is True

    @pytest.mark.unit
    def test_human_denied_when_human_role_not_in_set(self):
        from teleclaude.cli.telec import CommandAuth

        auth = CommandAuth(system=frozenset({"worker"}), human=frozenset({"member"}))
        assert auth.allows(system_role=None, human_role="admin") is False

    @pytest.mark.unit
    def test_no_roles_returns_false(self):
        from teleclaude.cli.telec import CommandAuth

        auth = CommandAuth(system=frozenset({"worker"}), human=frozenset({"admin"}))
        assert auth.allows(system_role=None, human_role=None) is False

    @pytest.mark.unit
    def test_escalate_blocks_admin(self):
        """sessions escalate uses _HR_ALL_NON_ADMIN — admin is not in the set."""
        from teleclaude.cli.telec import CommandAuth

        auth = CommandAuth(
            system=frozenset({"worker", "orchestrator", "integrator"}),
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
        from teleclaude.cli.telec import is_command_allowed

        assert is_command_allowed("sessions list", system_role=None, human_role="admin") is True

    @pytest.mark.unit
    def test_no_roles_denied(self):
        from teleclaude.cli.telec import is_command_allowed

        assert is_command_allowed("sessions list", system_role=None, human_role=None) is False

    @pytest.mark.unit
    def test_unknown_command_denied(self):
        from teleclaude.cli.telec import is_command_allowed

        assert is_command_allowed("nonexistent command", system_role=None, human_role="admin") is False

    @pytest.mark.unit
    def test_escalate_blocks_admin_human(self):
        from teleclaude.cli.telec import is_command_allowed

        assert is_command_allowed("sessions escalate", system_role=None, human_role="admin") is False

    @pytest.mark.unit
    def test_escalate_allows_member(self):
        from teleclaude.cli.telec import is_command_allowed

        assert is_command_allowed("sessions escalate", system_role=None, human_role="member") is True

    @pytest.mark.unit
    def test_escalate_allows_worker_agent(self):
        from teleclaude.cli.telec import is_command_allowed

        assert is_command_allowed("sessions escalate", system_role="worker", human_role=None) is True


# ---------------------------------------------------------------------------
# _is_tool_denied wiring — principal fallback lives here now
# ---------------------------------------------------------------------------


class TestIsToolDeniedPrincipalWiring:
    """Verify _is_tool_denied resolves principal_role when human_role is absent."""

    @pytest.mark.unit
    def test_principal_role_used_when_human_role_absent(self):
        from teleclaude.api.auth import _is_tool_denied

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
        from teleclaude.api.auth import _is_tool_denied

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
        from teleclaude.api.auth import _is_tool_denied

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
        from teleclaude.api.auth import _is_tool_denied

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
        request = _make_request()

        with (
            patch("teleclaude.api.auth._resolve_terminal_role", return_value=None),
            patch("teleclaude.api.auth._requires_terminal_login", return_value=False),
        ):
            identity = await verify_caller(
                request=request, x_tmux_session="tc_tui",
            )

        assert identity.human_role == "admin"
        assert identity.system_role is None
        assert identity.tmux_session_name == "tc_tui"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_non_tmux_caller_no_login_single_owner_gets_admin(self):
        """Non-tmux caller without login in single-owner mode gets admin."""
        request = _make_request()

        with (
            patch("teleclaude.api.auth._resolve_terminal_role", return_value=None),
            patch("teleclaude.api.auth._requires_terminal_login", return_value=False),
        ):
            identity = await verify_caller(request=request)

        assert identity.human_role == "admin"
        assert identity.system_role is None
        assert identity.tmux_session_name is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_multi_user_no_login_raises_401(self):
        """Any caller without login in multi-user mode raises 401."""
        request = _make_request()

        with (
            patch("teleclaude.api.auth._resolve_terminal_role", return_value=None),
            patch("teleclaude.api.auth._requires_terminal_login", return_value=True),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await verify_caller(request=request, x_tmux_session="tc_tui")

            assert exc_info.value.status_code == 401
