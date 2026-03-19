from __future__ import annotations

import pytest

from teleclaude.core.db import Db

pytestmark = pytest.mark.asyncio


async def test_issue_session_token_persists_a_valid_token(db: Db) -> None:
    token = await db.issue_session_token("sess-001", "system:sess-001", "admin")

    record = await db.validate_session_token(token)

    assert record is not None
    assert record.session_id == "sess-001"
    assert record.principal == "system:sess-001"
    assert record.role == "admin"


async def test_validate_session_token_returns_none_after_revocation(db: Db) -> None:
    token = await db.issue_session_token("sess-001", "system:sess-001", "admin")

    await db.revoke_session_tokens("sess-001")

    assert await db.validate_session_token(token) is None


async def test_revoke_session_tokens_invalidates_all_active_tokens_for_a_session(db: Db) -> None:
    first = await db.issue_session_token("sess-001", "system:sess-001", "admin")
    second = await db.issue_session_token("sess-001", "system:sess-001", "admin")

    await db.revoke_session_tokens("sess-001")

    assert await db.validate_session_token(first) is None
    assert await db.validate_session_token(second) is None
