"""Tests for Task 1: DEFAULT_STATE v2 schema and deep-merge in read_phase_state.

Guards:
- v1 state.yaml (no artifacts/audit/findings) → deep-merged to v2 with all sub-keys defaulted
- v2 state with partial nested dicts → non-default sub-keys preserved
- v2 state round-trips unchanged
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from teleclaude.core.next_machine.core import DEFAULT_STATE, read_phase_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_state(todo_dir: Path, state: dict[str, Any]) -> None:
    state_path = todo_dir / "state.yaml"
    state_path.write_text(yaml.dump(state))


def _make_todo(tmp_path: Path, slug: str = "test-slug") -> tuple[str, str]:
    """Create todo dir and return (cwd, slug)."""
    todo_dir = tmp_path / "todos" / slug
    todo_dir.mkdir(parents=True)
    return str(tmp_path), slug


# ---------------------------------------------------------------------------
# DEFAULT_STATE v2 shape
# ---------------------------------------------------------------------------


def test_default_state_has_artifacts_key() -> None:
    assert "artifacts" in DEFAULT_STATE
    artifacts = DEFAULT_STATE["artifacts"]
    assert isinstance(artifacts, dict)
    assert "input" in artifacts
    assert "requirements" in artifacts
    assert "implementation_plan" in artifacts
    for key in ("input", "requirements", "implementation_plan"):
        entry = artifacts[key]  # type: ignore[index]
        assert isinstance(entry, dict)
        assert "digest" in entry
        assert "produced_at" in entry
        assert "stale" in entry


def test_default_state_has_audit_key() -> None:
    assert "audit" in DEFAULT_STATE
    audit = DEFAULT_STATE["audit"]
    assert isinstance(audit, dict)
    for phase in ("input_assessment", "triangulation", "plan_drafting", "gate"):
        assert phase in audit
        entry = audit[phase]  # type: ignore[index]
        assert isinstance(entry, dict)
        assert "started_at" in entry
        assert "completed_at" in entry
    for review_phase in ("requirements_review", "plan_review"):
        assert review_phase in audit
        entry = audit[review_phase]  # type: ignore[index]
        assert isinstance(entry, dict)
        assert "started_at" in entry
        assert "completed_at" in entry
        assert "baseline_commit" in entry
        assert "verdict" in entry
        assert "rounds" in entry
        assert "findings" in entry


def test_default_state_requirements_review_has_findings() -> None:
    req_review = DEFAULT_STATE["requirements_review"]
    assert isinstance(req_review, dict)
    assert "findings" in req_review
    assert "baseline_commit" in req_review


def test_default_state_plan_review_has_findings() -> None:
    plan_review = DEFAULT_STATE["plan_review"]
    assert isinstance(plan_review, dict)
    assert "findings" in plan_review
    assert "baseline_commit" in plan_review


def test_default_state_has_schema_version_2() -> None:
    assert DEFAULT_STATE.get("schema_version") == 2


# ---------------------------------------------------------------------------
# Deep merge: v1 state → v2 sub-keys defaulted
# ---------------------------------------------------------------------------


def test_read_phase_state_v1_gets_artifacts_defaulted(tmp_path: Path) -> None:
    cwd, slug = _make_todo(tmp_path)
    v1_state = {
        "prepare_phase": "requirements_review",
        "requirements_review": {"verdict": "approve", "findings_count": 2, "rounds": 1},
        "plan_review": {"verdict": "", "findings_count": 0, "rounds": 0},
    }
    _write_state(tmp_path / "todos" / slug, v1_state)

    result = read_phase_state(cwd, slug)

    # New v2 nested keys must be present
    assert "artifacts" in result
    artifacts = result["artifacts"]
    assert isinstance(artifacts, dict)
    assert artifacts["input"]["produced_at"] == ""  # type: ignore[index]
    assert artifacts["requirements"]["digest"] == ""  # type: ignore[index]
    assert artifacts["implementation_plan"]["stale"] is False  # type: ignore[index]

    assert "audit" in result
    audit = result["audit"]
    assert isinstance(audit, dict)
    assert audit["input_assessment"]["started_at"] == ""  # type: ignore[index]

    # Original v1 fields preserved
    assert result["prepare_phase"] == "requirements_review"
    rr = result["requirements_review"]
    assert isinstance(rr, dict)
    assert rr["verdict"] == "approve"
    assert rr["findings_count"] == 2


def test_read_phase_state_v1_requirements_review_gets_missing_subkeys(tmp_path: Path) -> None:
    """A v1 requirements_review dict must have findings and baseline_commit defaulted in."""
    cwd, slug = _make_todo(tmp_path)
    v1_state = {
        "requirements_review": {
            "verdict": "approve",
            "reviewed_at": "2025-01-01T00:00:00+00:00",
            "findings_count": 1,
            "rounds": 1,
        }
    }
    _write_state(tmp_path / "todos" / slug, v1_state)

    result = read_phase_state(cwd, slug)
    rr = result["requirements_review"]
    assert isinstance(rr, dict)
    # v2 sub-keys added
    assert "findings" in rr
    assert rr["findings"] == []
    assert "baseline_commit" in rr
    assert rr["baseline_commit"] == ""
    # v1 fields preserved
    assert rr["verdict"] == "approve"
    assert rr["findings_count"] == 1


def test_read_phase_state_v2_preserves_existing_subkeys(tmp_path: Path) -> None:
    """Partial v2 nested dicts must retain non-default sub-keys."""
    cwd, slug = _make_todo(tmp_path)
    v2_state = {
        "schema_version": 2,
        "requirements_review": {
            "verdict": "needs_work",
            "reviewed_at": "2025-06-01T00:00:00+00:00",
            "findings_count": 3,
            "rounds": 2,
            "baseline_commit": "abc123",
            "findings": [{"id": "f1", "severity": "substantive", "summary": "missing", "status": "open"}],
        },
        "artifacts": {
            "input": {"digest": "sha256abc", "produced_at": "2025-06-01T00:00:00+00:00", "stale": False},
            "requirements": {"digest": "", "produced_at": "", "stale": False},
            "implementation_plan": {"digest": "", "produced_at": "", "stale": False},
        },
    }
    _write_state(tmp_path / "todos" / slug, v2_state)

    result = read_phase_state(cwd, slug)
    rr = result["requirements_review"]
    assert isinstance(rr, dict)
    assert rr["baseline_commit"] == "abc123"
    assert rr["findings"] == [{"id": "f1", "severity": "substantive", "summary": "missing", "status": "open"}]
    assert rr["verdict"] == "needs_work"

    artifacts = result["artifacts"]
    assert isinstance(artifacts, dict)
    assert artifacts["input"]["digest"] == "sha256abc"  # type: ignore[index]
    assert artifacts["input"]["produced_at"] == "2025-06-01T00:00:00+00:00"  # type: ignore[index]


def test_read_phase_state_v2_round_trips_unchanged(tmp_path: Path) -> None:
    """Reading a complete v2 state must return all fields unchanged."""
    cwd, slug = _make_todo(tmp_path)
    v2_state = copy.deepcopy(DEFAULT_STATE)
    v2_state["prepare_phase"] = "plan_review"  # type: ignore[assignment]
    _write_state(tmp_path / "todos" / slug, v2_state)

    result = read_phase_state(cwd, slug)
    assert result["schema_version"] == 2
    assert result["prepare_phase"] == "plan_review"
    artifacts = result["artifacts"]
    assert isinstance(artifacts, dict)
    assert "input" in artifacts
