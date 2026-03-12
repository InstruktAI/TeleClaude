"""Unit tests for session token DB operations and principal resolution.

Tests cover: issuance, validation (valid/expired/revoked), bulk revocation,
and the resolve_session_principal helper.
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


def _make_session(
    session_id: str = "sess-001",
    human_email: str | None = None,
    human_role: str | None = None,
    principal: str | None = None,
) -> MagicMock:
    session = MagicMock()
    session.session_id = session_id
    session.human_email = human_email
    session.human_role = human_role
    session.principal = principal
    return session


def _make_token_record(
    token: str | None = None,
    session_id: str = "sess-001",
    principal: str = "system:sess-001",
    role: str = "admin",
    expires_at: str | None = None,
    revoked_at: str | None = None,
) -> MagicMock:
    """Build a mock SessionToken record."""
    from teleclaude.core import db_models

    record = MagicMock(spec=db_models.SessionToken)
    record.token = token or str(uuid.uuid4())
    record.session_id = session_id
    record.principal = principal
    record.role = role
    record.expires_at = expires_at or (datetime.now(UTC) + timedelta(hours=24)).isoformat()
    record.revoked_at = revoked_at
    return record


# ---------------------------------------------------------------------------
# resolve_session_principal
# ---------------------------------------------------------------------------


class TestResolveSessionPrincipal:
    """Tests for the resolve_session_principal() helper."""

    @pytest.mark.unit
    def test_human_session_returns_human_principal(self):
        session = _make_session(human_email="alice@example.com", human_role="admin")
        principal, role = resolve_session_principal(session)
        assert principal == "human:alice@example.com"
        assert role == "admin"

    @pytest.mark.unit
    def test_human_session_defaults_role_to_admin(self):
        session = _make_session(human_email="alice@example.com", human_role=None)
        principal, role = resolve_session_principal(session)
        assert principal == "human:alice@example.com"
        assert role == "admin"

    @pytest.mark.unit
    def test_system_session_uses_full_session_id(self):
        session = _make_session(session_id="abc-def-123", human_email=None)
        principal, role = resolve_session_principal(session)
        assert principal == "system:abc-def-123"
        assert "abc-def-123" in principal
        assert role == "admin"

    @pytest.mark.unit
    def test_system_principal_does_not_truncate_id(self):
        long_id = "a" * 64
        session = _make_session(session_id=long_id, human_email=None)
        principal, _ = resolve_session_principal(session)
        # Full ID must appear unmodified in the principal.
        assert long_id in principal


# ---------------------------------------------------------------------------
# DB operations (mocked)
# ---------------------------------------------------------------------------


class TestIssueSessionToken:
    """Tests for db.issue_session_token()."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_uuid_token(self):
        from teleclaude.core.db import Db

        db_instance = Db.__new__(Db)
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        with patch.object(db_instance, "_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            token = await db_instance.issue_session_token("sess-001", "system:sess-001", "admin")

        assert isinstance(token, str)
        # Must be a valid UUID.
        uuid.UUID(token)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stores_record_with_correct_fields(self):
        from teleclaude.core import db_models
        from teleclaude.core.db import Db

        db_instance = Db.__new__(Db)
        stored: list[db_models.SessionToken] = []
        mock_session = AsyncMock()
        mock_session.add = lambda r: stored.append(r)
        mock_session.commit = AsyncMock()

        with patch.object(db_instance, "_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            await db_instance.issue_session_token("sess-001", "human:alice@example.com", "admin")

        assert len(stored) == 1
        record = stored[0]
        assert record.session_id == "sess-001"
        assert record.principal == "human:alice@example.com"
        assert record.role == "admin"
        assert record.revoked_at is None
        assert record.expires_at > record.issued_at


class TestValidateSessionToken:
    """Tests for db.validate_session_token()."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_valid_token_returns_record(self):
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
    async def test_expired_token_returns_none(self):
        from teleclaude.core.db import Db

        db_instance = Db.__new__(Db)
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        record = _make_token_record(expires_at=past)

        mock_result = MagicMock()
        mock_result.first = MagicMock(return_value=record)
        mock_session = AsyncMock()
        mock_session.exec = AsyncMock(return_value=mock_result)

        with patch.object(db_instance, "_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await db_instance.validate_session_token(record.token)

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_revoked_token_returns_none(self):
        from teleclaude.core.db import Db

        db_instance = Db.__new__(Db)
        record = _make_token_record(revoked_at=datetime.now(UTC).isoformat())

        mock_result = MagicMock()
        mock_result.first = MagicMock(return_value=record)
        mock_session = AsyncMock()
        mock_session.exec = AsyncMock(return_value=mock_result)

        with patch.object(db_instance, "_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await db_instance.validate_session_token(record.token)

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unknown_token_returns_none(self):
        from teleclaude.core.db import Db

        db_instance = Db.__new__(Db)

        mock_result = MagicMock()
        mock_result.first = MagicMock(return_value=None)
        mock_session = AsyncMock()
        mock_session.exec = AsyncMock(return_value=mock_result)

        with patch.object(db_instance, "_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await db_instance.validate_session_token("no-such-token")

        assert result is None


class TestRevokeSessionTokens:
    """Tests for db.revoke_session_tokens()."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_revoke_calls_update(self):
        from teleclaude.core.db import Db

        db_instance = Db.__new__(Db)
        mock_result = MagicMock()
        mock_session = AsyncMock()
        mock_session.exec = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        with patch.object(db_instance, "_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            # Should not raise.
            await db_instance.revoke_session_tokens("sess-001")

        mock_session.exec.assert_called_once()
        mock_session.commit.assert_called_once()
