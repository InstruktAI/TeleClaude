"""Unit tests for stamp_verdict (state_io boundary)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.core.next_machine.state_io import stamp_artifact, stamp_verdict
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
        patch("teleclaude.core.next_machine.state_io.resolve_main_repo_root", return_value=Path(cwd)),
        patch("teleclaude.core.next_machine.state_io.get_todos_db_sync", return_value=seeded_db),
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
        patch("teleclaude.core.next_machine.state_io.resolve_main_repo_root", return_value=Path(cwd)),
        patch("teleclaude.core.next_machine.state_io.get_todos_db_sync", return_value=seeded_db),
    ):
        state = stamp_verdict(cwd, "slug-b", "build_review", "changes_requested")

    build_review = state.get("build_review")
    assert isinstance(build_review, dict)
    assert build_review["verdict"] == "changes_requested"


def test_stamp_verdict_approve_records_approved_digest_for_requirements(seeded_db: TodosDb) -> None:
    """When verdict is approve, approved_digest is bound to current artifact digest."""
    db_path = seeded_db._db_path
    cwd = str(db_path.parent.parent)

    seeded_db.write_artifact_sync("slug-a", "requirements", "# Requirements v1\n")

    with (
        patch("teleclaude.core.next_machine.state_io.resolve_main_repo_root", return_value=Path(cwd)),
        patch("teleclaude.core.next_machine.state_io.get_todos_db_sync", return_value=seeded_db),
    ):
        stamp_artifact(cwd, "slug-a", "requirements")
        state = stamp_verdict(cwd, "slug-a", "requirements_review", "approve")

    artifacts = state.get("artifacts", {})
    assert isinstance(artifacts, dict)
    requirements = artifacts.get("requirements", {})
    assert isinstance(requirements, dict)
    expected_digest = requirements.get("digest", "")

    req_review = state.get("requirements_review")
    assert isinstance(req_review, dict)
    assert req_review["approved_digest"] == expected_digest
    assert expected_digest != ""


def test_stamp_verdict_approve_records_approved_digest_for_test_specs(seeded_db: TodosDb) -> None:
    """test_spec_review approve binds approved_digest to current test-specs digest."""
    db_path = seeded_db._db_path
    cwd = str(db_path.parent.parent)

    seeded_db.write_artifact_sync("slug-a", "requirements", "# Requirements\n")
    seeded_db.write_artifact_sync("slug-a", "test-specs", "# Specs v1\n")

    with (
        patch("teleclaude.core.next_machine.state_io.resolve_main_repo_root", return_value=Path(cwd)),
        patch("teleclaude.core.next_machine.state_io.get_todos_db_sync", return_value=seeded_db),
    ):
        stamp_artifact(cwd, "slug-a", "requirements")
        stamp_artifact(cwd, "slug-a", "test_specs")
        state = stamp_verdict(cwd, "slug-a", "test_spec_review", "approve")

    artifacts = state.get("artifacts", {})
    assert isinstance(artifacts, dict)
    test_specs = artifacts.get("test_specs", {})
    assert isinstance(test_specs, dict)
    expected_digest = test_specs.get("digest", "")

    spec_review = state.get("test_spec_review")
    assert isinstance(spec_review, dict)
    assert spec_review["approved_digest"] == expected_digest


def test_stamp_verdict_approve_records_approved_digest_for_plan(seeded_db: TodosDb) -> None:
    """plan_review approve binds approved_digest to current implementation-plan digest."""
    db_path = seeded_db._db_path
    cwd = str(db_path.parent.parent)

    seeded_db.write_artifact_sync("slug-a", "requirements", "# Requirements\n")
    seeded_db.write_artifact_sync("slug-a", "test-specs", "# Specs\n")
    seeded_db.write_artifact_sync("slug-a", "implementation-plan", "# Plan v1\n")

    with (
        patch("teleclaude.core.next_machine.state_io.resolve_main_repo_root", return_value=Path(cwd)),
        patch("teleclaude.core.next_machine.state_io.get_todos_db_sync", return_value=seeded_db),
    ):
        stamp_artifact(cwd, "slug-a", "requirements")
        stamp_artifact(cwd, "slug-a", "test_specs")
        stamp_artifact(cwd, "slug-a", "implementation_plan")
        state = stamp_verdict(cwd, "slug-a", "plan_review", "approve")

    artifacts = state.get("artifacts", {})
    assert isinstance(artifacts, dict)
    plan_artifact = artifacts.get("implementation_plan", {})
    assert isinstance(plan_artifact, dict)
    expected_digest = plan_artifact.get("digest", "")

    plan_review = state.get("plan_review")
    assert isinstance(plan_review, dict)
    assert plan_review["approved_digest"] == expected_digest


def test_stamp_verdict_needs_work_does_not_set_approved_digest(seeded_db: TodosDb) -> None:
    """When verdict is needs_work, approved_digest stays empty."""
    db_path = seeded_db._db_path
    cwd = str(db_path.parent.parent)

    seeded_db.write_artifact_sync("slug-a", "requirements", "# Requirements\n")

    with (
        patch("teleclaude.core.next_machine.state_io.resolve_main_repo_root", return_value=Path(cwd)),
        patch("teleclaude.core.next_machine.state_io.get_todos_db_sync", return_value=seeded_db),
    ):
        stamp_artifact(cwd, "slug-a", "requirements")
        state = stamp_verdict(cwd, "slug-a", "requirements_review", "needs_work")

    req_review = state.get("requirements_review")
    assert isinstance(req_review, dict)
    assert req_review.get("approved_digest", "") == ""


def test_stamp_verdict_rejects_unknown_phase(seeded_db: TodosDb) -> None:
    """stamp_verdict raises for unrecognized phase names."""
    db_path = seeded_db._db_path
    cwd = str(db_path.parent.parent)

    with (
        patch("teleclaude.core.next_machine.state_io.resolve_main_repo_root", return_value=Path(cwd)),
        patch("teleclaude.core.next_machine.state_io.get_todos_db_sync", return_value=seeded_db),
        pytest.raises(ValueError, match="invalid review phase"),
    ):
        stamp_verdict(cwd, "slug-c", "invalid_phase", "approve")
