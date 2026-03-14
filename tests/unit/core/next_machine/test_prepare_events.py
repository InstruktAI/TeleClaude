"""Characterization tests for prepare phase derivation and invalidation events."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from teleclaude.core.next_machine._types import PreparePhase, RoadmapEntry
from teleclaude.core.next_machine.prepare_events import (
    _derive_prepare_phase,
    _has_test_spec_artifacts,
    invalidate_stale_preparations,
)
from teleclaude.core.next_machine.roadmap import save_roadmap


def _write_state(todo_dir: Path, state: dict[object, object]) -> None:
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "state.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")


def test_has_test_spec_artifacts_detects_xfail_marked_tests_in_worktree(tmp_path: Path) -> None:
    worktree = tmp_path / "trees" / "slug-a" / "tests"
    worktree.mkdir(parents=True)
    (worktree / "test_example.py").write_text("import pytest\n\npytestmark = pytest.mark.xfail\n", encoding="utf-8")

    assert _has_test_spec_artifacts(str(tmp_path), "slug-a") is True


def test_derive_prepare_phase_routes_to_plan_drafting_after_specs_are_approved(tmp_path: Path) -> None:
    todo_dir = tmp_path / "todos" / "slug-b"
    todo_dir.mkdir(parents=True)
    (todo_dir / "input.md").write_text("input", encoding="utf-8")
    (todo_dir / "requirements.md").write_text(
        "These requirements are long enough to count as authored content for the gate checks.\n",
        encoding="utf-8",
    )
    worktree = tmp_path / "trees" / "slug-b" / "tests"
    worktree.mkdir(parents=True)
    (worktree / "test_specs.py").write_text("pytestmark = pytest.mark.xfail\n", encoding="utf-8")
    state = {
        "schema_version": 2,
        "artifacts": {
            "requirements": {"digest": "a", "produced_at": "2025-01-01", "stale": False},
            "implementation_plan": {"digest": "", "produced_at": "", "stale": False},
        },
        "requirements_review": {"verdict": "approve"},
        "test_spec_review": {"verdict": "approve"},
    }

    phase = _derive_prepare_phase("slug-b", str(tmp_path), state)

    assert phase == PreparePhase.PLAN_DRAFTING


def test_invalidate_stale_preparations_marks_only_overlapping_grounding_as_invalid(tmp_path: Path) -> None:
    save_roadmap(
        str(tmp_path),
        [
            RoadmapEntry(slug="slug-c", group=None, after=[], description=None),
            RoadmapEntry(slug="slug-d", group=None, after=[], description=None),
        ],
    )
    _write_state(
        tmp_path / "todos" / "slug-c",
        {"grounding": {"referenced_paths": ["src/app.py"], "valid": True}},
    )
    _write_state(
        tmp_path / "todos" / "slug-d",
        {"grounding": {"referenced_paths": ["src/other.py"], "valid": True}},
    )

    with patch("teleclaude.core.next_machine.prepare_events._emit_prepare_event") as emit_event:
        result = invalidate_stale_preparations(str(tmp_path), ["src/app.py"])

    invalidated_state = yaml.safe_load((tmp_path / "todos" / "slug-c" / "state.yaml").read_text(encoding="utf-8"))
    untouched_state = yaml.safe_load((tmp_path / "todos" / "slug-d" / "state.yaml").read_text(encoding="utf-8"))
    assert result == {"invalidated": ["slug-c"]}
    assert invalidated_state["grounding"]["valid"] is False
    assert invalidated_state["prepare_phase"] == PreparePhase.GROUNDING_CHECK.value
    assert untouched_state["grounding"]["valid"] is True
    assert emit_event.call_args.args[0] == "domain.software-development.prepare.grounding_invalidated"
