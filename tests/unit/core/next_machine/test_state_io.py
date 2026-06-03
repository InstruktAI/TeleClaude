"""Unit tests for todo state I/O helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.core.next_machine.state_io import (
    apply_prepared_state,
    mark_phase_state,
    stamp_artifact,
    validate_mark_phase_preconditions,
)
from teleclaude.core.todos_db import TodosDb
from teleclaude.types.todos import TodoState

pytestmark = pytest.mark.unit

_STATE_IO = "teleclaude.core.next_machine.state_io"


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@pytest.fixture
async def seeded_db(todos_db: TodosDb) -> TodosDb:
    await todos_db.add_to_roadmap("slug-a")
    state = TodoState.defaults().model_dump(exclude_none=True)
    await todos_db.write_state("slug-a", state)
    return todos_db


def test_mark_phase_preconditions_only_reject_unknown_phase() -> None:
    assert validate_mark_phase_preconditions({}, "prepared", None) is None
    assert validate_mark_phase_preconditions({}, "build_complete", None) is None
    assert validate_mark_phase_preconditions({}, "not-a-phase", None) == "Unknown lifecycle phase: not-a-phase"


def test_mark_phase_state_is_operator_override(seeded_db: TodosDb) -> None:
    cwd = str(seeded_db._db_path.parent.parent)

    with (
        patch(f"{_STATE_IO}.resolve_state_root", return_value=Path(cwd)),
        patch(f"{_STATE_IO}.get_todos_db_sync", return_value=seeded_db),
    ):
        state = mark_phase_state(cwd, "slug-a", "prepared")

    assert state["lifecycle_phase"] == "prepared"


def test_stamp_architecture_records_prd_upstream_digest(seeded_db: TodosDb) -> None:
    cwd = str(seeded_db._db_path.parent.parent)
    prd_content = "# PRD\n"
    architecture_content = "# Architecture\n"
    seeded_db.write_artifact_sync("slug-a", "prd", prd_content)
    seeded_db.write_artifact_sync("slug-a", "architecture", architecture_content)
    prd_digest = _digest(prd_content)

    with (
        patch(f"{_STATE_IO}.resolve_state_root", return_value=Path(cwd)),
        patch(f"{_STATE_IO}.get_todos_db_sync", return_value=seeded_db),
    ):
        stamp_artifact(cwd, "slug-a", "prd")
        state = stamp_artifact(cwd, "slug-a", "architecture")

    artifacts = state.get("artifacts", {})
    assert isinstance(artifacts, dict)
    architecture = artifacts.get("architecture", {})
    assert isinstance(architecture, dict)
    upstream_digests = architecture.get("upstream_digests", {})
    assert isinstance(upstream_digests, dict)
    assert upstream_digests["prd"] == prd_digest


def test_stamp_implementation_plan_records_v2_upstream_digests(seeded_db: TodosDb) -> None:
    cwd = str(seeded_db._db_path.parent.parent)
    prd_content = "# PRD\n"
    architecture_content = "# Architecture\n"
    plan_content = "# Plan\n"
    seeded_db.write_artifact_sync("slug-a", "prd", prd_content)
    seeded_db.write_artifact_sync("slug-a", "architecture", architecture_content)
    seeded_db.write_artifact_sync("slug-a", "implementation-plan", plan_content)

    with (
        patch(f"{_STATE_IO}.resolve_state_root", return_value=Path(cwd)),
        patch(f"{_STATE_IO}.get_todos_db_sync", return_value=seeded_db),
    ):
        stamp_artifact(cwd, "slug-a", "prd")
        stamp_artifact(cwd, "slug-a", "architecture")
        state = stamp_artifact(cwd, "slug-a", "implementation_plan")

    artifacts = state.get("artifacts", {})
    assert isinstance(artifacts, dict)
    plan = artifacts.get("implementation_plan", {})
    assert isinstance(plan, dict)
    upstream_digests = plan.get("upstream_digests", {})
    assert isinstance(upstream_digests, dict)
    assert upstream_digests == {
        "prd": _digest(prd_content),
        "architecture": _digest(architecture_content),
    }


def test_apply_prepared_state_stamps_legacy_requirements_without_fabricating_prd(seeded_db: TodosDb) -> None:
    cwd = str(seeded_db._db_path.parent.parent)
    requirements_content = "# Requirements\n\nLegacy requirement body.\n"
    plan_content = "# Plan\n\n- [ ] Do the work.\n"
    seeded_db.write_artifact_sync("slug-a", "requirements", requirements_content)
    seeded_db.write_artifact_sync("slug-a", "implementation-plan", plan_content)

    with (
        patch(f"{_STATE_IO}.resolve_state_root", return_value=Path(cwd)),
        patch(f"{_STATE_IO}.get_todos_db_sync", return_value=seeded_db),
        patch(f"{_STATE_IO}.run_git_command", return_value=(0, "abc123\n", "")),
    ):
        state = apply_prepared_state(cwd, "slug-a")

    artifacts = state.get("artifacts", {})
    assert isinstance(artifacts, dict)
    prd = artifacts.get("prd", {})
    requirements = artifacts.get("requirements", {})
    assert isinstance(prd, dict)
    assert isinstance(requirements, dict)
    assert prd.get("digest", "") == ""
    assert requirements.get("digest") == _digest(requirements_content)
