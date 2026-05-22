"""Tests for the work-service roadmap wrapper."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from teleclaude.core.todos_db._exceptions import RemoveRefused
from teleclaude.docs_reconcile import BlockingSnippet
from teleclaude.services.work._roadmap import RoadmapOps

pytestmark = pytest.mark.asyncio


async def test_remove_threads_project_root_into_soft_primitive() -> None:
    """RoadmapOps.remove must forward the work-service project root so the DB
    primitive can run slug-keyed cleanup against the correct repo."""
    fake_db = SimpleNamespace(soft_remove_from_roadmap=AsyncMock(return_value=True))
    base = SimpleNamespace(
        project_root="/path/to/project",
        _ensure_db=AsyncMock(return_value=fake_db),
    )
    ops = RoadmapOps(base)  # type: ignore[arg-type]

    result = await ops.remove("doomed")

    assert result is True
    fake_db.soft_remove_from_roadmap.assert_awaited_once_with("doomed", cwd="/path/to/project")


async def test_remove_preserves_soft_primitive_refusal() -> None:
    refusal = RemoveRefused(
        slug="doomed",
        blocking_snippets=[
            BlockingSnippet(
                path="/path/to/project/docs/project/spec/snippet.md",
                slug_role="sole",
                live_deliverer_count=0,
                other_removed_deliverers=[],
            )
        ],
    )
    fake_db = SimpleNamespace(soft_remove_from_roadmap=AsyncMock(side_effect=refusal))
    base = SimpleNamespace(
        project_root="/path/to/project",
        _ensure_db=AsyncMock(return_value=fake_db),
    )
    ops = RoadmapOps(base)  # type: ignore[arg-type]

    with pytest.raises(RemoveRefused) as exc_info:
        await ops.remove("doomed")

    assert exc_info.value.blocking_snippets == refusal.blocking_snippets


async def test_add_does_not_accept_before() -> None:
    fake_db = SimpleNamespace(add_to_roadmap=AsyncMock(return_value=True))
    base = SimpleNamespace(
        project_root="/path/to/project",
        _ensure_db=AsyncMock(return_value=fake_db),
    )
    ops = RoadmapOps(base)  # type: ignore[arg-type]

    assert "before" not in inspect.signature(ops.add).parameters
    with pytest.raises(TypeError):
        await ops.add("new-work", before="other-work")  # type: ignore[call-arg]


async def test_move_method_removed() -> None:
    assert not hasattr(RoadmapOps, "move")
