"""Focused tests for the work state machine helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine._types import ItemPhase
from teleclaude.core.next_machine.work import _advance_prepared_to_build_started, _resolve_explicit_work_slug

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
