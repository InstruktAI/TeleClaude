"""Integration smoke tests for consolidated drift routing."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.core.next_machine.prepare import next_prepare
from teleclaude.core.next_machine.stamps import apply_todo_stamp
from teleclaude.core.next_machine.work import next_work
from teleclaude.core.todos_db import TodosDb

_SLUG = "test-drift"
_HEAD_SHA = "origin-main-sha"
_DISPATCHED = "DISPATCHED"
_SESSION_TMP_RE = re.compile(r"(?:/[^/\s]+)+/teleclaude-pytest-[^/\s]+")
_PREPARED_STATE = {
    "lifecycle_phase": "prepared",
    "approvals": {"prd_approved": {"approved": True, "caller_session_id": "human-session"}},
    "artifacts": {
        "prd": {"digest": "prd-digest", "async_provenance_complete": True},
        "architecture": {"digest": "architecture-digest", "async_provenance_complete": True},
        "implementation_plan": {"digest": "plan-digest", "async_provenance_complete": True},
    },
    "architecture_review": {"verdict": "approve"},
    "plan_review": {"verdict": "approve"},
}

pytestmark = [pytest.mark.integration, pytest.mark.timeout(10)]


def _normalize_instruction_paths(text: str) -> str:
    return _SESSION_TMP_RE.sub("TMP", text)


async def _make_prepared_db(tmp_path: Path) -> TodosDb:
    database = TodosDb(str(tmp_path / ".teleclaude" / "todos.db"))
    await database.initialize()
    await database.add_to_roadmap(_SLUG)
    await database.write_state(_SLUG, _PREPARED_STATE)
    await database.write_artifact(_SLUG, "prd", "prd body")
    await database.write_artifact(_SLUG, "architecture", "architecture body")
    await database.write_artifact(_SLUG, "implementation-plan", "plan body")
    return database


async def test_cosmetic_drift_bounces_then_allows_work_after_review(
    tmp_path: Path,
    snapshot: SnapshotAssertion,
) -> None:
    database = await _make_prepared_db(tmp_path)
    try:
        with (
            patch("teleclaude.core.next_machine.work.get_todos_db", new=AsyncMock(return_value=database)),
            patch(
                "teleclaude.core.next_machine.work._normalize_next_work_cwd", new=AsyncMock(return_value=str(tmp_path))
            ),
            patch(
                "teleclaude.core.next_machine.work.derive_lifecycle_drift",
                new=AsyncMock(return_value={"prd": {"code": "pending"}}),
            ),
            patch("teleclaude.core.next_machine.work._ensure_worktree_ready", new=AsyncMock()) as ensure_worktree,
        ):
            bounced = await next_work(AsyncMock(), _SLUG, str(tmp_path))

        assert bounced == snapshot
        ensure_worktree.assert_not_awaited()

        with (
            patch("teleclaude.core.next_machine.stamps.get_todos_db", new=AsyncMock(return_value=database)),
            patch("teleclaude.core.next_machine.stamps.get_origin_main_sha", return_value=_HEAD_SHA),
            patch("teleclaude.core.next_machine.stamps.read_owned_snippet_digests", new=AsyncMock(return_value={})),
            patch(
                "teleclaude.core.next_machine.stamps.read_referenced_snippet_digests", new=AsyncMock(return_value={})
            ),
            patch("teleclaude.core.next_machine.stamps.read_dependency_set", new=AsyncMock(return_value=[])),
        ):
            await apply_todo_stamp(
                cwd=str(tmp_path),
                slug=_SLUG,
                stamp_type="drift_reviewed",
                value='{"artifact": "prd", "verdict": "cosmetic", "reason": "comments only"}',
                caller_session_id="worker",
            )

        with (
            patch("teleclaude.core.next_machine.work.get_todos_db", new=AsyncMock(return_value=database)),
            patch(
                "teleclaude.core.next_machine.work._normalize_next_work_cwd", new=AsyncMock(return_value=str(tmp_path))
            ),
            patch(
                "teleclaude.core.next_machine.work.derive_lifecycle_drift",
                new=AsyncMock(return_value={"prd": {"code": "fresh"}}),
            ),
            patch(
                "teleclaude.core.next_machine.work._ensure_worktree_ready",
                new=AsyncMock(return_value=(str(tmp_path / "trees" / _SLUG), None)),
            ),
            patch("teleclaude.core.next_machine.work.get_head_commit", return_value="head"),
            patch("teleclaude.core.next_machine.work._merge_origin_main_into_worktree", return_value=""),
            patch("teleclaude.core.next_machine.work._work_dispatch", new=AsyncMock(return_value=(False, _DISPATCHED))),
        ):
            proceeded = await next_work(AsyncMock(), _SLUG, str(tmp_path))

        assert proceeded == _DISPATCHED
    finally:
        await database.close()


async def test_substantive_plan_drift_routes_to_plan_drafting_without_prd_gate(
    tmp_path: Path,
    snapshot: SnapshotAssertion,
) -> None:
    database = await _make_prepared_db(tmp_path)
    try:
        with (
            patch("teleclaude.core.next_machine.stamps.get_todos_db", new=AsyncMock(return_value=database)),
            patch("teleclaude.core.next_machine.stamps.get_origin_main_sha", return_value=_HEAD_SHA),
            patch("teleclaude.core.next_machine.stamps.read_owned_snippet_digests", new=AsyncMock(return_value={})),
            patch(
                "teleclaude.core.next_machine.stamps.read_referenced_snippet_digests", new=AsyncMock(return_value={})
            ),
            patch("teleclaude.core.next_machine.stamps.read_dependency_set", new=AsyncMock(return_value=[])),
        ):
            state = await apply_todo_stamp(
                cwd=str(tmp_path),
                slug=_SLUG,
                stamp_type="drift_reviewed",
                value='{"artifact": "implementation-plan", "verdict": "substantive", "reason": "architecture changed"}',
                caller_session_id="worker",
            )

        assert state["plan_review"]["cleared_by_substantive_drift"] is True  # type: ignore[index]
        with (
            patch("teleclaude.core.next_machine.prepare.get_todos_db", new=AsyncMock(return_value=database)),
            patch("teleclaude.core.next_machine.prepare.resolve_state_root", return_value=tmp_path),
            patch("teleclaude.core.next_machine.lifecycle._session_principal", return_value="human:mo@example.com"),
        ):
            instruction = await next_prepare(AsyncMock(), _SLUG, str(tmp_path))

        assert _normalize_instruction_paths(instruction) == snapshot
    finally:
        await database.close()
