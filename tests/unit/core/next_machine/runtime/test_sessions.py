"""Unit tests for shared next-machine runtime session lookup."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from teleclaude.core.next_machine.runtime.sessions import (
    find_all_live_sessions_for_slug,
    find_live_prepare_worker_for_slug,
    find_live_session_for_slug,
    find_live_session_with_status_for_slug,
)


def _session(
    session_id: str,
    title: str,
    subdir: str | None,
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
async def test_find_live_session_with_status_matches_none_subdir_for_empty_override() -> None:
    stopped_at = datetime(2026, 4, 13, tzinfo=UTC)
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session(
            "rev-specs",
            "/next-review-architecture slug-a",
            None,
            last_activity=stopped_at,
            last_message_sent_at=stopped_at,
            last_agent_stop_at=stopped_at,
        )
    ]

    session_id, status = await find_live_session_with_status_for_slug(
        db, "slug-a", "/next-review-architecture", subdir_override=""
    )

    assert session_id == "rev-specs"
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


@pytest.mark.asyncio
async def test_find_live_prepare_worker_for_slug_exact_title_match() -> None:
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session("rev", "/next-review-architecture slug-a", subdir=None),
    ]

    session_id = await find_live_prepare_worker_for_slug(db, "slug-a", "next-review-architecture")

    assert session_id == "rev"


@pytest.mark.asyncio
async def test_find_live_prepare_worker_for_slug_rejects_prefix_collider() -> None:
    """A longer slug that starts with the target as a prefix must not match."""
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session("collider", "/next-review-architecture slug-a-extra", subdir=None),
        _session("exact", "/next-review-architecture slug-a", subdir=None),
    ]

    session_id = await find_live_prepare_worker_for_slug(db, "slug-a", "next-review-architecture")

    assert session_id == "exact"


@pytest.mark.asyncio
async def test_find_live_prepare_worker_for_slug_matches_with_trailing_context() -> None:
    """A title with whitespace boundary after the slug still matches."""
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session("rev", "/next-review-architecture slug-a  ADDITIONAL CONTEXT: x", subdir=None),
    ]

    session_id = await find_live_prepare_worker_for_slug(db, "slug-a", "next-review-architecture")

    assert session_id == "rev"


@pytest.mark.asyncio
async def test_find_live_prepare_worker_for_slug_skips_non_root_subdir() -> None:
    """Sessions running inside a worktree (subdir set) are not prepare workers."""
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session("worktree", "/next-review-architecture slug-a", subdir="trees/slug-a"),
    ]

    session_id = await find_live_prepare_worker_for_slug(db, "slug-a", "next-review-architecture")

    assert session_id is None


@pytest.mark.asyncio
async def test_find_live_prepare_worker_for_slug_rejects_other_command() -> None:
    """Same slug+subdir but a different command family does not match."""
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session("plan", "/next-review-plan slug-a", subdir=None),
    ]

    session_id = await find_live_prepare_worker_for_slug(db, "slug-a", "next-review-architecture")

    assert session_id is None
