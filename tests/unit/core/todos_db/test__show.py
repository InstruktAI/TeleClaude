"""Tests for the assemble_show_payload draft fast-path."""

from __future__ import annotations

import pytest

from teleclaude.core.todos_db import TodosDb
from teleclaude.core.todos_db._show import assemble_show_payload
from teleclaude.types.todos import TodoState

pytestmark = pytest.mark.asyncio


async def test_show_payload_draft_todo_reports_draft_stage(todos_db: TodosDb) -> None:
    """Draft todos should report stage='draft' and current.phase='draft' from canonical lifecycle state."""
    await todos_db.add_to_roadmap("draft-item")
    await todos_db.write_state("draft-item", {"kind": "draft", "schema_version": 1, "phase": "pending"})
    await todos_db.write_artifact("draft-item", "input", "some idea")

    payload = await assemble_show_payload(todos_db, "draft-item")

    assert payload is not None
    assert payload["stage"] == "draft"
    assert payload["current"]["phase"] == "draft"


async def test_show_payload_pending_draft_todo_reports_pending_current_state(todos_db: TodosDb) -> None:
    """A draft todo with no active worker should keep current.state aligned to the item phase."""
    state = TodoState.defaults()
    state.kind = "feature"
    await todos_db.add_to_roadmap("feature-draft")
    await todos_db.write_state("feature-draft", state.model_dump(exclude_none=True))

    payload = await assemble_show_payload(todos_db, "feature-draft")

    assert payload is not None
    assert payload["current"]["state"] == state.phase
