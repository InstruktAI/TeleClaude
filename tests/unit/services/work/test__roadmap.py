"""Tests for the work-service roadmap wrapper."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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
