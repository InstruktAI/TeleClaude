"""Unit tests for shared next-machine runtime session lookup."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from teleclaude.core.next_machine.runtime.sessions import (
    find_all_live_sessions_for_slug,
    find_live_session_for_slug,
    find_live_session_with_status_for_slug,
)


def _session(
    session_id: str,
    title: str,
    subdir: str,
    *,
    last_activity: datetime | None = None,
    last_message_sent_at: datetime | None = None,
    last_agent_stop_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        session_id=session_id,
        title=title,
        subdir=subdir,
        last_activity=last_activity,
        last_message_sent_at=last_message_sent_at,
        last_agent_stop_at=last_agent_stop_at,
    )


@pytest.mark.asyncio
async def test_find_live_session_for_slug_matches_review_family_prefix() -> None:
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session("rev-plan", "/next-review-plan slug-a", "trees/slug-a"),
        _session("other", "/next-build slug-a", "trees/slug-a"),
    ]

    session_id = await find_live_session_for_slug(db, "slug-a", "/next-review-")

    assert session_id == "rev-plan"


@pytest.mark.asyncio
async def test_find_live_session_with_status_for_slug_returns_idle_status() -> None:
    stopped_at = datetime(2026, 4, 13, tzinfo=UTC)
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session(
            "rev-build",
            "/next-review-build slug-a",
            "trees/slug-a",
            last_activity=stopped_at,
            last_message_sent_at=stopped_at,
            last_agent_stop_at=stopped_at,
        )
    ]

    session_id, status = await find_live_session_with_status_for_slug(db, "slug-a", "/next-review-")

    assert session_id == "rev-build"
    assert status == "idle"


@pytest.mark.asyncio
async def test_find_all_live_sessions_for_slug_filters_by_subdir_only() -> None:
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session("sess-1", "/next-review-build slug-a", "trees/slug-a"),
        _session("sess-2", "/next-build slug-a", "trees/slug-a"),
        _session("sess-3", "/next-build other", "trees/other"),
    ]

    session_ids = await find_all_live_sessions_for_slug(db, "slug-a")

    assert session_ids == ["sess-1", "sess-2"]
