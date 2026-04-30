# guard: no-companion
"""Unit tests for stamp_artifact upstream_digests binding."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.core.next_machine.state_io import stamp_artifact
from teleclaude.core.todos_db import TodosDb
from teleclaude.types.todos import TodoState

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@pytest.fixture
async def seeded_db(todos_db: TodosDb) -> TodosDb:
    """Seed a minimal v1 state for test slugs."""
    for slug in ("slug-a", "slug-b"):
        await todos_db.add_to_roadmap(slug)
        state = TodoState.defaults().model_dump(exclude_none=True)
        await todos_db.write_state(slug, state)
    return todos_db


def test_stamp_test_specs_records_requirements_upstream_digest(seeded_db: TodosDb) -> None:
    """When test_specs is stamped, upstream_digests records the current requirements digest."""
    db_path = seeded_db._db_path
    cwd = str(db_path.parent.parent)

    requirements_content = "# Requirements v1\n"
    seeded_db.write_artifact_sync("slug-a", "requirements", requirements_content)
    requirements_digest = _digest(requirements_content)

    with (
        patch("teleclaude.core.next_machine.state_io.resolve_main_repo_root", return_value=Path(cwd)),
        patch("teleclaude.core.next_machine.state_io.get_todos_db_sync", return_value=seeded_db),
    ):
        stamp_artifact(cwd, "slug-a", "requirements")
        state = stamp_artifact(cwd, "slug-a", "test_specs")

    artifacts = state.get("artifacts", {})
    assert isinstance(artifacts, dict)
    test_specs = artifacts.get("test_specs", {})
    assert isinstance(test_specs, dict)
    upstream_digests = test_specs.get("upstream_digests", {})
    assert isinstance(upstream_digests, dict)
    assert upstream_digests["requirements"] == requirements_digest
    assert requirements_digest != ""


def test_stamp_implementation_plan_records_both_upstream_digests(seeded_db: TodosDb) -> None:
    """When implementation_plan is stamped, upstream_digests records both requirements and test_specs digests."""
    db_path = seeded_db._db_path
    cwd = str(db_path.parent.parent)

    requirements_content = "# Requirements\n"
    test_specs_content = "# Specs\n"
    plan_content = "# Plan\n"
    seeded_db.write_artifact_sync("slug-a", "requirements", requirements_content)
    seeded_db.write_artifact_sync("slug-a", "test-specs", test_specs_content)
    seeded_db.write_artifact_sync("slug-a", "implementation-plan", plan_content)

    requirements_digest = _digest(requirements_content)
    test_specs_digest = _digest(test_specs_content)

    with (
        patch("teleclaude.core.next_machine.state_io.resolve_main_repo_root", return_value=Path(cwd)),
        patch("teleclaude.core.next_machine.state_io.get_todos_db_sync", return_value=seeded_db),
    ):
        stamp_artifact(cwd, "slug-a", "requirements")
        stamp_artifact(cwd, "slug-a", "test_specs")
        state = stamp_artifact(cwd, "slug-a", "implementation_plan")

    artifacts = state.get("artifacts", {})
    assert isinstance(artifacts, dict)
    plan = artifacts.get("implementation_plan", {})
    assert isinstance(plan, dict)
    upstream_digests = plan.get("upstream_digests", {})
    assert isinstance(upstream_digests, dict)
    assert upstream_digests["requirements"] == requirements_digest
    assert upstream_digests["test_specs"] == test_specs_digest


def test_stamp_requirements_does_not_record_upstream_digests(seeded_db: TodosDb) -> None:
    """requirements is the root preparation artifact — upstream_digests stays empty."""
    db_path = seeded_db._db_path
    cwd = str(db_path.parent.parent)

    seeded_db.write_artifact_sync("slug-b", "requirements", "# Requirements\n")

    with (
        patch("teleclaude.core.next_machine.state_io.resolve_main_repo_root", return_value=Path(cwd)),
        patch("teleclaude.core.next_machine.state_io.get_todos_db_sync", return_value=seeded_db),
    ):
        state = stamp_artifact(cwd, "slug-b", "requirements")

    artifacts = state.get("artifacts", {})
    assert isinstance(artifacts, dict)
    requirements_entry = artifacts.get("requirements", {})
    assert isinstance(requirements_entry, dict)
    upstream_digests = requirements_entry.get("upstream_digests", {}) or {}
    assert upstream_digests == {}
