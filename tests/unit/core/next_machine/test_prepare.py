"""Tests for the prepare state machine entrypoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine.prepare import _find_next_prepare_slug_db, next_prepare
from teleclaude.core.todos_db import TodosDb

_PREPARE = "teleclaude.core.next_machine.prepare"
_SLUG_RES = "teleclaude.core.next_machine.slug_resolution"


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
        patch("teleclaude.core.todos_db.get_todos_db", return_value=todos_db),
        patch(f"{_SLUG_RES}.resolve_holder_children_db", return_value=[]),
        patch(f"{_PREPARE}.check_artifact_staleness_db", return_value=[]),
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
        patch("teleclaude.core.todos_db.get_todos_db", return_value=todos_db),
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
        patch("teleclaude.core.todos_db.get_todos_db", return_value=todos_db),
        patch(f"{_SLUG_RES}.resolve_holder_children_db", return_value=["child-a", "child-b"]),
    ):
        result = await next_prepare(db, "holder", "/repo")

    assert "SPLIT FINALIZE" in result


@pytest.mark.asyncio
async def test_next_prepare_uses_derived_phase_and_returns_dispatch_instruction() -> None:
    """next_prepare derives the phase and returns the dispatch result from _prepare_dispatch."""
    db = AsyncMock()
    todos_db = _mock_todos_db(state={"schema_version": 1, "phase": "in_progress"})

    with (
        patch(f"{_PREPARE}.resolve_canonical_project_root", return_value="/repo"),
        patch("teleclaude.core.todos_db.get_todos_db", return_value=todos_db),
        patch(f"{_SLUG_RES}.resolve_holder_children_db", return_value=[]),
        patch(f"{_PREPARE}.check_artifact_staleness_db", return_value=[]),
        patch(f"{_PREPARE}._prepare_dispatch", return_value=(False, "dispatch")),
    ):
        result = await next_prepare(db, "slug-a", "/repo")

    assert result == "dispatch"


@pytest.mark.asyncio
async def test_next_prepare_raises_on_missing_state() -> None:
    """A slug with no state record is a contract violation — must raise, not return PREPARED."""
    db = AsyncMock()
    todos_db = _mock_todos_db(state=None)
    todos_db.read_state = AsyncMock(return_value=None)

    with (
        patch(f"{_PREPARE}.resolve_canonical_project_root", return_value="/repo"),
        patch("teleclaude.core.todos_db.get_todos_db", return_value=todos_db),
        patch(f"{_SLUG_RES}.resolve_holder_children_db", return_value=[]),
        patch(f"{_PREPARE}.check_artifact_staleness_db", return_value=[]),
        pytest.raises(RuntimeError, match="Contract violation: no state record"),
    ):
        await next_prepare(db, "stateless-slug", "/repo")


@pytest.mark.asyncio
async def test_next_prepare_skips_explicit_draft_slug(todos_db: TodosDb) -> None:
    """Explicit prepare on a draft slug must not enter derive_prepare_phase — drafts bypass lifecycle."""
    db = AsyncMock()
    await todos_db.add_to_roadmap("draft-item")
    await todos_db.write_state("draft-item", {"kind": "draft", "schema_version": 1, "phase": "pending"})

    with (
        patch(f"{_PREPARE}.resolve_canonical_project_root", return_value="/repo"),
        patch("teleclaude.core.todos_db.get_todos_db", return_value=todos_db),
        patch(f"{_PREPARE}.derive_prepare_phase") as mock_derive,
        patch(f"{_PREPARE}.compose_agent_guidance", return_value="guidance"),
    ):
        await next_prepare(db, "draft-item", "/repo")

    mock_derive.assert_not_called()


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
