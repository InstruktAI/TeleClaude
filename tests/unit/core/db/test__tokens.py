from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import text

from teleclaude.core import db_models
from teleclaude.core.db import Db
from teleclaude.core.models import Session

pytestmark = pytest.mark.asyncio


async def test_issue_session_token_persists_a_valid_token(
    db: Db, session_factory: Callable[..., Awaitable[Session]]
) -> None:
    await session_factory(session_id="sess-001")
    token = await db.issue_session_token("sess-001", "system:sess-001", "admin")

    record = await db.validate_session_token(token)

    assert record is not None
    assert record.session_id == "sess-001"
    assert record.principal == "system:sess-001"
    assert record.role == "admin"


async def test_validate_session_token_returns_none_after_revocation(
    db: Db, session_factory: Callable[..., Awaitable[Session]]
) -> None:
    await session_factory(session_id="sess-001")
    token = await db.issue_session_token("sess-001", "system:sess-001", "admin")

    await db.revoke_session_tokens("sess-001")

    assert await db.validate_session_token(token) is None


async def test_revoke_session_tokens_invalidates_all_active_tokens_for_a_session(
    db: Db, session_factory: Callable[..., Awaitable[Session]]
) -> None:
    await session_factory(session_id="sess-001")
    first = await db.issue_session_token("sess-001", "system:sess-001", "admin")
    second = await db.issue_session_token("sess-001", "system:sess-001", "admin")

    await db.revoke_session_tokens("sess-001")

    assert await db.validate_session_token(first) is None
    assert await db.validate_session_token(second) is None


async def test_cleanup_orphan_session_tokens_deletes_closed_and_missing_session_tokens(
    db: Db,
    session_factory: Callable[..., Awaitable[Session]],
) -> None:
    await session_factory(session_id="sess-active")
    await session_factory(session_id="sess-closed")
    await db.close_session("sess-closed")
    active_token = await db.issue_session_token("sess-active", "system:sess-active", "admin")
    closed_token = await db.issue_session_token("sess-closed", "system:sess-closed", "admin")
    missing_token = "token-missing"
    async with db._session() as session:
        await session.exec(text("PRAGMA foreign_keys = OFF"))  # guard: raw-sql - seeds legacy orphan token
        session.add(
            db_models.SessionToken(
                token=missing_token,
                session_id="sess-missing",
                principal="system:sess-missing",
                role="admin",
            )
        )
        await session.commit()
        await session.exec(text("PRAGMA foreign_keys = ON"))  # guard: raw-sql - restore default enforcement

    deleted = await db.cleanup_orphan_session_tokens()

    assert deleted == 2
    assert await db.validate_session_token(active_token) is not None
    assert await db.validate_session_token(closed_token) is None
    assert await db.validate_session_token(missing_token) is None
