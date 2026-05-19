"""Tests for the prepare state machine entrypoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.core.next_machine.prepare import (
    _find_next_prepare_slug_db,
    _format_holder_prepare_instruction,
    next_prepare,
)
from teleclaude.core.next_machine.slug_resolution import HolderChildResolution, HolderResolutionReason
from teleclaude.core.todos_db import TodosDb

_PREPARE = "teleclaude.core.next_machine.prepare"


def _not_holder() -> HolderChildResolution:
    return HolderChildResolution(children=(), runnable=(), reason=HolderResolutionReason.NOT_HOLDER)


def _mock_todos_db(**overrides: object) -> AsyncMock:
    db = AsyncMock()
    db.slug_in_roadmap = AsyncMock(return_value=overrides.get("in_roadmap", True))
    db.add_to_roadmap = AsyncMock(return_value=True)
    db.read_state = AsyncMock(return_value=overrides.get("state", {"schema_version": 3, "lifecycle_phase": "draft"}))
    db.write_state = AsyncMock()
    db.artifact_exists = AsyncMock(return_value=False)
    db.artifact_digest = AsyncMock(return_value="")
    return db


@pytest.mark.asyncio
async def test_next_prepare_canonicalizes_cwd_from_worktree_path() -> None:
    db = AsyncMock()
    todos_db = _mock_todos_db()

    with (
        patch(f"{_PREPARE}.resolve_state_root", return_value="/repo") as mock_resolve,
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}.resolve_runnable_holder_children_db", return_value=_not_holder()),
        patch(f"{_PREPARE}._prepare_dispatch", return_value=(False, "dispatch")),
    ):
        await next_prepare(db, "my-slug", "/repo/trees/my-slug")

    mock_resolve.assert_called_once_with("/repo/trees/my-slug")


@pytest.mark.asyncio
async def test_next_prepare_no_active_work_emits_blocker_resolution(snapshot: SnapshotAssertion) -> None:
    db = AsyncMock()
    todos_db = _mock_todos_db()

    with (
        patch(f"{_PREPARE}.resolve_state_root", return_value="/repo"),
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}._find_next_prepare_slug_db", return_value=None),
        patch(f"{_PREPARE}.compose_agent_guidance", return_value="guidance"),
    ):
        result = await next_prepare(db, None, "/repo")

    assert result == snapshot


@pytest.mark.asyncio
async def test_next_prepare_holder_with_children_emits_child_prepare_commands(snapshot: SnapshotAssertion) -> None:
    db = AsyncMock()
    todos_db = _mock_todos_db()

    with (
        patch(f"{_PREPARE}.resolve_state_root", return_value="/repo"),
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(
            f"{_PREPARE}.resolve_runnable_holder_children_db",
            return_value=HolderChildResolution(
                children=("child-a", "child-b"),
                runnable=("child-a", "child-b"),
                reason=HolderResolutionReason.OK,
            ),
        ),
    ):
        result = await next_prepare(db, "holder", "/repo")

    assert result == snapshot


def test_format_holder_prepare_instruction_covers_non_runnable_reasons(snapshot: SnapshotAssertion) -> None:
    children = ("child-a",)
    outputs = {
        reason.value: _format_holder_prepare_instruction("holder", children, (), reason)
        for reason in (
            HolderResolutionReason.COMPLETE,
            HolderResolutionReason.ALL_PREPARED,
            HolderResolutionReason.DEPS_UNSATISFIED,
            HolderResolutionReason.CHILDREN_NOT_IN_ROADMAP,
            HolderResolutionReason.ITEM_NOT_READY,
        )
    }

    assert outputs == snapshot


@pytest.mark.asyncio
async def test_next_prepare_reads_stored_phase_and_returns_dispatch_instruction() -> None:
    db = AsyncMock()
    todos_db = _mock_todos_db(state={"schema_version": 3, "lifecycle_phase": "prd_drafting"})

    with (
        patch(f"{_PREPARE}.resolve_state_root", return_value="/repo"),
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}.resolve_runnable_holder_children_db", return_value=_not_holder()),
        patch(f"{_PREPARE}._prepare_dispatch", return_value=(False, "dispatch")),
    ):
        result = await next_prepare(db, "slug-a", "/repo")

    assert result == "dispatch"


@pytest.mark.asyncio
async def test_next_prepare_raises_on_missing_state() -> None:
    db = AsyncMock()
    todos_db = _mock_todos_db(state=None)
    todos_db.read_state = AsyncMock(return_value=None)

    with (
        patch(f"{_PREPARE}.resolve_state_root", return_value="/repo"),
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}.resolve_runnable_holder_children_db", return_value=_not_holder()),
        pytest.raises(RuntimeError, match="Contract violation: no state record"),
    ):
        await next_prepare(db, "stateless-slug", "/repo")


@pytest.mark.asyncio
async def test_next_prepare_adopts_draft_with_input_to_prd_drafting(todos_db: TodosDb) -> None:
    db = AsyncMock()
    await todos_db.add_to_roadmap("draft-item")
    await todos_db.write_state("draft-item", {"kind": "feature", "schema_version": 3, "lifecycle_phase": "draft"})
    await todos_db.write_artifact("draft-item", "input", "build a thing")
    captured_phase = None

    async def _dispatch(**kwargs):
        nonlocal captured_phase
        captured_phase = kwargs["phase"].value
        return (False, "dispatch")

    with (
        patch(f"{_PREPARE}.resolve_state_root", return_value="/repo"),
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}.resolve_runnable_holder_children_db", return_value=_not_holder()),
        patch(f"{_PREPARE}._prepare_dispatch", side_effect=_dispatch),
    ):
        result = await next_prepare(db, "draft-item", "/repo")

    persisted = await todos_db.read_state("draft-item")
    assert result == "dispatch"
    assert captured_phase == "prd_drafting"
    assert persisted is not None
    assert persisted["lifecycle_phase"] == "prd_drafting"


@pytest.mark.asyncio
async def test_find_next_prepare_slug_db_returns_first_prepare_lane_slug(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("ready")
    await todos_db.write_state("ready", {"schema_version": 3, "lifecycle_phase": "prepared"})
    await todos_db.add_to_roadmap("draft-item")
    await todos_db.write_state("draft-item", {"schema_version": 3, "lifecycle_phase": "draft"})

    result = await _find_next_prepare_slug_db(todos_db)

    assert result == "draft-item"
