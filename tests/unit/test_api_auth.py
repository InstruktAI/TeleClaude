"""Unit tests for auth middleware (token path) and clearance checks.

Tasks 7.2 and 7.3:
- verify_caller() token path: valid token, invalid/expired/revoked, priority, CallerIdentity fields
- is_command_allowed(): principal-backed sessions, principal_role fallback, anonymous denial
"""

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
# Task 7.2: verify_caller() token path
# ---------------------------------------------------------------------------


class TestVerifyCallerTokenPath:
    """Tests for the X-Session-Token path in verify_caller()."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_valid_token_returns_caller_identity(self):
        """A valid token resolves to a CallerIdentity with principal fields."""
        token_record = _make_token_record(
            principal="system:sess-001",
            role="admin",
        )
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

            identity = await verify_caller(
                request=request,
                x_session_token=token_record.token,
            )

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
                await verify_caller(
                    request=request,
                    x_session_token="invalid-token",
                )

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
                await verify_caller(
                    request=request,
                    x_session_token=token_record.token,
                )

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
                x_caller_session_id="sess-other",  # should be ignored
            )

        # Identity comes from the token, not the session-id header
        assert identity.session_id == "sess-token"
        assert identity.principal == "system:sess-token"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_principal_and_principal_role_populated(self):
        """CallerIdentity.principal and principal_role come from the token record."""
        token_record = _make_token_record(
            principal="human:alice@example.com",
            role="admin",
        )
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

            identity = await verify_caller(
                request=request,
                x_session_token=token_record.token,
            )

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

            await verify_caller(
                request=request,
                x_session_token=token_record.token,
            )

        mock_db.validate_session_token.assert_not_called()


# ---------------------------------------------------------------------------
# Task 7.3: is_command_allowed() clearance checks for principal-based auth
# ---------------------------------------------------------------------------


class TestIsCommandAllowedWithPrincipal:
    """Tests for principal-based authorization in is_command_allowed()."""

    @pytest.mark.unit
    def test_principal_backed_session_allowed_when_human_role_absent(self):
        """A session with a principal but no human_role is allowed via principal_role."""
        from teleclaude.cli.telec import is_command_allowed

        # Use a command that admin can reach (most commands are admin-allowed)
        result = is_command_allowed(
            "sessions list",
            system_role=None,
            human_role=None,
            principal="system:sess-001",
            principal_role="admin",
        )
        assert result is True

    @pytest.mark.unit
    def test_principal_role_used_for_allowlist_when_human_role_absent(self):
        """When human_role is None, principal_role fills the effective role."""
        from teleclaude.cli.telec import is_command_allowed

        # With principal_role="admin", should be permitted
        assert (
            is_command_allowed(
                "sessions list",
                system_role=None,
                human_role=None,
                principal="system:sess-001",
                principal_role="admin",
            )
            is True
        )

    @pytest.mark.unit
    def test_anonymous_caller_denied_when_both_role_and_principal_absent(self):
        """No human_role and no principal means access is denied (fail closed)."""
        from teleclaude.cli.telec import is_command_allowed

        result = is_command_allowed(
            "sessions list",
            system_role=None,
            human_role=None,
            principal=None,
            principal_role=None,
        )
        assert result is False

    @pytest.mark.unit
    def test_human_role_takes_precedence_over_principal_role(self):
        """When human_role is set, it is used; principal_role does not override it."""
        from teleclaude.cli.telec import is_command_allowed

        # human_role="admin" is set — principal_role is ignored for the effective role
        result = is_command_allowed(
            "sessions list",
            system_role=None,
            human_role="admin",
            principal="system:sess-001",
            principal_role="worker",  # less permissive, but human_role wins
        )
        assert result is True

    @pytest.mark.unit
    def test_principal_without_principal_role_still_denies(self):
        """A principal with no role cannot pass the human-role gate."""
        from teleclaude.cli.telec import is_command_allowed

        result = is_command_allowed(
            "sessions list",
            system_role=None,
            human_role=None,
            principal="system:sess-001",
            principal_role=None,  # no role even with principal
        )
        assert result is False


# ---------------------------------------------------------------------------
# Task 7.3b: _is_tool_denied wiring — verifies principal fields are passed through
# ---------------------------------------------------------------------------


class TestIsToolDeniedPrincipalWiring:
    """Verify _is_tool_denied correctly passes principal fields to is_command_allowed."""

    @pytest.mark.unit
    def test_tool_denied_passes_principal_fields(self):
        """_is_tool_denied passes CallerIdentity.principal and principal_role to is_command_allowed."""
        from teleclaude.api.auth import CallerIdentity, _is_tool_denied

        identity = CallerIdentity(
            session_id="sess-001",
            system_role=None,
            human_role=None,
            tmux_session_name=None,
            principal="system:sess-001",
            principal_role="admin",
        )

        # With principal_role="admin", the command should be allowed (not denied)
        assert _is_tool_denied("sessions list", identity) is False

    @pytest.mark.unit
    def test_tool_denied_without_principal_denies(self):
        """_is_tool_denied denies when no principal and no human_role."""
        from teleclaude.api.auth import CallerIdentity, _is_tool_denied

        identity = CallerIdentity(
            session_id="sess-001",
            system_role=None,
            human_role=None,
            tmux_session_name=None,
            principal=None,
            principal_role=None,
        )

        assert _is_tool_denied("sessions list", identity) is True
