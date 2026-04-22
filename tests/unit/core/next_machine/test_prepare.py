"""Tests for the prepare state machine entrypoint."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine.prepare import _find_next_prepare_slug_db, next_prepare
from teleclaude.core.todos_db import TodosDb

_PREPARE = "teleclaude.core.next_machine.prepare"


def _mock_todos_db(**overrides: object) -> AsyncMock:
    db = AsyncMock()
    db.slug_in_roadmap = AsyncMock(return_value=overrides.get("in_roadmap", True))
    db.add_to_roadmap = AsyncMock(return_value=True)
    db.read_state = AsyncMock(return_value=overrides.get("state", {"schema_version": 1, "phase": "pending"}))
    db.write_state = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_next_prepare_canonicalizes_cwd_from_worktree_path() -> None:
    """next_prepare must resolve worktree paths to the project root."""
    db = AsyncMock()
    todos_db = _mock_todos_db(state={"schema_version": 1, "phase": "in_progress"})

    with (
        patch(f"{_PREPARE}.resolve_canonical_project_root", return_value="/repo") as mock_resolve,
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
        patch(f"{_PREPARE}.resolve_canonical_project_root", return_value="/repo"),
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
        patch(f"{_PREPARE}.resolve_canonical_project_root", return_value="/repo"),
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}.resolve_holder_children_db", return_value=["child-a", "child-b"]),
    ):
        result = await next_prepare(db, "holder", "/repo")

    assert "SPLIT FINALIZE" in result


@pytest.mark.asyncio
async def test_next_prepare_reads_stored_phase_and_returns_dispatch_instruction() -> None:
    """next_prepare reads the stored lifecycle pointer and returns the dispatch result."""
    db = AsyncMock()
    todos_db = _mock_todos_db(state={"schema_version": 1, "phase": "in_progress", "lifecycle_phase": "triangulation"})

    with (
        patch(f"{_PREPARE}.resolve_canonical_project_root", return_value="/repo"),
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
            "schema_version": 1,
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
        patch(f"{_PREPARE}.resolve_canonical_project_root", return_value="/repo"),
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
        patch(f"{_PREPARE}.resolve_canonical_project_root", return_value="/repo"),
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}.resolve_holder_children_db", return_value=[]),
        pytest.raises(RuntimeError, match="Contract violation: no state record"),
    ):
        await next_prepare(db, "stateless-slug", "/repo")


@pytest.mark.asyncio
async def test_next_prepare_skips_explicit_draft_slug(todos_db: TodosDb) -> None:
    """Explicit prepare on a draft slug must bypass the prepare lifecycle."""
    db = AsyncMock()
    await todos_db.add_to_roadmap("draft-item")
    await todos_db.write_state("draft-item", {"kind": "draft", "schema_version": 1, "phase": "pending"})

    with (
        patch(f"{_PREPARE}.resolve_canonical_project_root", return_value="/repo"),
        patch(f"{_PREPARE}.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}.compose_agent_guidance", return_value="guidance"),
    ):
        result = await next_prepare(db, "draft-item", "/repo")

    assert result


@pytest.mark.asyncio
async def test_find_next_prepare_slug_db_skips_draft_todos(todos_db: TodosDb) -> None:
    """Draft todos must not be returned by _find_next_prepare_slug_db — they bypass the lifecycle."""
    await todos_db.add_to_roadmap("draft-item")
    await todos_db.write_state("draft-item", {"kind": "draft", "schema_version": 1, "phase": "pending"})

    result = await _find_next_prepare_slug_db(todos_db)

    assert result is None


@pytest.mark.asyncio
async def test_find_next_prepare_slug_db_returns_non_draft_when_draft_present(todos_db: TodosDb) -> None:
    """When a draft and a regular todo both exist, only the regular one is returned."""
    await todos_db.add_to_roadmap("draft-item")
    await todos_db.write_state("draft-item", {"kind": "draft", "schema_version": 1, "phase": "pending"})
    await todos_db.add_to_roadmap("real-item")
    await todos_db.write_state("real-item", {"kind": "todo", "schema_version": 1, "phase": "pending"})

    result = await _find_next_prepare_slug_db(todos_db)

    assert result == "real-item"
