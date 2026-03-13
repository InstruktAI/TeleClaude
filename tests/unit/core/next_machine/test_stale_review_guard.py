"""Regression guard: stale review check skips when finalize is in progress.

Reproduces the bug where the state machine triggered an unnecessary review
round after finalize merged main into the worktree. The stale review guard
compared review_baseline_commit against HEAD, saw divergence from the
merge-main commits, and reset review to PENDING — even though finalize was
already ready/handed_off.

The fix hoists finalize_state read before the guard and skips the stale
check when finalize_status is "ready" or "handed_off".
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MODULE = "teleclaude.core.next_machine.work"

SLUG = "fix-something"
BASELINE_SHA = "aaa1111"
HEAD_SHA = "bbb2222"


def _make_state(*, finalize_status: str = "pending") -> dict[str, Any]:
    """Build a state dict with review approved and a stale baseline."""
    return {
        "schema_version": 1,
        "phase": "in_progress",
        "build": "complete",
        "review": "approved",
        "review_round": 1,
        "max_review_rounds": 3,
        "review_baseline_commit": BASELINE_SHA,
        "finalize": {"status": finalize_status},
        "kind": "bug",
    }


@dataclass
class _EnsureResult:
    created: bool = False
    prepared: bool = False
    prep_reason: str = "already_exists"


class _FakeAsyncLock:
    def locked(self) -> bool:
        return False

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        pass


def _patched_context(state: dict[str, Any], mark_phase_fn: Any) -> contextlib.ExitStack:
    """Return a context manager stacking all patches needed to reach the stale
    review guard in next_work."""
    stack = contextlib.ExitStack()
    targets = [
        ("resolve_canonical_project_root", lambda cwd: cwd),
        ("sweep_completed_groups", lambda cwd: None),
        ("load_roadmap_deps", lambda cwd: {}),
        ("is_bug_todo", lambda cwd, slug: True),
        ("get_stash_entries", lambda cwd: [],),
        ("check_file_has_content", lambda cwd, path: True),
        ("_ensure_todo_on_remote_main", lambda cwd, slug: (True, "ok")),
        ("_get_slug_single_flight_lock", AsyncMock(return_value=_FakeAsyncLock())),
        ("ensure_worktree_with_policy_async", AsyncMock(return_value=_EnsureResult())),
        ("has_uncommitted_changes", lambda cwd, slug: False),
        ("get_item_phase", lambda cwd, slug: "in_progress"),
        ("set_item_phase", lambda cwd, slug, phase: None),
        ("read_phase_state", lambda cwd, slug: state.copy()),
        ("_get_head_commit", lambda cwd: HEAD_SHA),
        ("_has_meaningful_diff", lambda cwd, baseline, head: True),
        ("mark_phase", mark_phase_fn),
        ("emit_branch_pushed", AsyncMock()),
        ("emit_deployment_started", AsyncMock()),
    ]
    for name, replacement in targets:
        stack.enter_context(patch(f"{MODULE}.{name}", replacement))
    return stack


@pytest.mark.asyncio
async def test_finalize_ready_skips_stale_review_reset() -> None:
    """When finalize.status=ready, review must NOT be reset to pending even if
    baseline != HEAD and meaningful diff exists.

    This is the exact regression: without the fix, finalize_state was read AFTER
    the stale check, so the guard had no visibility into finalize status and
    incorrectly invalidated the review.
    """
    state = _make_state(finalize_status="ready")
    mock_mark = MagicMock(return_value=state)

    with _patched_context(state, mock_mark):
        from teleclaude.core.next_machine.work import next_work

        result = await next_work(MagicMock(), SLUG, "/fake/cwd")

    # Should reach finalize handoff path, not stale review reset.
    assert "FINALIZE_STATE_INVALID" in result

    # Critical: mark_phase must NOT reset review to pending.
    for call in mock_mark.call_args_list:
        args = call[0]
        assert not (len(args) >= 4 and args[2] == "review" and args[3] == "pending"), (
            "Review was incorrectly reset to pending despite finalize being ready"
        )


@pytest.mark.asyncio
async def test_finalize_pending_allows_stale_review_reset() -> None:
    """Counter-test: when finalize.status=pending, the stale review guard SHOULD
    reset review to pending when baseline diverges with meaningful diff."""
    state = _make_state(finalize_status="pending")
    mark_calls: list[tuple[Any, ...]] = []

    def tracking_mark(*args: Any) -> dict[str, Any]:
        mark_calls.append(args)
        return state

    with _patched_context(state, tracking_mark):
        from teleclaude.core.next_machine.work import next_work

        await next_work(MagicMock(), SLUG, "/fake/cwd")

    review_resets = [
        c for c in mark_calls if len(c) >= 4 and c[2] == "review" and c[3] == "pending"
    ]
    assert len(review_resets) == 1, (
        f"Expected exactly one review reset to pending, got {len(review_resets)}"
    )


@pytest.mark.asyncio
async def test_finalize_handed_off_skips_stale_review_reset() -> None:
    """handed_off is equivalent to ready for the stale review bypass."""
    state = _make_state(finalize_status="handed_off")
    mock_mark = MagicMock(return_value=state)

    with _patched_context(state, mock_mark):
        from teleclaude.core.next_machine.work import next_work

        result = await next_work(MagicMock(), SLUG, "/fake/cwd")

    assert "FINALIZE_ALREADY_HANDED_OFF" in result

    for call in mock_mark.call_args_list:
        args = call[0]
        assert not (len(args) >= 4 and args[2] == "review" and args[3] == "pending"), (
            "Review was incorrectly reset to pending despite finalize being handed_off"
        )
