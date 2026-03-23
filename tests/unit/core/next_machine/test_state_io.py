"""Characterization tests for next-machine state persistence helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict
from unittest.mock import MagicMock, patch

import pytest
import yaml

from teleclaude.core.next_machine.state_io import (
    mark_phase,
    read_phase_state,
    stamp_artifact,
    stamp_verdict,
)


class _GroundingState(TypedDict, total=False):
    valid: bool
    base_sha: str
    input_digest: str
    last_grounded_at: str


def _write_state(todo_dir: Path, state: dict[object, object]) -> None:
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "state.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")


def _mock_target(target_name: str) -> MagicMock:
    """Create a mock machine whose target() sets current to the given name."""

    def _target_side_effect(snapshot: dict, name: str, ctx: object) -> dict:
        result = dict(snapshot)
        result["current"] = name
        result.setdefault("history", [])
        return result

    machine = MagicMock()
    machine.target.side_effect = _target_side_effect
    return machine


def _patch_mark_phase_deps(mock_machine: MagicMock):  # type: ignore[no-untyped-def]
    """Return a context manager that patches mark_phase dependencies."""
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(
        patch("teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=lambda x: x)
    )
    stack.enter_context(
        patch("teleclaude.core.next_machine.work_lifecycle.build_lifecycle_machine", return_value=mock_machine)
    )
    stack.enter_context(patch("teleclaude.session_identity.get_session_id", return_value="test-session"))
    return stack


def test_read_phase_state_deep_merges_defaults_and_normalizes_ready_phase(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "todos" / "slug-a",
        {
            "schema_version": 1,
            "phase": "ready",
            "artifacts": {"requirements": {"digest": "abc123"}},
        },
    )

    state = read_phase_state(str(tmp_path), "slug-a")

    assert state["phase"] == "pending"
    assert state["schema_version"] == 2  # migrated to v2
    artifacts = state["artifacts"]
    assert isinstance(artifacts, dict)
    requirements = artifacts["requirements"]
    assert isinstance(requirements, dict)
    assert requirements["digest"] == "abc123"
    assert requirements["produced_at"] == ""


def test_mark_phase_changes_requested_records_round_baseline_and_finding_ids(tmp_path: Path) -> None:
    todo_dir = tmp_path / "todos" / "slug-b"
    _write_state(todo_dir, {"schema_version": 2, "current": "review_pending", "history": []})
    (todo_dir / "review-findings.md").write_text("R1-F1\nR1-F2\nR1-F1\n", encoding="utf-8")

    mock_machine = MagicMock()

    # on_enter for review_changes_requested is in the lifecycle — we test via the real machine
    def _target_side_effect(snapshot: dict, name: str, ctx: object) -> dict:
        result = dict(snapshot)
        result["current"] = name
        result.setdefault("history", [])
        # Simulate on_enter for review_changes_requested
        if name == "review_changes_requested":
            result["review_round"] = 1
            result["review_baseline_commit"] = "deadbeef"
            result["unresolved_findings"] = ["R1-F1", "R1-F2"]
            result["resolved_findings"] = []
        return result

    mock_machine.target.side_effect = _target_side_effect

    with _patch_mark_phase_deps(mock_machine):
        with patch("teleclaude.core.next_machine.work_lifecycle.get_head_commit", return_value="deadbeef"):
            state = mark_phase(str(tmp_path), "slug-b", "review_changes_requested")

    assert state["current"] == "review_changes_requested"
    assert state["review_round"] == 1
    assert state["review_baseline_commit"] == "deadbeef"
    assert state["unresolved_findings"] == ["R1-F1", "R1-F2"]
    assert state["resolved_findings"] == []


def test_mark_phase_approved_merges_unresolved_findings_into_resolved_ids(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "todos" / "slug-c",
        {
            "schema_version": 2,
            "current": "review_pending",
            "history": [],
            "resolved_findings": ["R1-F1"],
            "unresolved_findings": ["R1-F2", "R1-F1"],
        },
    )

    mock_machine = MagicMock()

    def _target_side_effect(snapshot: dict, name: str, ctx: object) -> dict:
        result = dict(snapshot)
        result["current"] = name
        result.setdefault("history", [])
        if name == "review_approved":
            result["review_round"] = 1
            result["review_baseline_commit"] = "cafebabe"
            unresolved = list(result.get("unresolved_findings", []))
            resolved = list(result.get("resolved_findings", []))
            merged = list(dict.fromkeys([*[str(i) for i in resolved], *[str(i) for i in unresolved]]))
            result["resolved_findings"] = merged
            result["unresolved_findings"] = []
        return result

    mock_machine.target.side_effect = _target_side_effect

    with _patch_mark_phase_deps(mock_machine):
        with patch("teleclaude.core.next_machine.work_lifecycle.get_head_commit", return_value="cafebabe"):
            state = mark_phase(str(tmp_path), "slug-c", "review_approved")

    assert state["current"] == "review_approved"
    assert state["review_round"] == 1
    assert state["review_baseline_commit"] == "cafebabe"
    assert state["resolved_findings"] == ["R1-F1", "R1-F2"]
    assert state["unresolved_findings"] == []


def test_mark_phase_prepared_stamps_grounding(tmp_path: Path) -> None:
    """mark_phase("prepared") stamps DOR, grounding, and verdicts via on_enter."""
    todo_dir = tmp_path / "todos" / "slug-e"
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text("Real requirements content.\n", encoding="utf-8")
    (todo_dir / "implementation-plan.md").write_text("Real plan content.\n", encoding="utf-8")
    (todo_dir / "input.md").write_text("input", encoding="utf-8")

    # Use the real lifecycle machine for on_enter
    with (
        patch("teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=lambda x: x),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
        patch("teleclaude.core.next_machine.work_lifecycle.run_git_command", return_value=(0, "headsha\n", "")),
    ):
        state = mark_phase(str(tmp_path), "slug-e", "prepared")

    grounding = state["grounding"]
    assert isinstance(grounding, dict)
    assert state["current"] == "prepared"
    assert state["dor"]["score"] == 8  # type: ignore[index]
    assert grounding["base_sha"] == "headsha"
    assert (todo_dir / "quality-checklist.md").exists()


def test_stamp_artifact_stamps_produced_at_for_test_specs(tmp_path: Path) -> None:
    """stamp_artifact writes artifacts.test_specs.produced_at to state.yaml."""
    todo_dir = tmp_path / "todos" / "slug-f"
    _write_state(
        todo_dir, {"schema_version": 2, "artifacts": {"test_specs": {"digest": "", "produced_at": "", "stale": False}}}
    )

    state = stamp_artifact(str(tmp_path), "slug-f", "test_specs")

    artifacts = state.get("artifacts")
    assert isinstance(artifacts, dict)
    test_specs = artifacts.get("test_specs")
    assert isinstance(test_specs, dict)
    assert test_specs["produced_at"] != ""
    persisted = read_phase_state(str(tmp_path), "slug-f")
    persisted_artifacts = persisted.get("artifacts")
    assert isinstance(persisted_artifacts, dict)
    assert persisted_artifacts["test_specs"]["produced_at"] != ""  # type: ignore[index]


def test_stamp_artifact_records_digest_for_requirements_file(tmp_path: Path) -> None:
    """stamp_artifact records digest + produced_at for file-backed requirements."""
    todo_dir = tmp_path / "todos" / "slug-g"
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text("grounded requirements\n", encoding="utf-8")
    _write_state(
        todo_dir,
        {"schema_version": 2, "artifacts": {"requirements": {"digest": "", "produced_at": "", "stale": False}}},
    )

    state = stamp_artifact(str(tmp_path), "slug-g", "requirements")

    artifacts = state.get("artifacts")
    assert isinstance(artifacts, dict)
    requirements = artifacts.get("requirements")
    assert isinstance(requirements, dict)
    assert requirements["digest"] != ""
    assert requirements["produced_at"] != ""


def test_stamp_artifact_records_digest_for_implementation_plan_file(tmp_path: Path) -> None:
    """stamp_artifact records digest + produced_at for file-backed plans."""
    todo_dir = tmp_path / "todos" / "slug-h"
    todo_dir.mkdir(parents=True)
    (todo_dir / "implementation-plan.md").write_text("grounded plan\n", encoding="utf-8")
    _write_state(
        todo_dir,
        {
            "schema_version": 2,
            "artifacts": {"implementation_plan": {"digest": "", "produced_at": "", "stale": False}},
        },
    )

    state = stamp_artifact(str(tmp_path), "slug-h", "implementation_plan")

    artifacts = state.get("artifacts")
    assert isinstance(artifacts, dict)
    implementation_plan = artifacts.get("implementation_plan")
    assert isinstance(implementation_plan, dict)
    assert implementation_plan["digest"] != ""
    assert implementation_plan["produced_at"] != ""


# ---------------------------------------------------------------------------
# stamp_verdict tests (I-2)
# ---------------------------------------------------------------------------


def test_stamp_verdict_writes_verdict_to_state(tmp_path: Path) -> None:
    """stamp_verdict persists a valid phase verdict to state.yaml."""
    todo_dir = tmp_path / "todos" / "slug-v1"
    _write_state(todo_dir, {"schema_version": 2, "requirements_review": {"verdict": "needs_work"}})

    state = stamp_verdict(str(tmp_path), "slug-v1", "requirements_review", "approve")

    assert state["requirements_review"]["verdict"] == "approve"  # type: ignore[index]
    persisted = read_phase_state(str(tmp_path), "slug-v1")
    assert persisted["requirements_review"]["verdict"] == "approve"  # type: ignore[index]


def test_stamp_verdict_raises_on_invalid_phase(tmp_path: Path) -> None:
    """stamp_verdict raises ValueError for an unknown phase name."""
    todo_dir = tmp_path / "todos" / "slug-v2"
    _write_state(todo_dir, {"schema_version": 2})

    with pytest.raises(ValueError, match="invalid prepare phase"):
        stamp_verdict(str(tmp_path), "slug-v2", "nonexistent_phase", "approve")


def test_stamp_verdict_raises_on_invalid_verdict(tmp_path: Path) -> None:
    """stamp_verdict raises ValueError for an unknown verdict value."""
    todo_dir = tmp_path / "todos" / "slug-v3"
    _write_state(todo_dir, {"schema_version": 2})

    with pytest.raises(ValueError, match="invalid verdict"):
        stamp_verdict(str(tmp_path), "slug-v3", "requirements_review", "not_a_verdict")


# ---------------------------------------------------------------------------
# _on_enter_prepared error paths (I-4)
# ---------------------------------------------------------------------------


def test_mark_phase_prepared_raises_when_todo_dir_missing(tmp_path: Path) -> None:
    """prepared transition raises ValueError when the todo directory does not exist."""
    with (
        patch("teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=lambda x: x),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
    ):
        with pytest.raises(ValueError, match="Todo directory not found"):
            mark_phase(str(tmp_path), "missing-slug", "prepared")


def test_mark_phase_prepared_raises_when_requirements_missing(tmp_path: Path) -> None:
    """prepared transition raises ValueError when requirements.md is absent."""
    todo_dir = tmp_path / "todos" / "slug-p2"
    todo_dir.mkdir(parents=True)
    (todo_dir / "implementation-plan.md").write_text("Real plan content.\n", encoding="utf-8")

    with (
        patch("teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=lambda x: x),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
    ):
        with pytest.raises(ValueError, match=r"Missing requirements\.md"):
            mark_phase(str(tmp_path), "slug-p2", "prepared")


def test_mark_phase_prepared_raises_when_plan_missing(tmp_path: Path) -> None:
    """prepared transition raises ValueError when implementation-plan.md is absent."""
    todo_dir = tmp_path / "todos" / "slug-p3"
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text("Real requirements content.\n", encoding="utf-8")

    with (
        patch("teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=lambda x: x),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
    ):
        with pytest.raises(ValueError, match=r"Missing implementation-plan\.md"):
            mark_phase(str(tmp_path), "slug-p3", "prepared")


# ---------------------------------------------------------------------------
# _on_enter_finalize_ready tests (I-1)
# ---------------------------------------------------------------------------


def _write_finalize_ready_state(tmp_path: Path, slug: str, *, head: str = "abc123") -> Path:
    """Set up a state at review_approved so we can target finalize_ready."""
    todo_dir = tmp_path / "todos" / slug
    _write_state(todo_dir, {"schema_version": 2, "current": "review_approved", "history": []})
    # Create worktree
    worktree = tmp_path / "trees" / slug
    worktree.mkdir(parents=True)
    (worktree / "todos" / slug).mkdir(parents=True)
    return worktree


def test_mark_phase_finalize_ready_raises_when_worktree_missing(tmp_path: Path) -> None:
    """finalize_ready raises ValueError when the worktree directory does not exist."""
    todo_dir = tmp_path / "todos" / "slug-fr1"
    _write_state(todo_dir, {"schema_version": 2, "current": "review_approved", "history": []})

    with (
        patch("teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=lambda x: x),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
    ):
        with pytest.raises(ValueError, match="worktree not found"):
            mark_phase(str(tmp_path), "slug-fr1", "finalize_ready")


def test_mark_phase_finalize_ready_raises_on_uncommitted_changes(tmp_path: Path) -> None:
    """finalize_ready raises ValueError when the worktree has uncommitted changes."""
    _write_finalize_ready_state(tmp_path, "slug-fr2")

    with (
        patch("teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=lambda x: x),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
        patch("teleclaude.core.next_machine.work_lifecycle.has_uncommitted_changes", return_value=True),
    ):
        with pytest.raises(ValueError, match="uncommitted changes"):
            mark_phase(str(tmp_path), "slug-fr2", "finalize_ready")


def test_mark_phase_finalize_ready_raises_on_head_mismatch(tmp_path: Path) -> None:
    """finalize_ready raises ValueError when worktree HEAD differs from branch ref."""
    _write_finalize_ready_state(tmp_path, "slug-fr3")

    with (
        patch("teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=lambda x: x),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
        patch("teleclaude.core.next_machine.work_lifecycle.has_uncommitted_changes", return_value=False),
        patch("teleclaude.core.next_machine.work_lifecycle.get_head_commit", return_value="worktree-head"),
        patch("teleclaude.core.next_machine.work_lifecycle.get_ref_commit", return_value="branch-head"),
    ):
        with pytest.raises(ValueError, match="does not match worktree HEAD"):
            mark_phase(str(tmp_path), "slug-fr3", "finalize_ready")


def test_mark_phase_finalize_ready_raises_when_remote_missing(tmp_path: Path) -> None:
    """finalize_ready raises ValueError when origin/{slug} is missing."""
    _write_finalize_ready_state(tmp_path, "slug-fr4")

    with (
        patch("teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=lambda x: x),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
        patch("teleclaude.core.next_machine.work_lifecycle.has_uncommitted_changes", return_value=False),
        patch("teleclaude.core.next_machine.work_lifecycle.get_head_commit", return_value="abc123"),
        patch("teleclaude.core.next_machine.work_lifecycle.get_ref_commit", return_value="abc123"),
        patch("teleclaude.core.next_machine.work_lifecycle.get_remote_branch_head", return_value=""),
    ):
        with pytest.raises(ValueError, match=r"origin/.* is missing"):
            mark_phase(str(tmp_path), "slug-fr4", "finalize_ready")


def test_mark_phase_finalize_ready_raises_when_remote_mismatches(tmp_path: Path) -> None:
    """finalize_ready raises ValueError when origin/{slug} differs from branch head."""
    _write_finalize_ready_state(tmp_path, "slug-fr5")

    with (
        patch("teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=lambda x: x),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
        patch("teleclaude.core.next_machine.work_lifecycle.has_uncommitted_changes", return_value=False),
        patch("teleclaude.core.next_machine.work_lifecycle.get_head_commit", return_value="abc123"),
        patch("teleclaude.core.next_machine.work_lifecycle.get_ref_commit", return_value="abc123"),
        patch("teleclaude.core.next_machine.work_lifecycle.get_remote_branch_head", return_value="remote-xyz"),
    ):
        with pytest.raises(ValueError, match=r"origin/.* is at"):
            mark_phase(str(tmp_path), "slug-fr5", "finalize_ready")


def test_mark_phase_finalize_ready_happy_path(tmp_path: Path) -> None:
    """finalize_ready writes finalize sub-dict on successful validation."""
    _write_finalize_ready_state(tmp_path, "slug-fr6")

    with (
        patch("teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=lambda x: x),
        patch("teleclaude.session_identity.get_session_id", return_value="worker-sess-1"),
        patch("teleclaude.core.next_machine.work_lifecycle.has_uncommitted_changes", return_value=False),
        patch("teleclaude.core.next_machine.work_lifecycle.get_head_commit", return_value="abc123"),
        patch("teleclaude.core.next_machine.work_lifecycle.get_ref_commit", return_value="abc123"),
        patch("teleclaude.core.next_machine.work_lifecycle.get_remote_branch_head", return_value="abc123"),
    ):
        state = mark_phase(str(tmp_path), "slug-fr6", "finalize_ready")

    assert state["current"] == "finalize_ready"
    finalize = state["finalize"]
    assert isinstance(finalize, dict)
    assert finalize["status"] == "ready"
    assert finalize["sha"] == "abc123"
    assert finalize["branch"] == "slug-fr6"
    assert finalize["worker_session_id"] == "worker-sess-1"
    assert finalize["ready_at"] != ""


# ---------------------------------------------------------------------------
# _on_enter_finalize_handoff tests (I-1)
# ---------------------------------------------------------------------------


def test_mark_phase_finalize_handoff_raises_when_not_ready(tmp_path: Path) -> None:
    """finalize_handoff raises ValueError when finalize.status is not 'ready'."""
    # Write state inside the worktree (where _resolve_state_cwd will look)
    worktree = tmp_path / "trees" / "slug-fh1"
    worktree.mkdir(parents=True)
    wt_todo_dir = worktree / "todos" / "slug-fh1"
    _write_state(
        wt_todo_dir,
        {
            "schema_version": 2,
            "current": "finalize_ready",
            "history": [],
            "finalize": {"status": "pending"},
        },
    )

    with (
        patch("teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=lambda x: x),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
    ):
        with pytest.raises(ValueError, match="not ready"):
            mark_phase(str(tmp_path), "slug-fh1", "finalize_handed_off")


def test_mark_phase_finalize_handoff_happy_path(tmp_path: Path) -> None:
    """finalize_handoff writes handoff metadata when finalize is ready."""
    # Write state inside the worktree (where _resolve_state_cwd will look)
    worktree = tmp_path / "trees" / "slug-fh2"
    worktree.mkdir(parents=True)
    wt_todo_dir = worktree / "todos" / "slug-fh2"
    _write_state(
        wt_todo_dir,
        {
            "schema_version": 2,
            "current": "finalize_ready",
            "history": [],
            "finalize": {
                "status": "ready",
                "branch": "slug-fh2",
                "sha": "abc123",
                "ready_at": "2026-01-01T00:00:00",
                "worker_session_id": "worker-1",
            },
        },
    )

    with (
        patch("teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=lambda x: x),
        patch("teleclaude.session_identity.get_session_id", return_value="integrator-sess"),
    ):
        state = mark_phase(str(tmp_path), "slug-fh2", "finalize_handed_off")

    assert state["current"] == "finalize_handed_off"
    finalize = state["finalize"]
    assert isinstance(finalize, dict)
    assert finalize["status"] == "handed_off"
    assert finalize["handoff_session_id"] == "integrator-sess"
    assert finalize["handed_off_at"] != ""
    assert finalize["branch"] == "slug-fh2"
    assert finalize["sha"] == "abc123"
