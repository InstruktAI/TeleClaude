"""Focused tests for the work state machine helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.core.next_machine._types import ItemPhase
from teleclaude.core.next_machine.work import (
    _advance_prepared_to_build_started,
    _resolve_explicit_work_slug,
    _resolve_work_slug,
)
from teleclaude.core.todos_db import TodosDb

_WORK = "teleclaude.core.next_machine.work"

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]


def _mock_todos_db(*, delivered: set[str] | None = None) -> AsyncMock:
    db = AsyncMock()
    db.load_deps = AsyncMock(return_value={})
    db.is_bug_todo = AsyncMock(return_value=False)
    db.slug_in_roadmap = AsyncMock(return_value=False)
    db.add_to_roadmap = AsyncMock(return_value=True)
    db.delivered_slugs = AsyncMock(return_value=delivered or set())
    return db


@pytest.mark.asyncio
async def test_resolve_explicit_work_slug_does_not_readd_delivered_slug() -> None:
    """Explicit work on a delivered slug must not recreate an active roadmap row."""
    todos_db = _mock_todos_db(delivered={"done-slug"})

    with (
        patch(f"{_WORK}._resolve_holder_slug", new=AsyncMock(return_value=("done-slug", None))),
        patch(f"{_WORK}._get_item_phase_db", new=AsyncMock(return_value=ItemPhase.DONE.value)),
    ):
        resolved, error = await _resolve_explicit_work_slug(todos_db, "done-slug", "done-slug", 0.0)

    assert resolved == ""
    assert error == "COMPLETE: Item 'done-slug' is already done."
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
