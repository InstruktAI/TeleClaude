# guard: no-companion
"""Tests for authoritative phase field clearing in loop dispatch paths.

Principle: the loop owns clearing. On dispatch return (keep_going=False),
the loop clears the authoritative field so primitives drive the next
invocation. BUILD_STARTED is the only exception (anchor during active build).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine._types import PreparePhase, WorkPhase
from teleclaude.core.next_machine.prepare import next_prepare
from teleclaude.core.next_machine.work import next_work
from teleclaude.core.todos_db import TodosDb
from teleclaude.types.todos import TodoState

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]


# ── Work loop dispatch: clear work_phase on return ─────────────────────


@pytest.mark.asyncio
async def test_work_loop_clears_work_phase_on_dispatch_return() -> None:
    """Work loop must clear work_phase on dispatch return for non-BUILD_STARTED phases."""
    mock_db = AsyncMock()
    mock_todos_db = AsyncMock()
    mock_todos_db.slug_in_roadmap = AsyncMock(return_value=True)
    mock_todos_db.delivered_slugs = AsyncMock(return_value=set())
    mock_todos_db.load_deps = AsyncMock(return_value={})
    mock_todos_db.is_bug_todo = AsyncMock(return_value=False)

    # State has work_phase set to a non-anchor value
    state_dict = TodoState.defaults().model_dump(exclude_none=True)
    state_dict["work_phase"] = WorkPhase.BUILD_COMPLETE.value
    state_dict["phase"] = "in_progress"
    mock_todos_db.read_state = AsyncMock(return_value=state_dict)

    written_states: list[dict] = []

    def capture_write(_cwd: str, _slug: str, st: dict) -> None:
        written_states.append(dict(st))

    with (
        patch("teleclaude.core.next_machine.work.resolve_canonical_project_root", return_value="/repo"),
        patch("teleclaude.core.todos_db.get_todos_db", return_value=mock_todos_db),
        patch("teleclaude.core.next_machine.work._resolve_explicit_work_slug", return_value=("my-slug", None)),
        patch("teleclaude.core.next_machine.work._validate_work_preconditions", return_value=None),
        patch("teleclaude.core.next_machine.work._ensure_worktree_ready", return_value=("/repo/trees/my-slug", None)),
        patch("teleclaude.core.next_machine.work._merge_origin_main_into_worktree", return_value=None),
        patch("teleclaude.core.next_machine.work.get_head_commit", return_value="abc123"),
        patch("teleclaude.core.next_machine.work._get_item_phase_db", return_value="in_progress"),
        patch("teleclaude.core.next_machine.work.derive_work_phase", return_value=WorkPhase.BUILD_COMPLETE),
        patch("teleclaude.core.next_machine.work._work_dispatch", return_value=(False, "dispatch instruction")),
        patch("teleclaude.core.next_machine.state_io.write_phase_state", capture_write),
    ):
        result = await next_work(mock_db, "my-slug", "/repo")

    assert result == "dispatch instruction"
    # work_phase must have been cleared
    assert len(written_states) == 1
    assert written_states[0].get("work_phase") == ""


@pytest.mark.asyncio
async def test_work_loop_preserves_work_phase_for_build_started() -> None:
    """Work loop must NOT clear work_phase when phase is BUILD_STARTED (the anchor)."""
    mock_db = AsyncMock()
    mock_todos_db = AsyncMock()
    mock_todos_db.slug_in_roadmap = AsyncMock(return_value=True)
    mock_todos_db.delivered_slugs = AsyncMock(return_value=set())
    mock_todos_db.load_deps = AsyncMock(return_value={})
    mock_todos_db.is_bug_todo = AsyncMock(return_value=False)

    state_dict = TodoState.defaults().model_dump(exclude_none=True)
    state_dict["work_phase"] = WorkPhase.BUILD_STARTED.value
    state_dict["phase"] = "in_progress"
    mock_todos_db.read_state = AsyncMock(return_value=state_dict)

    written_states: list[dict] = []

    def capture_write(_cwd: str, _slug: str, st: dict) -> None:
        written_states.append(dict(st))

    with (
        patch("teleclaude.core.next_machine.work.resolve_canonical_project_root", return_value="/repo"),
        patch("teleclaude.core.todos_db.get_todos_db", return_value=mock_todos_db),
        patch("teleclaude.core.next_machine.work._resolve_explicit_work_slug", return_value=("my-slug", None)),
        patch("teleclaude.core.next_machine.work._validate_work_preconditions", return_value=None),
        patch("teleclaude.core.next_machine.work._ensure_worktree_ready", return_value=("/repo/trees/my-slug", None)),
        patch("teleclaude.core.next_machine.work._merge_origin_main_into_worktree", return_value=None),
        patch("teleclaude.core.next_machine.work.get_head_commit", return_value="abc123"),
        patch("teleclaude.core.next_machine.work._get_item_phase_db", return_value="in_progress"),
        patch("teleclaude.core.next_machine.work.derive_work_phase", return_value=WorkPhase.BUILD_STARTED),
        patch("teleclaude.core.next_machine.work._work_dispatch", return_value=(False, "dispatch instruction")),
        patch("teleclaude.core.next_machine.state_io.write_phase_state", capture_write),
    ):
        await next_work(mock_db, "my-slug", "/repo")

    # work_phase should NOT be cleared for BUILD_STARTED
    assert len(written_states) == 0


# ── Prepare loop dispatch: clear prepare_phase on return ───────────────


@pytest.mark.asyncio
async def test_prepare_loop_clears_prepare_phase_on_dispatch_return(todos_db: TodosDb) -> None:
    """Prepare loop must clear prepare_phase on dispatch return."""
    await todos_db.add_to_roadmap("prep-slug")
    state_dict = TodoState.defaults().model_dump(exclude_none=True)
    state_dict["prepare_phase"] = PreparePhase.REQUIREMENTS_REVIEW.value
    await todos_db.write_state("prep-slug", state_dict)

    written_states: list[dict] = []

    def capture_write(_cwd: str, _slug: str, st: dict) -> None:
        written_states.append(dict(st))

    mock_db = AsyncMock()
    with (
        patch("teleclaude.core.next_machine.prepare.resolve_canonical_project_root", return_value="/repo"),
        patch("teleclaude.core.todos_db.get_todos_db", return_value=todos_db),
        patch("teleclaude.core.next_machine.slug_resolution.resolve_holder_children_db", return_value=[]),
        patch("teleclaude.core.next_machine.prepare.check_artifact_staleness_db", return_value=[]),
        patch(
            "teleclaude.core.next_machine.prepare.derive_prepare_phase", return_value=PreparePhase.REQUIREMENTS_REVIEW
        ),
        patch("teleclaude.core.next_machine.prepare._prepare_dispatch", return_value=(False, "dispatch instruction")),
        patch("teleclaude.core.next_machine.state_io.write_phase_state", capture_write),
    ):
        result = await next_prepare(mock_db, "prep-slug", "/repo")

    assert result == "dispatch instruction"
    assert len(written_states) == 1
    assert written_states[0].get("prepare_phase") == ""
