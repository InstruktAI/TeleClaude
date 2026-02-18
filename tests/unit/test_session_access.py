"""Unit tests for session access control (teleclaude/api/session_access.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api.session_access import check_session_access


def _make_request(email: str | None = None, role: str | None = None):
    """Build a minimal mock request with identity headers."""
    from unittest.mock import MagicMock

    request = MagicMock()
    headers: dict[str, str] = {}
    if email:
        headers["x-web-user-email"] = email
    if role:
        headers["x-web-user-role"] = role

    def get_header(key: str, default: str | None = None) -> str | None:
        return headers.get(key, default)

    request.headers.get = get_header
    return request


def _make_session(
    email: str | None = "owner@example.com",
    visibility: str = "private",
):
    from unittest.mock import MagicMock

    session = MagicMock()
    session.human_email = email
    session.visibility = visibility
    return session


@pytest.mark.asyncio
async def test_no_identity_headers_always_allowed():
    """TUI/MCP clients without headers bypass all checks."""
    request = _make_request()  # no email
    # Should not raise
    await check_session_access(request, "any-session-id")


@pytest.mark.asyncio
async def test_admin_always_allowed():
    """Admin role bypasses all per-session checks."""
    request = _make_request(email="admin@example.com", role="admin")
    # Should not raise even without DB lookup
    with patch("teleclaude.api.session_access.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=None)
        await check_session_access(request, "any-session-id")
        mock_db.get_session.assert_not_called()


@pytest.mark.asyncio
async def test_session_not_found_raises_404():
    request = _make_request(email="user@example.com", role="member")
    with patch("teleclaude.api.session_access.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc_info:
            await check_session_access(request, "missing-id")
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_owner_can_access_own_session():
    request = _make_request(email="owner@example.com", role="member")
    session = _make_session(email="owner@example.com", visibility="private")
    with patch("teleclaude.api.session_access.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        await check_session_access(request, "session-id")


@pytest.mark.asyncio
async def test_member_cannot_access_private_other_session():
    request = _make_request(email="other@example.com", role="member")
    session = _make_session(email="owner@example.com", visibility="private")
    with patch("teleclaude.api.session_access.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        with pytest.raises(HTTPException) as exc_info:
            await check_session_access(request, "session-id")
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_member_can_access_shared_session():
    """Shared sessions are visible to all members — the core C1 scenario."""
    request = _make_request(email="other@example.com", role="member")
    session = _make_session(email="owner@example.com", visibility="shared")
    with patch("teleclaude.api.session_access.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        await check_session_access(request, "session-id")


@pytest.mark.asyncio
async def test_require_owner_blocks_non_owner():
    request = _make_request(email="other@example.com", role="member")
    session = _make_session(email="owner@example.com", visibility="shared")
    with patch("teleclaude.api.session_access.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        with pytest.raises(HTTPException) as exc_info:
            await check_session_access(request, "session-id", require_owner=True)
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_owner_allows_actual_owner():
    request = _make_request(email="owner@example.com", role="member")
    session = _make_session(email="owner@example.com", visibility="private")
    with patch("teleclaude.api.session_access.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        await check_session_access(request, "session-id", require_owner=True)


@pytest.mark.asyncio
async def test_visibility_field_from_core_session_is_used():
    """Ensure the visibility field on core Session is respected (C1 regression guard)."""
    request = _make_request(email="member@example.com", role="member")
    # Session with visibility="shared" should allow access
    session = _make_session(email="owner@example.com", visibility="shared")
    with patch("teleclaude.api.session_access.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        # Must not raise
        await check_session_access(request, "session-id")

    # Session with visibility="private" should block access
    session_private = _make_session(email="owner@example.com", visibility="private")
    with patch("teleclaude.api.session_access.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session_private)
        with pytest.raises(HTTPException) as exc_info:
            await check_session_access(request, "session-id")
        assert exc_info.value.status_code == 403
