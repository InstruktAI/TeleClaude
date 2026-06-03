"""Focused tests for the work state machine helpers."""

from __future__ import annotations

from unittest.mock import ANY, AsyncMock, Mock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.core.next_machine._types import ItemPhase
from teleclaude.core.next_machine.work import (
    _advance_prepared_to_build_started,
    _check_work_entry_drift,
    _resolve_explicit_work_slug,
    _resolve_work_slug,
    next_work,
)
from teleclaude.core.todos_db import TodosDb

_WORK = "teleclaude.core.next_machine.work"

pytestmark = pytest.mark.unit


def _mock_todos_db(*, delivered: set[str] | None = None) -> AsyncMock:
    db = AsyncMock()
    db.load_deps = AsyncMock(return_value={})
    db.is_bug_todo = AsyncMock(return_value=False)
    db.slug_in_roadmap = AsyncMock(return_value=False)
    db.add_to_roadmap = AsyncMock(return_value=True)
    db.delivered_slugs = AsyncMock(return_value=delivered or set())
    return db


@pytest.mark.asyncio
async def test_resolve_explicit_work_slug_does_not_readd_delivered_slug(snapshot: SnapshotAssertion) -> None:
    """Explicit work on a delivered slug must not recreate an active roadmap row."""
    todos_db = _mock_todos_db(delivered={"done-slug"})

    with (
        patch(f"{_WORK}._resolve_holder_slug", new=AsyncMock(return_value=("done-slug", None))),
        patch(f"{_WORK}._get_item_phase_db", new=AsyncMock(return_value=ItemPhase.DONE.value)),
    ):
        resolved, error = await _resolve_explicit_work_slug(todos_db, "done-slug", "done-slug", 0.0)

    assert resolved == ""
    assert error == snapshot
    todos_db.add_to_roadmap.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_explicit_work_slug_still_auto_adds_missing_active_slug() -> None:
    """Explicit work should still add non-delivered roadmap items when missing."""
    todos_db = _mock_todos_db()

    with (
        patch(f"{_WORK}._resolve_holder_slug", new=AsyncMock(return_value=("ready-slug", None))),
        patch(f"{_WORK}._get_item_phase_db", new=AsyncMock(return_value=ItemPhase.PENDING.value)),
    ):
        resolved, error = await _resolve_explicit_work_slug(todos_db, "ready-slug", "ready-slug", 0.0)

    assert resolved == "ready-slug"
    assert error is None
    todos_db.add_to_roadmap.assert_awaited_once_with("ready-slug")


@pytest.mark.asyncio
async def test_resolve_explicit_holder_emits_child_work_commands(
    todos_db: TodosDb,
    snapshot: SnapshotAssertion,
) -> None:
    """Explicit holder work resolves to child commands instead of working the holder."""
    await todos_db.add_to_roadmap("holder")
    await todos_db.add_to_roadmap("child-a", group_slug="holder")
    await todos_db.write_state("child-a", {"schema_version": 3, "lifecycle_phase": "prepared"})

    resolved, instruction = await _resolve_explicit_work_slug(todos_db, "holder", "holder", 0.0)

    assert resolved == ""
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_no_slug_work_skips_holder_without_runnable_children(todos_db: TodosDb) -> None:
    """Automatic work pickup must not starve later ready work behind a blocked holder."""
    await todos_db.add_to_roadmap("holder")
    await todos_db.add_to_roadmap("child-a", group_slug="holder")
    await todos_db.write_state("child-a", {"schema_version": 3, "lifecycle_phase": "draft"})
    await todos_db.add_to_roadmap("later-ready")
    await todos_db.write_state("later-ready", {"schema_version": 3, "lifecycle_phase": "prepared"})

    resolved, instruction = await _resolve_work_slug(todos_db, None, "<auto>")

    assert resolved == "later-ready"
    assert instruction is None


@pytest.mark.asyncio
async def test_explicit_work_accepts_complete_holder_dependency(todos_db: TodosDb) -> None:
    """A dependency on a holder is satisfied once every holder child has delivered."""
    await todos_db.add_to_roadmap("holder")
    await todos_db.add_to_roadmap("child-a", group_slug="holder")
    await todos_db.write_state("child-a", {"schema_version": 3, "lifecycle_phase": "finalize_ready"})
    await todos_db.deliver("child-a")
    await todos_db.add_to_roadmap("ready-after-holder")
    await todos_db.write_state("ready-after-holder", {"schema_version": 3, "lifecycle_phase": "prepared"})
    await todos_db.set_deps("ready-after-holder", after=["holder"])

    resolved, error = await _resolve_explicit_work_slug(todos_db, "ready-after-holder", "ready-after-holder", 0.0)

    assert resolved == "ready-after-holder"
    assert error is None


@pytest.mark.asyncio
async def test_prepared_handoff_persists_build_started(monkeypatch: pytest.MonkeyPatch) -> None:
    """First work entry writes the build_started lifecycle pointer durably."""
    todos_db = AsyncMock()
    state = {"lifecycle_phase": "prepared"}
    monkeypatch.setattr("teleclaude.core.next_machine.lifecycle.get_head_commit", lambda _cwd: "base-sha")

    await _advance_prepared_to_build_started(todos_db, "my-slug", state, "/repo/trees/my-slug")

    todos_db.write_state.assert_awaited_once()
    _, payload = todos_db.write_state.await_args.args
    assert payload["lifecycle_phase"] == "build_started"
    assert payload["build_start_base_sha"] == "base-sha"


@pytest.mark.asyncio
async def test_next_work_bounces_pending_drift_before_worktree_setup(snapshot: SnapshotAssertion) -> None:
    """Pending prepare drift must stop work before any worktree side effects."""
    todos_db = AsyncMock()
    todos_db.read_state = AsyncMock(return_value={"lifecycle_phase": "prepared"})
    todos_db.write_state = AsyncMock()
    ensure_worktree = AsyncMock(return_value=("/repo/trees/my-slug", None))
    log_phase = Mock()

    with (
        patch(f"{_WORK}.get_todos_db", new=AsyncMock(return_value=todos_db)),
        patch(f"{_WORK}._normalize_next_work_cwd", new=AsyncMock(return_value="/repo")),
        patch(f"{_WORK}._resolve_work_slug", new=AsyncMock(return_value=("my-slug", None))),
        patch(f"{_WORK}._validate_work_preconditions", new=AsyncMock(return_value=None)),
        patch(f"{_WORK}.derive_lifecycle_drift", new=AsyncMock(return_value={"prd": {"code": "pending"}})),
        patch(f"{_WORK}._ensure_worktree_ready", new=ensure_worktree),
        patch(f"{_WORK}._log_next_work_phase", new=log_phase),
    ):
        instruction = await next_work(AsyncMock(), "my-slug", "/repo")

    assert instruction == snapshot
    ensure_worktree.assert_not_awaited()
    log_phase.assert_any_call("my-slug", "drift_check", ANY, "bounce", "prd:pending")


@pytest.mark.asyncio
async def test_work_entry_drift_allows_pending_drift_during_in_flight_work() -> None:
    """In-flight work re-entry does not bounce on unclassified pending drift."""
    todos_db = AsyncMock()
    todos_db.read_state = AsyncMock(return_value={"lifecycle_phase": "build_complete"})
    todos_db.write_state = AsyncMock()

    with (
        patch(f"{_WORK}.derive_lifecycle_drift", new=AsyncMock(return_value={"prd": {"code": "pending"}})),
        patch(f"{_WORK}._log_next_work_phase"),
    ):
        instruction = await _check_work_entry_drift(todos_db, "my-slug", "/repo", "my-slug")

    assert instruction is None


@pytest.mark.asyncio
async def test_work_entry_drift_bounces_substantive_drift_during_in_flight_work() -> None:
    """Confirmed substantive drift still blocks in-flight work re-entry."""
    todos_db = AsyncMock()
    todos_db.read_state = AsyncMock(return_value={"lifecycle_phase": "build_complete"})
    todos_db.write_state = AsyncMock()

    with (
        patch(f"{_WORK}.derive_lifecycle_drift", new=AsyncMock(return_value={"prd": {"code": "substantive"}})),
        patch(f"{_WORK}._log_next_work_phase"),
    ):
        instruction = await _check_work_entry_drift(todos_db, "my-slug", "/repo", "my-slug")

    assert instruction is not None


@pytest.mark.asyncio
async def test_next_work_proceeds_after_fresh_drift_check() -> None:
    """Fresh prepare drift lets work continue into the normal work dispatch flow."""
    todos_db = AsyncMock()
    todos_db.read_state = AsyncMock(return_value={"lifecycle_phase": "build_started"})
    todos_db.write_state = AsyncMock()
    ensure_worktree = AsyncMock(return_value=("/repo/trees/my-slug", None))
    dispatch = AsyncMock(return_value=(False, "DISPATCHED"))
    log_phase = Mock()

    with (
        patch(f"{_WORK}.get_todos_db", new=AsyncMock(return_value=todos_db)),
        patch(f"{_WORK}._normalize_next_work_cwd", new=AsyncMock(return_value="/repo")),
        patch(f"{_WORK}._resolve_work_slug", new=AsyncMock(return_value=("my-slug", None))),
        patch(f"{_WORK}._validate_work_preconditions", new=AsyncMock(return_value=None)),
        patch(f"{_WORK}.derive_lifecycle_drift", new=AsyncMock(return_value={"prd": {"code": "fresh"}})),
        patch(f"{_WORK}._ensure_worktree_ready", new=ensure_worktree),
        patch(f"{_WORK}.get_head_commit", return_value="head"),
        patch(f"{_WORK}._merge_origin_main_into_worktree", return_value=""),
        patch(f"{_WORK}._get_item_phase_db", new=AsyncMock(return_value=ItemPhase.IN_PROGRESS.value)),
        patch(f"{_WORK}._work_dispatch", new=dispatch),
        patch(f"{_WORK}._log_next_work_phase", new=log_phase),
    ):
        instruction = await next_work(AsyncMock(), "my-slug", "/repo")

    assert instruction == "DISPATCHED"
    ensure_worktree.assert_awaited_once()
    dispatch.assert_awaited_once()
    log_phase.assert_any_call("my-slug", "drift_check", ANY, "proceed", "fresh")
