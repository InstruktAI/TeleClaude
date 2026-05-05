"""Tests for the prepare state machine entrypoint."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine.prepare import (
    _find_next_prepare_slug_db,
    detect_unsatisfied_phase,
    next_prepare,
)
from teleclaude.core.todos_db import TodosDb

_PREPARE = "teleclaude.core.next_machine.prepare"


def _mock_todos_db(**overrides: object) -> AsyncMock:
    db = AsyncMock()
    db.slug_in_roadmap = AsyncMock(return_value=overrides.get("in_roadmap", True))
    db.add_to_roadmap = AsyncMock(return_value=True)
    db.read_state = AsyncMock(
        return_value=overrides.get(
            "state", {"schema_version": 2, "phase": "pending", "lifecycle_phase": "input_assessment"}
        )
    )
    db.write_state = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_next_prepare_canonicalizes_cwd_from_worktree_path() -> None:
    """next_prepare must resolve worktree paths to the project root."""
    db = AsyncMock()
    todos_db = _mock_todos_db(
        state={"schema_version": 2, "phase": "in_progress", "lifecycle_phase": "input_assessment"}
    )

    with (
        patch(f"{_PREPARE}.resolve_state_root", return_value="/repo") as mock_resolve,
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}.resolve_holder_children_db", return_value=[]),
        patch(f"{_PREPARE}._prepare_dispatch", return_value=(False, "dispatch")),
    ):
        await next_prepare(db, "my-slug", "/repo/trees/my-slug")

    mock_resolve.assert_called_once_with("/repo/trees/my-slug")


@pytest.mark.asyncio
async def test_next_prepare_dispatches_no_active_work_to_prepare_draft() -> None:
    """When no slug needs preparation, next_prepare returns a prepare-draft dispatch."""
    db = AsyncMock()
    todos_db = _mock_todos_db()

    with (
        patch(f"{_PREPARE}.resolve_state_root", return_value="/repo"),
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}._find_next_prepare_slug_db", return_value=None),
        patch(f"{_PREPARE}.compose_agent_guidance", return_value="guidance"),
    ):
        result = await next_prepare(db, None, "/repo")

    assert result


@pytest.mark.asyncio
async def test_next_prepare_returns_container_message_when_holder_has_children() -> None:
    """Holder slugs with children return a split-finalize message instead of preparing."""
    db = AsyncMock()
    todos_db = _mock_todos_db()

    with (
        patch(f"{_PREPARE}.resolve_state_root", return_value="/repo"),
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}.resolve_holder_children_db", return_value=["child-a", "child-b"]),
    ):
        result = await next_prepare(db, "holder", "/repo")

    assert "SPLIT FINALIZE" in result


@pytest.mark.asyncio
async def test_next_prepare_reads_stored_phase_and_returns_dispatch_instruction() -> None:
    """next_prepare reads the stored lifecycle pointer and returns the dispatch result."""
    db = AsyncMock()
    todos_db = _mock_todos_db(state={"schema_version": 2, "phase": "in_progress", "lifecycle_phase": "triangulation"})

    with (
        patch(f"{_PREPARE}.resolve_state_root", return_value="/repo"),
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}.resolve_holder_children_db", return_value=[]),
        patch(f"{_PREPARE}._prepare_dispatch", return_value=(False, "dispatch")),
    ):
        result = await next_prepare(db, "slug-a", "/repo")

    assert result == "dispatch"


@pytest.mark.asyncio
async def test_next_prepare_keeps_marked_phase_even_when_later_artifacts_exist(tmp_path: Path) -> None:
    """A rewound lifecycle phase must not be overwritten by later preserved artifact history."""
    db = AsyncMock()
    todos_db = TodosDb(str(tmp_path / "todos.db"))
    await todos_db.initialize()
    await todos_db.add_to_roadmap("slug-a")
    await todos_db.write_state(
        "slug-a",
        {
            "schema_version": 2,
            "phase": "in_progress",
            "lifecycle_phase": "test_spec_build",
            "requirements_review": {"verdict": "approve"},
            "artifacts": {
                "implementation_plan": {
                    "digest": "00440fc00b7751680bc43b4dcf477b98b1259492deb4f890173cbac36bc4ed6a",
                    "produced_at": "",
                }
            },
        },
    )
    await todos_db.write_artifact("slug-a", "implementation-plan", "plan content")
    captured_phase = None

    async def _dispatch(**kwargs):
        nonlocal captured_phase
        captured_phase = kwargs["phase"].value
        return (False, "dispatch")

    with (
        patch(f"{_PREPARE}.resolve_state_root", return_value="/repo"),
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}.resolve_holder_children_db", return_value=[]),
        patch(f"{_PREPARE}._prepare_dispatch", side_effect=_dispatch),
    ):
        result = await next_prepare(db, "slug-a", "/repo")

    persisted = await todos_db.read_state("slug-a")
    assert result == "dispatch"
    assert captured_phase == "test_spec_build"
    assert persisted is not None
    assert persisted["lifecycle_phase"] == "test_spec_build"


@pytest.mark.asyncio
async def test_next_prepare_raises_on_missing_state() -> None:
    """A slug with no state record is a contract violation — must raise, not return PREPARED."""
    db = AsyncMock()
    todos_db = _mock_todos_db(state=None)
    todos_db.read_state = AsyncMock(return_value=None)

    with (
        patch(f"{_PREPARE}.resolve_state_root", return_value="/repo"),
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}.resolve_holder_children_db", return_value=[]),
        pytest.raises(RuntimeError, match="Contract violation: no state record"),
    ):
        await next_prepare(db, "stateless-slug", "/repo")


@pytest.mark.asyncio
async def test_next_prepare_adopts_explicit_draft_slug_into_prepare_lane(todos_db: TodosDb) -> None:
    """Explicit prepare on a draft slug adopts the current artifact state into the prepare lane."""
    db = AsyncMock()
    await todos_db.add_to_roadmap("draft-item")
    await todos_db.write_state("draft-item", {"kind": "draft", "schema_version": 1, "phase": "pending"})
    captured_phase = None

    async def _dispatch(**kwargs):
        nonlocal captured_phase
        captured_phase = kwargs["phase"].value
        return (False, "dispatch")

    with (
        patch(f"{_PREPARE}.resolve_state_root", return_value="/repo"),
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}.resolve_holder_children_db", return_value=[]),
        patch(f"{_PREPARE}._prepare_dispatch", side_effect=_dispatch),
    ):
        result = await next_prepare(db, "draft-item", "/repo")

    persisted = await todos_db.read_state("draft-item")
    assert result == "dispatch"
    assert captured_phase == "input_assessment"
    assert persisted is not None
    assert persisted["lifecycle_phase"] == "input_assessment"


@pytest.mark.asyncio
async def test_next_prepare_adopts_no_input_requirements_directly_to_test_spec_build(todos_db: TodosDb) -> None:
    """Draft handoff without input but with requirements must skip requirements_review."""
    db = AsyncMock()
    await todos_db.add_to_roadmap("draft-item")
    await todos_db.write_state("draft-item", {"kind": "draft", "schema_version": 1, "phase": "pending"})
    await todos_db.write_artifact("draft-item", "requirements", "# Requirements")
    captured_phase = None

    async def _dispatch(**kwargs):
        nonlocal captured_phase
        captured_phase = kwargs["phase"].value
        return (False, "dispatch")

    with (
        patch(f"{_PREPARE}.resolve_state_root", return_value="/repo"),
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}.resolve_holder_children_db", return_value=[]),
        patch(f"{_PREPARE}._prepare_dispatch", side_effect=_dispatch),
    ):
        result = await next_prepare(db, "draft-item", "/repo")

    persisted = await todos_db.read_state("draft-item")
    assert result == "dispatch"
    assert captured_phase == "test_spec_build"
    assert persisted is not None
    assert persisted["lifecycle_phase"] == "test_spec_build"


@pytest.mark.asyncio
async def test_find_next_prepare_slug_db_skips_draft_todos(todos_db: TodosDb) -> None:
    """Draft todos must not be returned by _find_next_prepare_slug_db — they bypass the lifecycle."""
    await todos_db.add_to_roadmap("draft-item")
    await todos_db.write_state("draft-item", {"kind": "draft", "schema_version": 1, "phase": "pending"})

    result = await _find_next_prepare_slug_db(todos_db)

    assert result is None


@pytest.mark.asyncio
async def test_find_next_prepare_slug_db_skips_lifecycle_draft_rows(todos_db: TodosDb) -> None:
    """Lifecycle draft rows must bypass prepare even when kind is not explicitly draft."""
    await todos_db.add_to_roadmap("draft-item")
    await todos_db.write_state(
        "draft-item",
        {"kind": "todo", "schema_version": 2, "phase": "pending", "lifecycle_phase": "draft"},
    )

    result = await _find_next_prepare_slug_db(todos_db)

    assert result is None


@pytest.mark.asyncio
async def test_find_next_prepare_slug_db_returns_non_draft_when_draft_present(todos_db: TodosDb) -> None:
    """When a draft and a regular todo both exist, only the regular one is returned."""
    await todos_db.add_to_roadmap("draft-item")
    await todos_db.write_state("draft-item", {"kind": "draft", "schema_version": 1, "phase": "pending"})
    await todos_db.add_to_roadmap("real-item")
    await todos_db.write_state(
        "real-item",
        {"kind": "todo", "schema_version": 2, "phase": "pending", "lifecycle_phase": "input_assessment"},
    )

    result = await _find_next_prepare_slug_db(todos_db)

    assert result == "real-item"


# ---------------------------------------------------------------------------
# Phase satisfaction walk: detect the earliest phase whose digest binding is
# stale and rewind lifecycle_phase to that phase.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_satisfaction_walk_returns_none_when_all_digests_match(todos_db: TodosDb) -> None:
    """When every review's approved_digest matches the current artifact digest, no rewind is needed."""
    await todos_db.add_to_roadmap("all-matched")
    await todos_db.write_artifact("all-matched", "requirements", "# R\n")
    await todos_db.write_artifact("all-matched", "test-specs", "# S\n")
    await todos_db.write_artifact("all-matched", "implementation-plan", "# P\n")
    requirements_digest = await todos_db.artifact_digest("all-matched", "requirements")
    test_specs_digest = await todos_db.artifact_digest("all-matched", "test-specs")
    plan_digest = await todos_db.artifact_digest("all-matched", "implementation-plan")
    await todos_db.write_state(
        "all-matched",
        {
            "schema_version": 2,
            "lifecycle_phase": "prepared",
            "artifacts": {
                "requirements": {"digest": requirements_digest, "produced_at": "2026-01-01T00:00:00+00:00"},
                "test_specs": {
                    "digest": test_specs_digest,
                    "produced_at": "2026-01-01T00:00:00+00:00",
                    "upstream_digests": {"requirements": requirements_digest},
                },
                "implementation_plan": {
                    "digest": plan_digest,
                    "produced_at": "2026-01-01T00:00:00+00:00",
                    "upstream_digests": {"requirements": requirements_digest, "test_specs": test_specs_digest},
                },
            },
            "requirements_review": {"verdict": "approve", "approved_digest": requirements_digest},
            "test_spec_review": {"verdict": "approve", "approved_digest": test_specs_digest},
            "plan_review": {"verdict": "approve", "approved_digest": plan_digest},
        },
    )
    state = await todos_db.read_state("all-matched")
    assert state is not None

    rewind_to = await detect_unsatisfied_phase(todos_db, "all-matched", state)

    assert rewind_to is None


@pytest.mark.asyncio
async def test_satisfaction_walk_rewinds_to_requirements_review_when_requirements_digest_changed(
    todos_db: TodosDb,
) -> None:
    """When requirements digest no longer matches the approved one, walk returns requirements_review."""
    await todos_db.add_to_roadmap("req-changed")
    await todos_db.write_artifact("req-changed", "requirements", "# R v1\n")
    old_digest = await todos_db.artifact_digest("req-changed", "requirements")
    await todos_db.write_artifact("req-changed", "requirements", "# R v2\n")
    new_digest = await todos_db.artifact_digest("req-changed", "requirements")
    assert old_digest != new_digest

    await todos_db.write_state(
        "req-changed",
        {
            "schema_version": 2,
            "lifecycle_phase": "prepared",
            "artifacts": {
                "requirements": {"digest": old_digest, "produced_at": "2026-01-01T00:00:00+00:00"},
            },
            "requirements_review": {"verdict": "approve", "approved_digest": old_digest},
        },
    )
    state = await todos_db.read_state("req-changed")
    assert state is not None

    rewind_to = await detect_unsatisfied_phase(todos_db, "req-changed", state)

    assert rewind_to is not None
    assert rewind_to.value == "requirements_review"


@pytest.mark.asyncio
async def test_satisfaction_walk_rewinds_to_test_spec_build_when_upstream_changed(
    todos_db: TodosDb,
) -> None:
    """When requirements digest changes after specs were built, the walk rewinds to test_spec_build."""
    await todos_db.add_to_roadmap("upstream-changed")
    await todos_db.write_artifact("upstream-changed", "requirements", "# R\n")
    requirements_digest = await todos_db.artifact_digest("upstream-changed", "requirements")
    await todos_db.write_artifact("upstream-changed", "test-specs", "# S\n")
    test_specs_digest = await todos_db.artifact_digest("upstream-changed", "test-specs")

    await todos_db.write_artifact("upstream-changed", "requirements", "# R v2\n")
    new_requirements_digest = await todos_db.artifact_digest("upstream-changed", "requirements")
    assert new_requirements_digest != requirements_digest

    await todos_db.write_state(
        "upstream-changed",
        {
            "schema_version": 2,
            "lifecycle_phase": "prepared",
            "artifacts": {
                "requirements": {"digest": new_requirements_digest, "produced_at": "2026-01-01T00:00:00+00:00"},
                "test_specs": {
                    "digest": test_specs_digest,
                    "produced_at": "2026-01-01T00:00:00+00:00",
                    "upstream_digests": {"requirements": requirements_digest},
                },
            },
            "requirements_review": {"verdict": "approve", "approved_digest": new_requirements_digest},
            "test_spec_review": {"verdict": "approve", "approved_digest": test_specs_digest},
        },
    )
    state = await todos_db.read_state("upstream-changed")
    assert state is not None

    rewind_to = await detect_unsatisfied_phase(todos_db, "upstream-changed", state)

    assert rewind_to is not None
    assert rewind_to.value == "test_spec_build"
