# guard: no-companion
"""Tests for teleclaude.core.next_machine.remove."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.next_machine.remove import execute_todo_remove

pytestmark = pytest.mark.asyncio


async def test_execute_todo_remove_notifies_via_on_committed() -> None:
    """execute_todo_remove uses the public on_committed API after its transaction."""
    mock_db = MagicMock()
    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=MagicMock(begin=MagicMock()))
    session_ctx.__aexit__ = AsyncMock(return_value=None)
    begin_ctx = MagicMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=None)
    begin_ctx.__aexit__ = AsyncMock(return_value=None)
    session_obj = MagicMock()
    session_obj.begin = MagicMock(return_value=begin_ctx)
    session_ctx.__aenter__ = AsyncMock(return_value=session_obj)
    mock_db._session = MagicMock(return_value=session_ctx)
    mock_db.read_state = AsyncMock(return_value={"kind": "draft"})
    mock_db.delete_state = AsyncMock()
    mock_db.delete_artifacts = AsyncMock()
    mock_db.remove_from_roadmap = AsyncMock()
    mock_db.clean_dep_references = AsyncMock()
    mock_db.on_committed = MagicMock()

    with patch("teleclaude.core.next_machine.remove.get_todos_db", AsyncMock(return_value=mock_db)):
        result = await execute_todo_remove(MagicMock(), "my-slug", "/repo")

    assert "removed" in result
    mock_db.on_committed.assert_called_once_with("todo_removed")
