"""Unit tests for the full session token lifecycle.

Task 7.5 — covers the end-to-end token flow at component level:
- Bootstrap issues a DB record (integration of issue + db contract)
- Token is injected into tmux env (daemon bootstrap output)
- Token-authenticated session completes auth middleware check
- Session close invokes revocation (session_cleanup calls db.revoke_session_tokens)
- Post-close token is rejected by validate_session_token
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.db import resolve_session_principal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _future_iso() -> str:
    return (datetime.now(UTC) + timedelta(hours=24)).isoformat()


def _make_token_record(
    token: str | None = None,
    session_id: str = "sess-lifecycle",
    principal: str = "system:sess-lifecycle",
    role: str = "admin",
    revoked_at: str | None = None,
) -> MagicMock:
    from teleclaude.core import db_models

    record = MagicMock(spec=db_models.SessionToken)
    record.token = token or str(uuid.uuid4())
    record.session_id = session_id
    record.principal = principal
    record.role = role
    record.expires_at = _future_iso()
    record.revoked_at = revoked_at
    return record


def _make_session(
    session_id: str = "sess-lifecycle",
    principal: str | None = "system:sess-lifecycle",
    human_email: str | None = None,
    human_role: str | None = "admin",
) -> MagicMock:
    session = MagicMock()
    session.session_id = session_id
    session.principal = principal
    session.human_email = human_email
    session.human_role = human_role
    session.tmux_session_name = f"tmux-{session_id}"
    session.project_path = "/tmp/project"
    session.subdir = None
    return session


# ---------------------------------------------------------------------------
# 1. Bootstrap issues a token and injects into tmux env
# ---------------------------------------------------------------------------


class TestBootstrapIssuesToken:
    """Session bootstrap issues a token and injects TELEC_SESSION_TOKEN into tmux."""

    @pytest.mark.unit
    def test_bootstrap_principal_resolves_to_system_id(self):
        """A session without human_email gets a system:<session_id> principal."""
        session = _make_session(session_id="sess-001", principal=None, human_email=None)
        principal, role = resolve_session_principal(session)
        assert principal == "system:sess-001"
        assert role == "admin"

    @pytest.mark.unit
    def test_bootstrap_principal_resolves_to_human_email(self):
        """A session with human_email gets a human:<email> principal."""
        session = _make_session(
            session_id="sess-001",
            principal=None,
            human_email="alice@example.com",
            human_role="admin",
        )
        principal, role = resolve_session_principal(session)
        assert principal == "human:alice@example.com"
        assert role == "admin"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_db_issue_stores_token_with_principal_and_role(self):
        """issue_session_token() persists principal and role on the token record."""
        from teleclaude.core.db import Db

        db_instance = Db.__new__(Db)
        stored: list = []
        mock_session = AsyncMock()
        mock_session.add = lambda r: stored.append(r)
        mock_session.commit = AsyncMock()

        with patch.object(db_instance, "_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            token = await db_instance.issue_session_token("sess-lifecycle", "system:sess-lifecycle", "admin")

        assert stored[0].principal == "system:sess-lifecycle"
        assert stored[0].role == "admin"
        assert stored[0].token == token


# ---------------------------------------------------------------------------
# 2. Token survives auth check while session is live
# ---------------------------------------------------------------------------


class TestLiveTokenAuth:
    """A live (non-revoked, non-expired) token passes the auth middleware."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_live_token_validate_returns_record(self):
        """validate_session_token() returns the record for a non-expired, non-revoked token."""
        from teleclaude.core.db import Db

        db_instance = Db.__new__(Db)
        record = _make_token_record()

        mock_result = MagicMock()
        mock_result.first = MagicMock(return_value=record)
        mock_session = AsyncMock()
        mock_session.exec = AsyncMock(return_value=mock_result)

        with patch.object(db_instance, "_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await db_instance.validate_session_token(record.token)

        assert result is record

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_live_token_verify_caller_returns_identity(self):
        """verify_caller() returns CallerIdentity.principal for a live token."""
        from teleclaude.api.auth import CallerIdentity, verify_caller

        record = _make_token_record(principal="system:sess-lifecycle", role="admin")
        session = _make_session(session_id=record.session_id)
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

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


# ---------------------------------------------------------------------------
# 3. Session close revokes the token
# ---------------------------------------------------------------------------


class TestSessionCloseRevokesToken:
    """Closing a session triggers revoke_session_tokens() and cache invalidation."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_terminate_session_calls_revoke_and_invalidate(self):
        """terminate_session calls revoke_session_tokens and invalidate_token_cache."""
        from teleclaude.core.session_cleanup import _terminate_session_inner

        session = _make_session(session_id="sess-lifecycle")

        with (
            patch("teleclaude.core.session_cleanup.db") as mock_db,
            patch("teleclaude.core.session_cleanup.invalidate_token_cache") as mock_invalidate,
            patch("teleclaude.core.session_cleanup.tmux_bridge") as mock_tmux,
            patch("teleclaude.core.session_cleanup.cleanup_session_resources", new_callable=AsyncMock),
            patch("teleclaude.core.session_cleanup.event_bus") as mock_event_bus,
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.revoke_session_tokens = AsyncMock()
            mock_db.update_session = AsyncMock()
            mock_db.close_session = AsyncMock()
            mock_tmux.kill_session = AsyncMock(return_value=True)
            mock_event_bus.emit = AsyncMock()

            await _terminate_session_inner("sess-lifecycle", MagicMock(), reason="test")

        mock_db.revoke_session_tokens.assert_called_once_with("sess-lifecycle")
        mock_invalidate.assert_called_once_with("sess-lifecycle")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_revoke_marks_tokens_so_validate_returns_none(self):
        """After revocation, validate_session_token returns None for that token."""
        from teleclaude.core.db import Db

        db_instance = Db.__new__(Db)
        # Token is revoked (revoked_at is set)
        revoked_record = _make_token_record(revoked_at=datetime.now(UTC).isoformat())

        mock_result = MagicMock()
        mock_result.first = MagicMock(return_value=revoked_record)
        mock_session = AsyncMock()
        mock_session.exec = AsyncMock(return_value=mock_result)

        with patch.object(db_instance, "_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await db_instance.validate_session_token(revoked_record.token)

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_post_close_token_rejected_in_auth(self):
        """verify_caller() raises 401 after the session token is revoked."""
        from fastapi import HTTPException

        from teleclaude.api.auth import verify_caller

        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        with (
            patch("teleclaude.api.auth._get_cached_token", return_value=None),
            patch("teleclaude.api.auth.db") as mock_db,
        ):
            # Post-close: validate_session_token returns None (revoked/expired)
            mock_db.validate_session_token = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await verify_caller(request=request, x_session_token="old-revoked-token")

        assert exc_info.value.status_code == 401
