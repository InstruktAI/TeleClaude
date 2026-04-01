"""Tests for the ``telec todo show`` assembler."""

# pylint: disable=missing-function-docstring

from __future__ import annotations

import pytest

from teleclaude.core.todos_db import TodosDb
from teleclaude.core.todos_db._show import assemble_show_payload


@pytest.mark.unit
async def test_returns_none_when_slug_not_found(todos_db: TodosDb) -> None:
    result = await assemble_show_payload(todos_db, "nonexistent")
    assert result is None


@pytest.mark.unit
async def test_fresh_todo_shows_prepare_stage(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug", description="Test todo")
    await todos_db.write_state("my-slug", {"current": "input_assessment"})

    result = await assemble_show_payload(todos_db, "my-slug")

    assert result is not None
    assert result["slug"] == "my-slug"
    assert result["description"] == "Test todo"
    assert result["stage"] == "prepare"
    assert result["current"]["phase"] == "input_assessment"
    assert result["current"]["state"] == "in_progress"
    assert "previous" not in result
    assert "next" not in result


@pytest.mark.unit
async def test_build_started_shows_work_stage_with_previous(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "build_started"})

    result = await assemble_show_payload(todos_db, "my-slug")

    assert result is not None
    assert result["stage"] == "work"
    assert result["current"]["phase"] == "build"
    assert result["current"]["state"] == "in_progress"
    assert result["previous"] == "prepared"
    assert "next" not in result


@pytest.mark.unit
async def test_build_complete_shows_done_with_next(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "build_complete"})

    result = await assemble_show_payload(todos_db, "my-slug")

    assert result is not None
    assert result["current"]["state"] == "done"
    assert result["next"] == "review"


@pytest.mark.unit
async def test_review_approved_shows_status_and_round(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state(
        "my-slug",
        {
            "current": "review_approved",
            "review_round": 2,
        },
    )

    result = await assemble_show_payload(todos_db, "my-slug")

    assert result is not None
    assert result["current"]["phase"] == "review"
    assert result["current"]["state"] == "done"
    assert result["current"]["status"] == "approved"
    assert result["current"]["round"] == 2
    assert result["next"] == "finalize"


@pytest.mark.unit
async def test_review_changes_requested_shows_in_progress(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "review_changes_requested"})

    result = await assemble_show_payload(todos_db, "my-slug")

    assert result is not None
    assert result["current"]["state"] == "in_progress"
    assert result["current"]["status"] == "changes_requested"
    assert "next" not in result


@pytest.mark.unit
async def test_finalize_handed_off_is_done(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "finalize_handed_off"})

    result = await assemble_show_payload(todos_db, "my-slug")

    assert result is not None
    assert result["current"]["phase"] == "finalize"
    assert result["current"]["state"] == "done"
    assert "next" not in result  # last state in lifecycle


@pytest.mark.unit
async def test_delivered_slug_shows_delivered_stage(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "finalize_handed_off"})
    await todos_db.deliver("my-slug", commit="abc123")

    result = await assemble_show_payload(todos_db, "my-slug")

    assert result is not None
    assert result["stage"] == "delivered"
    assert result["current"]["state"] == "done"


@pytest.mark.unit
async def test_reopened_slug_shows_active_stage_not_delivered(todos_db: TodosDb) -> None:
    """A slug re-added to the roadmap after delivery must not render stage=delivered."""
    # First delivery cycle
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "finalize_handed_off"})
    await todos_db.deliver("my-slug", commit="abc123")

    # Re-add the slug (simulates reopening delivered work)
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "build_started"})

    result = await assemble_show_payload(todos_db, "my-slug")

    assert result is not None
    assert result["stage"] != "delivered"
    assert result["stage"] == "work"


@pytest.mark.unit
async def test_blocked_by_shows_undelivered_deps(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("blocker")
    await todos_db.add_to_roadmap("my-slug", after=["blocker"])
    await todos_db.write_state("my-slug", {"current": "build_started"})
    await todos_db.write_state("blocker", {"current": "requirements_review"})

    result = await assemble_show_payload(todos_db, "my-slug")

    assert result is not None
    assert "blocked_by" in result
    assert len(result["blocked_by"]) == 1
    assert result["blocked_by"][0]["slug"] == "blocker"
    assert result["blocked_by"][0]["stage"] == "prepare"
    assert result["blocked_by"][0]["current"] == "requirements_review"


@pytest.mark.unit
async def test_blocked_by_excludes_delivered_deps(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("done-dep")
    await todos_db.add_to_roadmap("my-slug", after=["done-dep"])
    await todos_db.write_state("my-slug", {"current": "build_started"})
    await todos_db.write_state("done-dep", {"current": "finalize_handed_off"})
    await todos_db.deliver("done-dep", commit="abc123")

    result = await assemble_show_payload(todos_db, "my-slug")

    assert result is not None
    assert "blocked_by" not in result


@pytest.mark.unit
async def test_transitive_blocked_by(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("root")
    await todos_db.add_to_roadmap("mid", after=["root"])
    await todos_db.add_to_roadmap("leaf", after=["mid"])
    await todos_db.write_state("leaf", {"current": "build_started"})
    await todos_db.write_state("mid", {"current": "plan_review"})
    await todos_db.write_state("root", {"current": "input_assessment"})

    result = await assemble_show_payload(todos_db, "leaf")

    assert result is not None
    assert len(result["blocked_by"]) == 1
    mid_blocker = result["blocked_by"][0]
    assert mid_blocker["slug"] == "mid"
    assert "blocked_by" in mid_blocker
    assert mid_blocker["blocked_by"][0]["slug"] == "root"


@pytest.mark.unit
async def test_artifacts_included_in_payload(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "build_started"})
    await todos_db.write_artifact("my-slug", "input", "Brain dump content")
    await todos_db.write_artifact("my-slug", "requirements", "Requirement details")

    result = await assemble_show_payload(todos_db, "my-slug")

    assert result is not None
    assert "artifacts" in result
    assert result["artifacts"]["input"] == "Brain dump content"
    assert result["artifacts"]["requirements"] == "Requirement details"


@pytest.mark.unit
async def test_no_artifacts_key_when_empty(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "input_assessment"})

    result = await assemble_show_payload(todos_db, "my-slug")

    assert result is not None
    assert "artifacts" not in result


@pytest.mark.unit
async def test_no_description_key_when_not_set(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")  # no description
    await todos_db.write_state("my-slug", {"current": "input_assessment"})

    result = await assemble_show_payload(todos_db, "my-slug")

    assert result is not None
    assert "description" not in result


@pytest.mark.unit
async def test_prepare_verdict_phase_done_when_verdict_present(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state(
        "my-slug",
        {
            "current": "requirements_review",
            "requirements_review": {"verdict": "approve", "timestamp": "2026-01-01"},
        },
    )

    result = await assemble_show_payload(todos_db, "my-slug")

    assert result is not None
    assert result["current"]["state"] == "done"
    assert result["next"] == "test_spec_build"
