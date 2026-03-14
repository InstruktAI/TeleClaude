"""Characterization tests for next-machine state persistence helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TypedDict
from unittest.mock import patch

import yaml

from teleclaude.core.next_machine.state_io import (
    mark_phase,
    mark_prepare_phase,
    mark_ready,
    read_phase_state,
)


class _GroundingState(TypedDict, total=False):
    valid: bool
    base_sha: str
    input_digest: str
    last_grounded_at: str


def _write_state(todo_dir: Path, state: dict[object, object]) -> None:
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "state.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")


def test_read_phase_state_deep_merges_defaults_and_normalizes_ready_phase(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "todos" / "slug-a",
        {
            "schema_version": 2,
            "phase": "ready",
            "artifacts": {"requirements": {"digest": "abc123"}},
        },
    )

    state = read_phase_state(str(tmp_path), "slug-a")

    assert state["phase"] == "pending"
    artifacts = state["artifacts"]
    assert isinstance(artifacts, dict)
    requirements = artifacts["requirements"]
    assert isinstance(requirements, dict)
    assert requirements["digest"] == "abc123"
    assert requirements["produced_at"] == ""


def test_mark_phase_changes_requested_records_round_baseline_and_finding_ids(tmp_path: Path) -> None:
    todo_dir = tmp_path / "todos" / "slug-b"
    _write_state(todo_dir, {})
    (todo_dir / "review-findings.md").write_text("R1-F1\nR1-F2\nR1-F1\n", encoding="utf-8")

    with patch("teleclaude.core.next_machine.state_io._get_head_commit", return_value="deadbeef"):
        state = mark_phase(str(tmp_path), "slug-b", "review", "changes_requested")

    assert state["review_round"] == 1
    assert state["review_baseline_commit"] == "deadbeef"
    assert state["unresolved_findings"] == ["R1-F1", "R1-F2"]
    assert state["resolved_findings"] == []


def test_mark_phase_approved_merges_unresolved_findings_into_resolved_ids(tmp_path: Path) -> None:
    _write_state(
        tmp_path / "todos" / "slug-c",
        {"resolved_findings": ["R1-F1"], "unresolved_findings": ["R1-F2", "R1-F1"]},
    )

    with patch("teleclaude.core.next_machine.state_io._get_head_commit", return_value="cafebabe"):
        state = mark_phase(str(tmp_path), "slug-c", "review", "approved")

    assert state["review_round"] == 1
    assert state["review_baseline_commit"] == "cafebabe"
    assert state["resolved_findings"] == ["R1-F1", "R1-F2"]
    assert state["unresolved_findings"] == []


def test_mark_prepare_phase_prepared_stamps_grounding_from_head_and_input_digest(tmp_path: Path) -> None:
    todo_dir = tmp_path / "todos" / "slug-d"
    todo_dir.mkdir(parents=True)
    (todo_dir / "input.md").write_text("hello world", encoding="utf-8")

    with patch("teleclaude.core.next_machine.state_io._run_git_prepare", return_value=(0, "abc123\n", "")):
        state = mark_prepare_phase(str(tmp_path), "slug-d", "prepared")

    grounding = state["grounding"]
    assert isinstance(grounding, dict)
    assert grounding["valid"] is True
    assert grounding["base_sha"] == "abc123"
    assert grounding["input_digest"] == hashlib.sha256(b"hello world").hexdigest()
    assert grounding["changed_paths"] == []


def test_mark_ready_generates_quality_checklist_and_ready_state(tmp_path: Path) -> None:
    todo_dir = tmp_path / "todos" / "slug-e"
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text("Real requirements content.\n", encoding="utf-8")
    (todo_dir / "implementation-plan.md").write_text("Real plan content.\n", encoding="utf-8")
    (todo_dir / "input.md").write_text("input", encoding="utf-8")

    with patch("teleclaude.core.next_machine.state_io._run_git_prepare", return_value=(0, "headsha\n", "")):
        ok, _message = mark_ready(str(tmp_path), "slug-e")

    assert ok is True
    state = read_phase_state(str(tmp_path), "slug-e")
    grounding = state["grounding"]
    assert isinstance(grounding, dict)
    assert state["prepare_phase"] == "prepared"
    assert state["dor"]["score"] == 8  # type: ignore[index]
    assert grounding["base_sha"] == "headsha"
    assert (todo_dir / "quality-checklist.md").exists()
