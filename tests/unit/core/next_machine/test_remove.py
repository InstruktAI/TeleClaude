"""Tests for teleclaude.core.next_machine.remove."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.next_machine.remove import execute_todo_remove

pytestmark = pytest.mark.asyncio


async def test_execute_todo_remove_routes_through_soft_primitive() -> None:
    """The receipt-backed remove path delegates to the shared DB soft-remove
    primitive, passing cwd. The slug-keyed cascade (state + artifacts + dep
    scrub + worktree teardown) is now owned by the primitive — execute_todo_remove
    is a thin engine-contract adapter."""
    mock_db = MagicMock()
    mock_db.soft_remove_from_roadmap = AsyncMock(return_value=True)

    with patch("teleclaude.core.next_machine.remove.get_todos_db", AsyncMock(return_value=mock_db)):
        await execute_todo_remove(MagicMock(), "my-slug", "/repo")

    mock_db.soft_remove_from_roadmap.assert_awaited_once_with("my-slug", cwd="/repo")


async def test_execute_todo_remove_fails_when_no_live_row_removed() -> None:
    """Unknown or already-removed slugs must fail the receipt-backed operation."""
    mock_db = MagicMock()
    mock_db.soft_remove_from_roadmap = AsyncMock(return_value=False)

    with (
        patch("teleclaude.core.next_machine.remove.get_todos_db", AsyncMock(return_value=mock_db)),
        pytest.raises(LookupError),
    ):
        await execute_todo_remove(MagicMock(), "ghost", "/repo")

    mock_db.soft_remove_from_roadmap.assert_awaited_once_with("ghost", cwd="/repo")


async def test_execute_todo_remove_requires_a_slug() -> None:
    """A missing slug must not reach the database."""
    mock_db = MagicMock()
    mock_db.soft_remove_from_roadmap = AsyncMock()

    with (
        patch("teleclaude.core.next_machine.remove.get_todos_db", AsyncMock(return_value=mock_db)),
        pytest.raises(ValueError),
    ):
        await execute_todo_remove(MagicMock(), None, "/repo")

    mock_db.soft_remove_from_roadmap.assert_not_called()
