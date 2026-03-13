"""Tests for Task 4: ghost artifact protection in _derive_prepare_phase."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from teleclaude.core.next_machine.core import PreparePhase, _derive_prepare_phase

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LONG_CONTENT = "This content is long enough to pass the scaffold content threshold check."


def _make_todo(tmp_path: Path, slug: str = "test-slug") -> tuple[str, str]:
    todo_dir = tmp_path / "todos" / slug
    todo_dir.mkdir(parents=True)
    return str(tmp_path), slug


def _write_file(todo_dir: Path, name: str, content: str = _LONG_CONTENT) -> Path:
    p = todo_dir / name
    p.write_text(content)
    return p


def _v2_state(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a minimal v2 state dict with artifacts section."""
    s: dict[str, Any] = {
        "schema_version": 2,
        "artifacts": {
            "input": {"digest": "", "produced_at": "", "stale": False},
            "requirements": {"digest": "", "produced_at": "", "stale": False},
            "implementation_plan": {"digest": "", "produced_at": "", "stale": False},
        },
        "requirements_review": {"verdict": "", "findings": [], "baseline_commit": "", "rounds": 0, "findings_count": 0},
        "plan_review": {"verdict": "", "findings": [], "baseline_commit": "", "rounds": 0, "findings_count": 0},
    }
    if extra:
        s.update(extra)
    return s


# ---------------------------------------------------------------------------
# Ghost artifact protection (v2 state)
# ---------------------------------------------------------------------------


def test_ghost_requirements_not_treated_as_produced_v2(tmp_path: Path) -> None:
    """v2 state: requirements.md on disk but no produced_at → INPUT_ASSESSMENT."""
    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "input.md")
    _write_file(tmp_path / "todos" / slug, "requirements.md")

    # v2 state with empty produced_at — ghost artifact
    state = _v2_state()

    phase = _derive_prepare_phase(slug, cwd, state)
    assert phase == PreparePhase.INPUT_ASSESSMENT


def test_requirements_with_produced_at_treated_as_produced_v2(tmp_path: Path) -> None:
    """v2 state: requirements.md on disk WITH produced_at → REQUIREMENTS_REVIEW."""
    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "input.md")
    _write_file(tmp_path / "todos" / slug, "requirements.md")

    state = _v2_state()
    state["artifacts"]["requirements"]["produced_at"] = "2025-01-01T00:00:00+00:00"  # type: ignore[index]

    phase = _derive_prepare_phase(slug, cwd, state)
    assert phase == PreparePhase.REQUIREMENTS_REVIEW


def test_ghost_plan_not_treated_as_produced_v2(tmp_path: Path) -> None:
    """v2 state: plan on disk but no produced_at → TEST_SPEC_BUILD (no test specs yet)."""
    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "input.md")
    _write_file(tmp_path / "todos" / slug, "requirements.md")
    _write_file(tmp_path / "todos" / slug, "implementation-plan.md")

    # requirements has produced_at, plan does not
    state = _v2_state()
    state["artifacts"]["requirements"]["produced_at"] = "2025-01-01T00:00:00+00:00"  # type: ignore[index]
    state["requirements_review"] = {  # type: ignore[assignment]
        "verdict": "approve",
        "findings": [],
        "baseline_commit": "",
        "rounds": 0,
        "findings_count": 0,
    }

    phase = _derive_prepare_phase(slug, cwd, state)
    assert phase == PreparePhase.TEST_SPEC_BUILD


# ---------------------------------------------------------------------------
# Backward compatibility (v1 state)
# ---------------------------------------------------------------------------


def test_v1_state_file_existence_respected(tmp_path: Path) -> None:
    """v1 state (no artifacts key) with requirements.md on disk → REQUIREMENTS_REVIEW."""
    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "input.md")
    _write_file(tmp_path / "todos" / slug, "requirements.md")

    # v1 state has no artifacts key (schema_version absent)
    v1_state: dict[str, Any] = {
        "requirements_review": {
            "verdict": "",
            "findings_count": 0,
            "rounds": 0,
        },
        "plan_review": {"verdict": "", "findings_count": 0, "rounds": 0},
    }

    phase = _derive_prepare_phase(slug, cwd, v1_state)
    assert phase == PreparePhase.REQUIREMENTS_REVIEW
