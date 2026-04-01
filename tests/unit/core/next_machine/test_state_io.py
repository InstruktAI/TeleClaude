"""Characterization tests for next-machine state persistence helpers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.state_io import mark_phase, read_phase_state, stamp_artifact, stamp_verdict
from teleclaude.core.todos_db import TodosDb

StateData = dict[str, StateValue]


def _init_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a todos.db with proper schema via TodosDb.initialize_sync."""
    db_path = str(tmp_path / ".teleclaude" / "todos.db")
    TodosDb(db_path).initialize_sync()
    return sqlite3.connect(db_path)


def _ensure_roadmap(conn: sqlite3.Connection, slug: str) -> None:
    """Insert a roadmap entry so slug→id resolution works."""
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO roadmap (id, slug, position, status, created_at, updated_at) "  # guard: raw-sql
        "VALUES (?, ?, 0, 'active', ?, ?)",
        (slug, slug, now, now),
    )
    conn.commit()


def _write_state_db(conn: sqlite3.Connection, slug: str, state: dict[str, StateValue]) -> None:
    """Write state to todos.db (ensures roadmap entry exists)."""
    now = datetime.now(UTC).isoformat()
    _ensure_roadmap(conn, slug)
    conn.execute(
        "INSERT INTO todo_state (id, slug, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?) "  # guard: raw-sql
        "ON CONFLICT(id) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at",
        (slug, slug, json.dumps(state), now, now),
    )
    conn.commit()


def _write_artifact_db(conn: sqlite3.Connection, slug: str, name: str, content: str) -> None:
    """Write an artifact to todos.db (ensures roadmap entry exists)."""
    now = datetime.now(UTC).isoformat()
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    _ensure_roadmap(conn, slug)
    conn.execute(
        "INSERT INTO todo_artifacts (id, slug, name, content, digest, updated_by, updated_at) "  # guard: raw-sql
        "VALUES (?, ?, ?, ?, ?, 'test', ?) "
        "ON CONFLICT(id, name) DO UPDATE SET "
        "content = excluded.content, digest = excluded.digest, updated_at = excluded.updated_at",
        (slug, slug, name, content, digest, now),
    )
    conn.commit()


def _read_artifact_db(conn: sqlite3.Connection, slug: str, name: str) -> str | None:
    """Read an artifact from todos.db."""
    row = conn.execute(
        "SELECT content FROM todo_artifacts WHERE slug = ? AND name = ? LIMIT 1",  # guard: raw-sql
        (slug, name),
    ).fetchone()
    return row[0] if row else None


def _identity_path(path: str) -> str:
    return path


def _patch_mark_phase_deps(mock_machine: MagicMock) -> ExitStack:
    """Return a context manager that patches mark_phase dependencies."""

    stack = ExitStack()
    stack.enter_context(
        patch("teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=_identity_path)
    )
    stack.enter_context(
        patch("teleclaude.core.next_machine.work_lifecycle.build_lifecycle_machine", return_value=mock_machine)
    )
    stack.enter_context(patch("teleclaude.session_identity.get_session_id", return_value="test-session"))
    return stack


def test_mark_phase_changes_requested_records_round_baseline_and_finding_ids(tmp_path: Path) -> None:
    """mark_phase("review_changes_requested") stamps round, baseline commit, and finding IDs."""
    conn = _init_db(tmp_path)
    _write_state_db(conn, "slug-b", {"schema_version": 2, "current": "review_pending", "history": []})
    _write_artifact_db(conn, "slug-b", "review-findings", "R1-F1\nR1-F2\nR1-F1\n")
    conn.close()

    mock_machine = MagicMock()

    def _target_side_effect(snapshot: StateData, name: str, _ctx: object) -> StateData:
        result = dict(snapshot)
        result["current"] = name
        result.setdefault("history", [])
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


def test_mark_phase_prepared_stamps_grounding(tmp_path: Path) -> None:
    """mark_phase("prepared") stamps DOR, grounding, and verdicts via on_enter."""
    conn = _init_db(tmp_path)
    _write_artifact_db(conn, "slug-e", "requirements", "Real requirements content.\n")
    _write_artifact_db(conn, "slug-e", "implementation-plan", "Real plan content.\n")
    _write_artifact_db(conn, "slug-e", "input", "input")
    conn.close()

    with (
        patch(
            "teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=_identity_path
        ),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
        patch("teleclaude.core.next_machine.work_lifecycle.run_git_command", return_value=(0, "headsha\n", "")),
    ):
        state = mark_phase(str(tmp_path), "slug-e", "prepared")

    grounding = state["grounding"]
    assert isinstance(grounding, dict)
    assert state["current"] == "prepared"
    assert state["dor"]["score"] == 8  # type: ignore[index]
    assert grounding["base_sha"] == "headsha"
    # Quality checklist is now written to DB, not filesystem
    db_conn = sqlite3.connect(str(tmp_path / ".teleclaude" / "todos.db"))
    checklist = _read_artifact_db(db_conn, "slug-e", "quality-checklist")
    db_conn.close()
    assert checklist is not None
    assert "Browser-based frontend or web UI changes smoke-tested with Playwright" in checklist
    assert "Browser-based frontend or web UI changes verified with Playwright during review" in checklist
    assert "## Finalize Gates (Finalizer)" in checklist


def test_stamp_artifact_stamps_produced_at_for_test_specs(tmp_path: Path) -> None:
    """stamp_artifact writes artifacts.test_specs.produced_at to state."""
    conn = _init_db(tmp_path)
    _write_state_db(
        conn,
        "slug-f",
        {"schema_version": 2, "artifacts": {"test_specs": {"digest": "", "produced_at": "", "stale": False}}},
    )
    conn.close()

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


def test_stamp_artifact_records_digest_for_requirements(tmp_path: Path) -> None:
    """stamp_artifact records digest + produced_at for DB-backed requirements."""
    conn = _init_db(tmp_path)
    _write_state_db(
        conn,
        "slug-g",
        {"schema_version": 2, "artifacts": {"requirements": {"digest": "", "produced_at": "", "stale": False}}},
    )
    _write_artifact_db(conn, "slug-g", "requirements", "grounded requirements\n")
    conn.close()

    state = stamp_artifact(str(tmp_path), "slug-g", "requirements")

    artifacts = state.get("artifacts")
    assert isinstance(artifacts, dict)
    requirements = artifacts.get("requirements")
    assert isinstance(requirements, dict)
    assert requirements["digest"] != ""
    assert requirements["produced_at"] != ""


def test_stamp_artifact_records_digest_for_implementation_plan(tmp_path: Path) -> None:
    """stamp_artifact records digest + produced_at for DB-backed plans."""
    conn = _init_db(tmp_path)
    _write_state_db(
        conn,
        "slug-h",
        {
            "schema_version": 2,
            "artifacts": {"implementation_plan": {"digest": "", "produced_at": "", "stale": False}},
        },
    )
    _write_artifact_db(conn, "slug-h", "implementation-plan", "grounded plan\n")
    conn.close()

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
    """stamp_verdict persists a valid phase verdict to state."""
    conn = _init_db(tmp_path)
    _write_state_db(conn, "slug-v1", {"schema_version": 2, "requirements_review": {"verdict": "needs_work"}})
    conn.close()

    state = stamp_verdict(str(tmp_path), "slug-v1", "requirements_review", "approve")

    assert state["requirements_review"]["verdict"] == "approve"  # type: ignore[index]
    persisted = read_phase_state(str(tmp_path), "slug-v1")
    assert persisted["requirements_review"]["verdict"] == "approve"  # type: ignore[index]


def test_stamp_verdict_raises_on_invalid_phase(tmp_path: Path) -> None:
    """stamp_verdict raises ValueError for an unknown phase name."""
    conn = _init_db(tmp_path)
    _write_state_db(conn, "slug-v2", {"schema_version": 2})
    conn.close()

    with pytest.raises(ValueError, match="invalid prepare phase"):
        stamp_verdict(str(tmp_path), "slug-v2", "nonexistent_phase", "approve")


def test_stamp_verdict_raises_on_invalid_verdict(tmp_path: Path) -> None:
    """stamp_verdict raises ValueError for an unknown verdict value."""
    conn = _init_db(tmp_path)
    _write_state_db(conn, "slug-v3", {"schema_version": 2})
    conn.close()

    with pytest.raises(ValueError, match="invalid verdict"):
        stamp_verdict(str(tmp_path), "slug-v3", "requirements_review", "not_a_verdict")


# ---------------------------------------------------------------------------
# _on_enter_prepared error paths (I-4)
# ---------------------------------------------------------------------------


def test_mark_phase_prepared_raises_when_requirements_missing(tmp_path: Path) -> None:
    """prepared transition raises ValueError when requirements artifact is absent."""
    conn = _init_db(tmp_path)
    _write_artifact_db(conn, "slug-p2", "implementation-plan", "Real plan content.\n")
    conn.close()

    with (
        patch(
            "teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=_identity_path
        ),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
    ):
        with pytest.raises(ValueError, match=r"Missing requirements artifact"):
            mark_phase(str(tmp_path), "slug-p2", "prepared")


def test_mark_phase_prepared_raises_when_plan_missing(tmp_path: Path) -> None:
    """prepared transition raises ValueError when implementation-plan artifact is absent."""
    conn = _init_db(tmp_path)
    _write_artifact_db(conn, "slug-p3", "requirements", "Real requirements content.\n")
    conn.close()

    with (
        patch(
            "teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=_identity_path
        ),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
    ):
        with pytest.raises(ValueError, match=r"Missing implementation-plan artifact"):
            mark_phase(str(tmp_path), "slug-p3", "prepared")


def test_mark_phase_prepared_raises_when_no_artifacts(tmp_path: Path) -> None:
    """prepared transition raises ValueError when no artifacts exist at all."""
    _init_db(tmp_path).close()

    with (
        patch(
            "teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=_identity_path
        ),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
    ):
        with pytest.raises(ValueError, match=r"Missing requirements artifact"):
            mark_phase(str(tmp_path), "missing-slug", "prepared")


# ---------------------------------------------------------------------------
# _on_enter_finalize_ready tests (I-1)
# ---------------------------------------------------------------------------


def _write_finalize_ready_state(tmp_path: Path, slug: str) -> Path:
    """Set up a state at review_approved in DB so we can target finalize_ready."""
    conn = _init_db(tmp_path)
    _write_state_db(conn, slug, {"schema_version": 2, "current": "review_approved", "history": []})
    conn.close()
    worktree = tmp_path / "trees" / slug
    worktree.mkdir(parents=True)
    (worktree / "todos" / slug).mkdir(parents=True)
    return worktree


def test_mark_phase_finalize_ready_raises_when_git_refs_unresolvable(tmp_path: Path) -> None:
    """finalize_ready raises ValueError when git refs cannot be resolved (no real worktree)."""
    conn = _init_db(tmp_path)
    _write_state_db(conn, "slug-fr1", {"schema_version": 2, "current": "review_approved", "history": []})
    conn.close()

    with (
        patch(
            "teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=_identity_path
        ),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
    ):
        with pytest.raises(ValueError, match="unable to resolve finalized branch head"):
            mark_phase(str(tmp_path), "slug-fr1", "finalize_ready")


def test_mark_phase_finalize_ready_raises_on_uncommitted_changes(tmp_path: Path) -> None:
    """finalize_ready raises ValueError when the worktree has uncommitted changes."""
    _write_finalize_ready_state(tmp_path, "slug-fr2")

    with (
        patch(
            "teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=_identity_path
        ),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
        patch("teleclaude.core.next_machine.work_lifecycle.has_uncommitted_changes", return_value=True),
    ):
        with pytest.raises(ValueError, match="uncommitted changes"):
            mark_phase(str(tmp_path), "slug-fr2", "finalize_ready")


def test_mark_phase_finalize_ready_raises_on_head_mismatch(tmp_path: Path) -> None:
    """finalize_ready raises ValueError when worktree HEAD differs from branch ref."""
    _write_finalize_ready_state(tmp_path, "slug-fr3")

    with (
        patch(
            "teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=_identity_path
        ),
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
        patch(
            "teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=_identity_path
        ),
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
        patch(
            "teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=_identity_path
        ),
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
        patch(
            "teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=_identity_path
        ),
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
    conn = _init_db(tmp_path)
    _write_state_db(
        conn,
        "slug-fh1",
        {
            "schema_version": 2,
            "current": "finalize_ready",
            "history": [],
            "finalize": {"status": "pending"},
        },
    )
    conn.close()

    with (
        patch(
            "teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=_identity_path
        ),
        patch("teleclaude.session_identity.get_session_id", return_value="test-session"),
    ):
        with pytest.raises(ValueError, match="not ready"):
            mark_phase(str(tmp_path), "slug-fh1", "finalize_handed_off")


def test_mark_phase_finalize_handoff_happy_path(tmp_path: Path) -> None:
    """finalize_handoff writes handoff metadata when finalize is ready."""
    conn = _init_db(tmp_path)
    _write_state_db(
        conn,
        "slug-fh2",
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
    conn.close()

    with (
        patch(
            "teleclaude.core.next_machine.slug_resolution.resolve_canonical_project_root", side_effect=_identity_path
        ),
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
