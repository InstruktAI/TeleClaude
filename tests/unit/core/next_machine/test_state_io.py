"""Unit tests for mark-phase validation helpers.

Patches state_io.get_todos_db_sync (consumer-module local).
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.core.next_machine.state_io import (
    mark_phase_state,
    reconcile_phase_state,
    stamp_artifact,
    validate_mark_phase_preconditions,
)
from teleclaude.core.todos_db import TodosDb
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import TodoState

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]

_STATE_IO = "teleclaude.core.next_machine.state_io"


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


def _prepared_state() -> dict[str, StateValue]:
    return {
        "requirements_review": {"verdict": "approve"},
        "artifacts": {
            "requirements": {"produced_at": "2026-01-01T00:00:00+00:00"},
            "test_specs": {"produced_at": "2026-01-01T00:00:00+00:00"},
            "implementation_plan": {"produced_at": "2026-01-01T00:00:00+00:00"},
        },
        "test_spec_review": {"verdict": "approve"},
        "plan_review": {"verdict": "approve"},
        "dor": {"score": 8, "status": "pass"},
        "grounding": {"valid": True},
        "lifecycle_phase": "prepared",
    }


def test_input_assessment_always_valid() -> None:
    assert validate_mark_phase_preconditions({}, "input_assessment", None) is None


def test_requirements_review_reports_missing_evidence() -> None:
    result = validate_mark_phase_preconditions({}, "requirements_review", None)

    assert result == ("Cannot mark requirements_review: missing input artifact and requirements artifact")


def test_build_started_requires_prepared_prerequisites() -> None:
    result = validate_mark_phase_preconditions({}, "build_started", None)

    assert result is not None
    assert "grounding" in result


def test_build_started_accepts_prepared_state() -> None:
    result = validate_mark_phase_preconditions(_prepared_state(), "build_started", None)

    assert result is None


def test_build_complete_rejected_without_commits() -> None:
    with patch(f"{_STATE_IO}.has_build_commits_beyond_main", return_value=False):
        result = validate_mark_phase_preconditions(_prepared_state(), "build_complete", "/some/worktree")

    assert result is not None
    assert "commits beyond main" in result


def test_build_complete_accepted_with_commits() -> None:
    with patch(f"{_STATE_IO}.has_build_commits_beyond_main", return_value=True):
        result = validate_mark_phase_preconditions(_prepared_state(), "build_complete", "/some/worktree")

    assert result is None


def test_review_approved_requires_approve_verdict() -> None:
    state = _prepared_state() | {"build_review": {"verdict": "changes_requested"}}

    result = validate_mark_phase_preconditions(state, "review_approved", None)

    assert result is not None
    assert "missing build review verdict 'approve'" in result


def test_review_approved_accepts_approve_verdict() -> None:
    state = _prepared_state() | {"build_review": {"verdict": "approve"}}

    result = validate_mark_phase_preconditions(state, "review_approved", None)

    assert result is None


def test_finalize_ready_requires_ready_status() -> None:
    state = _prepared_state() | {"build_review": {"verdict": "approve"}}

    result = validate_mark_phase_preconditions(state, "finalize_ready", None)

    assert result is not None
    assert "missing finalize ready state" in result


def test_finalize_ready_accepts_ready_status() -> None:
    state = _prepared_state() | {
        "build_review": {"verdict": "approve"},
        "finalize": {"status": "ready"},
    }

    result = validate_mark_phase_preconditions(state, "finalize_ready", None)

    assert result is None


def test_handed_off_requires_handed_off_status() -> None:
    state = _prepared_state() | {"finalize": {"status": "ready"}}

    result = validate_mark_phase_preconditions(state, "handed_off", None)

    assert result is not None
    assert "missing handed-off finalize state" in result


def test_stamp_test_specs_records_requirements_upstream_digest(seeded_db: TodosDb) -> None:
    """When test_specs is stamped, upstream_digests records the current requirements digest."""
    db_path = seeded_db._db_path
    cwd = str(db_path.parent.parent)

    requirements_content = "# Requirements v1\n"
    seeded_db.write_artifact_sync("slug-a", "requirements", requirements_content)
    requirements_digest = _digest(requirements_content)

    with (
        patch(f"{_STATE_IO}.resolve_state_root", return_value=Path(cwd)),
        patch(f"{_STATE_IO}.get_todos_db_sync", return_value=seeded_db),
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
        patch(f"{_STATE_IO}.resolve_state_root", return_value=Path(cwd)),
        patch(f"{_STATE_IO}.get_todos_db_sync", return_value=seeded_db),
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
    """requirements is the root preparation artifact, so upstream_digests stays empty."""
    db_path = seeded_db._db_path
    cwd = str(db_path.parent.parent)

    seeded_db.write_artifact_sync("slug-b", "requirements", "# Requirements\n")

    with (
        patch(f"{_STATE_IO}.resolve_state_root", return_value=Path(cwd)),
        patch(f"{_STATE_IO}.get_todos_db_sync", return_value=seeded_db),
    ):
        state = stamp_artifact(cwd, "slug-b", "requirements")

    artifacts = state.get("artifacts", {})
    assert isinstance(artifacts, dict)
    requirements_entry = artifacts.get("requirements", {})
    assert isinstance(requirements_entry, dict)
    upstream_digests = requirements_entry.get("upstream_digests", {}) or {}
    assert upstream_digests == {}


def test_read_artifact_presence_propagates_sqlite_error(tmp_path: Path) -> None:
    class _BrokenConn:
        def execute(self, *_args: object, **_kwargs: object) -> object:
            raise sqlite3.OperationalError("locked")

        def close(self) -> None:
            pass

    class _BrokenDb:
        def _sync_conn(self) -> _BrokenConn:
            return _BrokenConn()

    with (
        patch("teleclaude.core.next_machine.state_io.get_todos_db_sync", return_value=_BrokenDb()),
        patch("teleclaude.core.next_machine.state_io.read_phase_state", return_value={"lifecycle_phase": "draft"}),
    ):
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            reconcile_phase_state(str(tmp_path), "my-slug")


def test_reconcile_phase_state_defaults_to_prepare_stage_and_adopts_existing_artifacts(
    tmp_path: Path,
) -> None:
    project_root = tmp_path
    (project_root / ".teleclaude").mkdir()
    (project_root / "trees" / "my-slug").mkdir(parents=True)

    state = {
        "schema_version": 2,
        "phase": "pending",
        "lifecycle_phase": "input_assessment",
        "kind": "draft",
        "artifacts": {
            "input": {
                "digest": "old",
                "produced_at": "",
                "stale": False,
                "approved": False,
                "confirmed": False,
            },
            "requirements": {
                "digest": "",
                "produced_at": "",
                "stale": False,
                "approved": False,
                "confirmed": False,
            },
            "test_specs": {
                "digest": "",
                "produced_at": "",
                "stale": False,
                "approved": False,
                "confirmed": False,
            },
            "implementation_plan": {
                "digest": "",
                "produced_at": "",
                "stale": False,
                "approved": False,
                "confirmed": False,
            },
        },
        "requirements_review": {
            "verdict": "",
            "reviewed_at": "",
            "findings_count": 0,
            "rounds": 0,
            "baseline_commit": "",
            "findings": [],
        },
        "test_spec_review": {
            "verdict": "",
            "reviewed_at": "",
            "findings_count": 0,
            "rounds": 0,
        },
        "plan_review": {
            "verdict": "",
            "reviewed_at": "",
            "findings_count": 0,
            "rounds": 0,
            "baseline_commit": "",
            "findings": [],
        },
        "build_review": {
            "verdict": "",
            "reviewed_at": "",
            "round": 0,
            "baseline_commit": "",
            "dispatch_head": "",
        },
        "grounding": {
            "valid": False,
            "base_sha": "",
            "input_digest": "",
            "referenced_paths": [],
            "changed_paths": [],
            "last_grounded_at": "",
            "invalidated_at": "",
            "invalidation_reason": "",
        },
        "finalize": {
            "status": "pending",
            "branch": "",
            "sha": "",
            "ready_at": "",
            "handed_off_at": "",
        },
        "breakdown": {"assessed": False, "todos": []},
    }

    with (
        patch("teleclaude.core.next_machine.state_io.read_phase_state", return_value=state),
        patch("teleclaude.core.next_machine.state_io.write_phase_state") as mock_write,
        patch(
            "teleclaude.core.next_machine.state_io._read_artifact_presence",
            return_value={
                "input": False,
                "requirements": True,
                "test_specs": False,
                "implementation_plan": True,
            },
        ),
        patch(
            "teleclaude.core.next_machine.state_io._artifact_digest",
            side_effect=lambda _cwd, _slug, name: {
                "requirements": "req-digest",
                "implementation-plan": "plan-digest",
            }.get(name, ""),
        ),
    ):
        payload = reconcile_phase_state(str(project_root), "my-slug")

    assert payload["lifecycle_phase"] == "plan_review"
    written_state = mock_write.call_args.args[2]
    assert written_state["artifacts"]["input"]["digest"] == ""
    assert written_state["artifacts"]["implementation_plan"]["digest"] == "plan-digest"


def _reconcile_state_with_artifacts(
    *,
    test_specs_upstream: dict[str, str],
    plan_upstream: dict[str, str],
) -> dict[str, StateValue]:
    return {
        "schema_version": 2,
        "phase": "pending",
        "lifecycle_phase": "input_assessment",
        "kind": "draft",
        "artifacts": {
            "input": {"digest": "", "produced_at": "", "stale": False, "approved": False, "confirmed": False},
            "requirements": {
                "digest": "stale-req",
                "produced_at": "2026-04-25T20:46:10+00:00",
                "stale": False,
                "approved": True,
                "confirmed": False,
            },
            "test_specs": {
                "digest": "stale-spec",
                "produced_at": "2026-04-25T20:46:11+00:00",
                "stale": False,
                "approved": False,
                "confirmed": False,
                "upstream_digests": dict(test_specs_upstream),
            },
            "implementation_plan": {
                "digest": "stale-plan",
                "produced_at": "2026-04-25T20:46:12+00:00",
                "stale": False,
                "approved": False,
                "confirmed": False,
                "upstream_digests": dict(plan_upstream),
            },
        },
        "requirements_review": {
            "verdict": "approve",
            "reviewed_at": "",
            "findings_count": 0,
            "rounds": 0,
            "baseline_commit": "",
            "findings": [],
        },
        "test_spec_review": {"verdict": "approve", "reviewed_at": "", "findings_count": 0, "rounds": 0},
        "plan_review": {
            "verdict": "approve",
            "reviewed_at": "",
            "findings_count": 0,
            "rounds": 0,
            "baseline_commit": "",
            "findings": [],
        },
        "build_review": {"verdict": "", "reviewed_at": "", "round": 0, "baseline_commit": "", "dispatch_head": ""},
        "grounding": {
            "valid": False,
            "base_sha": "",
            "input_digest": "",
            "referenced_paths": [],
            "changed_paths": [],
            "last_grounded_at": "",
            "invalidated_at": "",
            "invalidation_reason": "",
        },
        "finalize": {"status": "pending", "branch": "", "sha": "", "ready_at": "", "handed_off_at": ""},
        "breakdown": {"assessed": False, "todos": []},
    }


def test_reconcile_seeds_empty_upstream_digests_from_current(tmp_path: Path) -> None:
    """Reconcile must bootstrap empty upstream_digests from refreshed upstream digests.

    A test_specs artifact with content but empty upstream_digests is the legacy
    failure mode that triggers a silent rebuild. Reconcile is the documented
    "bring state in line with reality" surface — it must seed provenance from
    the refreshed upstream digests in the same pass.
    """
    project_root = tmp_path
    (project_root / ".teleclaude").mkdir()
    (project_root / "trees" / "my-slug").mkdir(parents=True)

    state = _reconcile_state_with_artifacts(test_specs_upstream={}, plan_upstream={})

    digest_lookup = {
        "requirements": "current-req",
        "test-specs": "current-spec",
        "implementation-plan": "current-plan",
    }

    with (
        patch(f"{_STATE_IO}.read_phase_state", return_value=state),
        patch(f"{_STATE_IO}.write_phase_state") as mock_write,
        patch(
            f"{_STATE_IO}._read_artifact_presence",
            return_value={"input": False, "requirements": True, "test_specs": True, "implementation_plan": True},
        ),
        patch(
            f"{_STATE_IO}._artifact_digest",
            side_effect=lambda _cwd, _slug, name: digest_lookup.get(name, ""),
        ),
    ):
        reconcile_phase_state(str(project_root), "my-slug")

    written_state = mock_write.call_args.args[2]
    assert written_state["artifacts"]["test_specs"]["upstream_digests"] == {"requirements": "current-req"}
    assert written_state["artifacts"]["implementation_plan"]["upstream_digests"] == {
        "requirements": "current-req",
        "test_specs": "current-spec",
    }


def test_reconcile_preserves_non_empty_upstream_digests(tmp_path: Path) -> None:
    """Reconcile must never overwrite recorded upstream provenance.

    Once an artifact has recorded upstream digests, they are the truth used
    to detect real drift. Reconcile is bootstrap-only — it never erases that
    signal, even when current upstream digests differ.
    """
    project_root = tmp_path
    (project_root / ".teleclaude").mkdir()
    (project_root / "trees" / "my-slug").mkdir(parents=True)

    state = _reconcile_state_with_artifacts(
        test_specs_upstream={"requirements": "recorded-req"},
        plan_upstream={"requirements": "recorded-req", "test_specs": "recorded-spec"},
    )

    digest_lookup = {
        "requirements": "current-req",
        "test-specs": "current-spec",
        "implementation-plan": "current-plan",
    }

    with (
        patch(f"{_STATE_IO}.read_phase_state", return_value=state),
        patch(f"{_STATE_IO}.write_phase_state") as mock_write,
        patch(
            f"{_STATE_IO}._read_artifact_presence",
            return_value={"input": False, "requirements": True, "test_specs": True, "implementation_plan": True},
        ),
        patch(
            f"{_STATE_IO}._artifact_digest",
            side_effect=lambda _cwd, _slug, name: digest_lookup.get(name, ""),
        ),
    ):
        reconcile_phase_state(str(project_root), "my-slug")

    written_state = mock_write.call_args.args[2]
    assert written_state["artifacts"]["test_specs"]["upstream_digests"] == {"requirements": "recorded-req"}
    assert written_state["artifacts"]["implementation_plan"]["upstream_digests"] == {
        "requirements": "recorded-req",
        "test_specs": "recorded-spec",
    }


def test_mark_phase_hydrates_artifact_digests_from_db(tmp_path: Path) -> None:
    """mark-phase must hydrate artifact digests from DB before normalizing state.

    When rewinding to input_assessment on a todo that has existing artifacts in the DB,
    the resulting state must reflect their presence via digest fields. Without hydration,
    downstream checks like _has_input_artifact return False even when the artifact exists.
    """
    project_root = tmp_path
    (project_root / ".teleclaude").mkdir()

    # State with empty digests — as if they were never hydrated
    state: dict[str, StateValue] = {
        "schema_version": 2,
        "phase": "pending",
        "lifecycle_phase": "prepared",
        "kind": "todo",
        "artifacts": {
            "input": {"digest": "", "produced_at": "", "stale": False, "approved": False, "confirmed": False},
            "requirements": {
                "digest": "",
                "produced_at": "2026-01-01T00:00:00+00:00",
                "stale": False,
                "approved": True,
                "confirmed": False,
            },
        },
        "requirements_review": {"verdict": "approve"},
        "test_spec_review": {"verdict": "approve"},
        "plan_review": {"verdict": "approve"},
        "dor": {"score": 8, "status": "pass"},
        "grounding": {"valid": True},
    }

    with (
        patch(f"{_STATE_IO}.read_phase_state", return_value=state),
        patch(f"{_STATE_IO}.write_phase_state") as mock_write,
        patch(
            f"{_STATE_IO}._read_artifact_presence",
            return_value={"input": True, "requirements": True, "test_specs": False, "implementation_plan": False},
        ),
        patch(
            f"{_STATE_IO}._artifact_digest",
            side_effect=lambda _cwd, _slug, name: {"input": "input-digest-abc", "requirements": "req-digest-xyz"}.get(
                name, ""
            ),
        ),
    ):
        mark_phase_state(str(project_root), "my-slug", "input_assessment")

    written_state = mock_write.call_args.args[2]
    # Input digest must be hydrated from DB — this is the core of the bug
    assert written_state["artifacts"]["input"]["digest"] == "input-digest-abc"
    assert written_state["lifecycle_phase"] == "input_assessment"


def test_reconcile_phase_state_reports_no_valid_work_phase(tmp_path: Path) -> None:
    project_root = tmp_path
    (project_root / ".teleclaude").mkdir()

    state = {
        "schema_version": 2,
        "phase": "pending",
        "lifecycle_phase": "plan_review",
        "kind": "todo",
    }

    with (
        patch("teleclaude.core.next_machine.state_io.read_phase_state", return_value=state),
        patch("teleclaude.core.next_machine.state_io._read_artifact_presence", return_value={}),
        patch("teleclaude.core.next_machine.state_io._artifact_digest", return_value=""),
    ):
        with pytest.raises(
            ValueError,
            match="No valid work phase matches the current todo state",
        ):
            reconcile_phase_state(str(project_root), "my-slug", "work")
