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


# Named-constant identity comparisons replace literal string asserts for
# this file's lookup tests, per software-development/policy/testing
# "String Assertions — One Paradigm".
_REVIEW_FAMILY_PREFIX = "/next-review-"
_REVIEW_ARCH_PREFIX = "/next-review-architecture"
_REVIEW_BUILD_PREFIX = "/next-review-build"
_REVIEW_PLAN_PREFIX = "/next-review-plan"
_BUILD_PREFIX = "/next-build"
_SLUG_A = "slug-a"
_SLUG_OTHER = "other"
_WORKTREE_A = "trees/slug-a"
_WORKTREE_OTHER = "trees/other"
_AGENT_STATUS_IDLE = "idle"
_REVIEW_PLAN_SESSION_ID = "rev-plan"
_REVIEW_BUILD_SESSION_ID = "rev-build"
_REVIEW_SPECS_SESSION_ID = "rev-specs"
_OTHER_COMMAND_SESSION_ID = "other"
_SLUG_A_SESSION_1 = "sess-1"
_SLUG_A_SESSION_2 = "sess-2"
_SLUG_OTHER_SESSION = "sess-3"
_SLUG_A_LIVE_SESSIONS = [_SLUG_A_SESSION_1, _SLUG_A_SESSION_2]


@pytest.mark.asyncio
async def test_find_live_session_for_slug_matches_review_family_prefix() -> None:
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session(_REVIEW_PLAN_SESSION_ID, f"{_REVIEW_PLAN_PREFIX} {_SLUG_A}", _WORKTREE_A),
        _session(_OTHER_COMMAND_SESSION_ID, f"{_BUILD_PREFIX} {_SLUG_A}", _WORKTREE_A),
    ]

    session_id = await find_live_session_for_slug(db, _SLUG_A, _REVIEW_FAMILY_PREFIX)

    assert session_id == _REVIEW_PLAN_SESSION_ID


@pytest.mark.asyncio
async def test_find_live_session_with_status_for_slug_returns_idle_status() -> None:
    stopped_at = datetime(2026, 4, 13, tzinfo=UTC)
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session(
            _REVIEW_BUILD_SESSION_ID,
            f"{_REVIEW_BUILD_PREFIX} {_SLUG_A}",
            _WORKTREE_A,
            last_activity=stopped_at,
            last_message_sent_at=stopped_at,
            last_agent_stop_at=stopped_at,
        )
    ]

    session_id, status = await find_live_session_with_status_for_slug(db, _SLUG_A, _REVIEW_FAMILY_PREFIX)

    assert session_id == _REVIEW_BUILD_SESSION_ID
    assert status == _AGENT_STATUS_IDLE


@pytest.mark.asyncio
async def test_find_live_session_with_status_matches_none_subdir_for_empty_override() -> None:
    stopped_at = datetime(2026, 4, 13, tzinfo=UTC)
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session(
            _REVIEW_SPECS_SESSION_ID,
            f"{_REVIEW_ARCH_PREFIX} {_SLUG_A}",
            None,
            last_activity=stopped_at,
            last_message_sent_at=stopped_at,
            last_agent_stop_at=stopped_at,
        )
    ]

    session_id, status = await find_live_session_with_status_for_slug(
        db, _SLUG_A, _REVIEW_ARCH_PREFIX, subdir_override=""
    )

    assert session_id == _REVIEW_SPECS_SESSION_ID
    assert status == _AGENT_STATUS_IDLE


@pytest.mark.asyncio
async def test_find_all_live_sessions_for_slug_filters_by_subdir_only() -> None:
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session(_SLUG_A_SESSION_1, f"{_REVIEW_BUILD_PREFIX} {_SLUG_A}", _WORKTREE_A),
        _session(_SLUG_A_SESSION_2, f"{_BUILD_PREFIX} {_SLUG_A}", _WORKTREE_A),
        _session(_SLUG_OTHER_SESSION, f"{_BUILD_PREFIX} {_SLUG_OTHER}", _WORKTREE_OTHER),
    ]

    session_ids = await find_all_live_sessions_for_slug(db, _SLUG_A)

    assert session_ids == _SLUG_A_LIVE_SESSIONS


# Named-constant identity comparisons for prepare-worker lookup tests.
# Identity comparisons against named constants are sanctioned by the
# string-assertion policy; bare literal comparisons are not.
_PREPARE_TARGET_SLUG = "slug-a"
_PREPARE_TARGET_COMMAND = "next-review-architecture"
_PREPARE_EXACT_SESSION_ID = "prepare-rev-exact"
_PREPARE_COLLIDER_SESSION_ID = "prepare-rev-collider"
_PREPARE_WORKTREE_SESSION_ID = "prepare-rev-worktree"
_PREPARE_OTHER_COMMAND_SESSION_ID = "prepare-plan"


@pytest.mark.asyncio
async def test_find_live_prepare_worker_for_slug_exact_title_match() -> None:
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session(_PREPARE_EXACT_SESSION_ID, f"/{_PREPARE_TARGET_COMMAND} {_PREPARE_TARGET_SLUG}", subdir=None),
    ]

    session_id = await find_live_prepare_worker_for_slug(db, _PREPARE_TARGET_SLUG, _PREPARE_TARGET_COMMAND)

    assert session_id == _PREPARE_EXACT_SESSION_ID


@pytest.mark.asyncio
async def test_find_live_prepare_worker_for_slug_rejects_prefix_collider() -> None:
    """A longer slug that starts with the target as a prefix must not match."""
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session(
            _PREPARE_COLLIDER_SESSION_ID,
            f"/{_PREPARE_TARGET_COMMAND} {_PREPARE_TARGET_SLUG}-extra",
            subdir=None,
        ),
        _session(_PREPARE_EXACT_SESSION_ID, f"/{_PREPARE_TARGET_COMMAND} {_PREPARE_TARGET_SLUG}", subdir=None),
    ]

    session_id = await find_live_prepare_worker_for_slug(db, _PREPARE_TARGET_SLUG, _PREPARE_TARGET_COMMAND)

    assert session_id == _PREPARE_EXACT_SESSION_ID


@pytest.mark.asyncio
async def test_find_live_prepare_worker_for_slug_matches_with_trailing_context() -> None:
    """A title with whitespace boundary after the slug still matches."""
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session(
            _PREPARE_EXACT_SESSION_ID,
            f"/{_PREPARE_TARGET_COMMAND} {_PREPARE_TARGET_SLUG}  ADDITIONAL CONTEXT: x",
            subdir=None,
        ),
    ]

    session_id = await find_live_prepare_worker_for_slug(db, _PREPARE_TARGET_SLUG, _PREPARE_TARGET_COMMAND)

    assert session_id == _PREPARE_EXACT_SESSION_ID


@pytest.mark.asyncio
async def test_find_live_prepare_worker_for_slug_skips_non_root_subdir() -> None:
    """Sessions running inside a worktree (subdir set) are not prepare workers."""
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session(
            _PREPARE_WORKTREE_SESSION_ID,
            f"/{_PREPARE_TARGET_COMMAND} {_PREPARE_TARGET_SLUG}",
            subdir=f"trees/{_PREPARE_TARGET_SLUG}",
        ),
    ]

    session_id = await find_live_prepare_worker_for_slug(db, _PREPARE_TARGET_SLUG, _PREPARE_TARGET_COMMAND)

    assert session_id is None


@pytest.mark.asyncio
async def test_find_live_prepare_worker_for_slug_rejects_other_command() -> None:
    """Same slug+subdir but a different command family does not match."""
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session(_PREPARE_OTHER_COMMAND_SESSION_ID, f"/next-review-plan {_PREPARE_TARGET_SLUG}", subdir=None),
    ]

    session_id = await find_live_prepare_worker_for_slug(db, _PREPARE_TARGET_SLUG, _PREPARE_TARGET_COMMAND)

    assert session_id is None
