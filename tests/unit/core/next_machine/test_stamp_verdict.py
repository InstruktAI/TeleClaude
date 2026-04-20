# guard: no-companion
"""Unit tests for stamp_verdict (state_io boundary)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from teleclaude.core.next_machine.state_io import stamp_verdict
from teleclaude.core.todos_db import TodosDb
from teleclaude.types.todos import TodoState

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]


@pytest.fixture
async def seeded_db(todos_db: TodosDb) -> TodosDb:
    """Seed a minimal v1 state for test slugs."""
    for slug in ("slug-a", "slug-b", "slug-c"):
        await todos_db.add_to_roadmap(slug)
        state = TodoState.defaults().model_dump(exclude_none=True)
        await todos_db.write_state(slug, state)
    return todos_db


def test_stamp_verdict_updates_requirements_review(seeded_db: TodosDb) -> None:
    """stamp_verdict for requirements_review persists the verdict."""
    db_path = seeded_db._db_path
    cwd = str(db_path.parent.parent)

    with (
        patch("teleclaude.core.next_machine.state_io._project_root_from_cwd", return_value=cwd),
        patch("teleclaude.core.next_machine.state_io._get_todos_db_sync", return_value=seeded_db),
    ):
        state = stamp_verdict(cwd, "slug-a", "requirements_review", "approve")

    req_review = state.get("requirements_review")
    assert isinstance(req_review, dict)
    assert req_review["verdict"] == "approve"


def test_stamp_verdict_updates_build_review(seeded_db: TodosDb) -> None:
    """stamp_verdict for build_review persists the verdict."""
    db_path = seeded_db._db_path
    cwd = str(db_path.parent.parent)

    with (
        patch("teleclaude.core.next_machine.state_io._project_root_from_cwd", return_value=cwd),
        patch("teleclaude.core.next_machine.state_io._get_todos_db_sync", return_value=seeded_db),
    ):
        state = stamp_verdict(cwd, "slug-b", "build_review", "changes_requested")

    build_review = state.get("build_review")
    assert isinstance(build_review, dict)
    assert build_review["verdict"] == "changes_requested"


def test_stamp_verdict_rejects_unknown_phase(seeded_db: TodosDb) -> None:
    """stamp_verdict raises for unrecognized phase names."""
    db_path = seeded_db._db_path
    cwd = str(db_path.parent.parent)

    with (
        patch("teleclaude.core.next_machine.state_io._project_root_from_cwd", return_value=cwd),
        patch("teleclaude.core.next_machine.state_io._get_todos_db_sync", return_value=seeded_db),
        pytest.raises(ValueError, match="invalid review phase"),
    ):
        stamp_verdict(cwd, "slug-c", "invalid_phase", "approve")
