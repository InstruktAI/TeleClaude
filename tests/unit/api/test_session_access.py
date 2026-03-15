"""Characterization tests for session access checks."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api import session_access


def _make_request(email: str | None = None, role: str | None = None) -> SimpleNamespace:
    headers: dict[str, str] = {}
    if email is not None:
        headers["x-web-user-email"] = email
    if role is not None:
        headers["x-web-user-role"] = role
    return SimpleNamespace(headers=headers)


class TestSessionAccess:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_missing_identity_headers_bypass_all_checks(self) -> None:
        """Requests without web identity headers bypass session access enforcement."""
        request = _make_request()

        with patch("teleclaude.api.session_access.db") as db:
            db.get_session = AsyncMock()

            await session_access.check_session_access(request, "sess-1")

        db.get_session.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_shared_member_can_access_other_shared_session(self) -> None:
        """Members can access shared sessions they do not own."""
        request = _make_request(email="bob@example.com", role="member")
        session = SimpleNamespace(human_email="alice@example.com", visibility="shared")

        with patch("teleclaude.api.auth._get_cached_session", return_value=session):
            await session_access.check_session_access(request, "sess-2")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_require_owner_rejects_non_owner_even_when_session_is_shared(self) -> None:
        """Owner-only checks still reject non-owners for shared sessions."""
        request = _make_request(email="bob@example.com", role="member")
        session = SimpleNamespace(human_email="alice@example.com", visibility="shared")

        with patch("teleclaude.api.auth._get_cached_session", return_value=session):
            with pytest.raises(HTTPException) as exc_info:
                await session_access.check_session_access(request, "sess-3", require_owner=True)

        assert exc_info.value.status_code == 403
