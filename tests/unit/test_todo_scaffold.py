"""Tests for teleclaude.todo_scaffold — split_todo parent-to-child inheritance."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from teleclaude.core.next_machine._types import StateValue
from teleclaude.todo_scaffold import split_todo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_parent(tmp_path: Path, slug: str = "parent-slug") -> tuple[Path, str]:
    """Create a minimal parent todo directory."""
    todo_dir = tmp_path / "todos" / slug
    todo_dir.mkdir(parents=True)
    (todo_dir / "state.yaml").write_text(yaml.dump({"build": "pending", "review": "pending"}))
    (todo_dir / "input.md").write_text("parent input content describing the feature in enough detail")
    return tmp_path, slug


def _set_parent_state(tmp_path: Path, slug: str, extra: dict[str, StateValue]) -> None:
    """Merge extra fields into parent state.yaml."""
    state_path = tmp_path / "todos" / slug / "state.yaml"
    existing: dict[str, StateValue] = {}
    if state_path.exists():
        existing = yaml.safe_load(state_path.read_text()) or {}
    existing.update(extra)
    state_path.write_text(yaml.dump(existing))


def _read_child_state(tmp_path: Path, child_slug: str) -> dict[str, StateValue]:
    """Read child state.yaml for assertion."""
    state_path = tmp_path / "todos" / child_slug / "state.yaml"
    return yaml.safe_load(state_path.read_text()) or {}


def _yaml_read_state(cwd: str, slug: str) -> dict[str, StateValue]:
    """Read state from state.yaml — substitutes DB-based read_phase_state in unit tests."""
    state_path = Path(cwd) / "todos" / slug / "state.yaml"
    if state_path.exists():
        return yaml.safe_load(state_path.read_text()) or {}
    return {}


def _yaml_write_state(cwd: str, slug: str, state: dict[str, StateValue]) -> None:
    """Write state to state.yaml — substitutes DB-based write_phase_state in unit tests."""
    state_path = Path(cwd) / "todos" / slug / "state.yaml"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(yaml.dump(state))


# ---------------------------------------------------------------------------
# split_todo — parent-to-child inheritance
# ---------------------------------------------------------------------------


@patch("teleclaude.core.next_machine.core._emit_prepare_event")
@patch("teleclaude.todo_scaffold._emit_prepare_event", create=True)
def test_split_no_approval_children_start_at_discovery(
    _mock_scaffold_emit: MagicMock,
    _mock_core_emit: MagicMock,
    tmp_path: Path,
) -> None:
    """Parent with no approved phase → children start without inherited phase."""
    project_root, parent_slug = _make_parent(tmp_path)

    with (
        patch("teleclaude.core.next_machine.core.read_phase_state", side_effect=_yaml_read_state),
        patch("teleclaude.core.next_machine.core.write_phase_state", side_effect=_yaml_write_state),
    ):
        split_todo(project_root, parent_slug, ["child-a"])

    child_state = _read_child_state(tmp_path, "child-a")
    assert child_state.get("current", "input_assessment") == "input_assessment", (
        f"expected input_assessment, got {child_state.get('current')!r}"
    )


@patch("teleclaude.core.next_machine.core._emit_prepare_event")
@patch("teleclaude.todo_scaffold._emit_prepare_event", create=True)
def test_split_req_approved_children_inherit_plan_drafting(
    _mock_scaffold_emit: MagicMock,
    _mock_core_emit: MagicMock,
    tmp_path: Path,
) -> None:
    """Parent with approved requirements → children inherit current=plan_drafting."""
    project_root, parent_slug = _make_parent(tmp_path)
    (tmp_path / "todos" / parent_slug / "requirements.md").write_text(
        "Requirements content long enough to pass scaffold threshold check."
    )
    _set_parent_state(
        tmp_path,
        parent_slug,
        {
            "requirements_review": {
                "verdict": "approve",
                "findings_count": 0,
                "rounds": 1,
                "findings": [],
                "baseline_commit": "",
                "reviewed_at": "2025-01-01",
            }
        },
    )

    with (
        patch("teleclaude.core.next_machine.core.read_phase_state", side_effect=_yaml_read_state),
        patch("teleclaude.core.next_machine.core.write_phase_state", side_effect=_yaml_write_state),
    ):
        split_todo(project_root, parent_slug, ["child-b"])

    child_state = _read_child_state(tmp_path, "child-b")
    assert child_state.get("current") == "plan_drafting", f"expected plan_drafting, got {child_state.get('current')!r}"
    req_review = child_state.get("requirements_review", {})
    assert isinstance(req_review, dict)
    assert req_review.get("verdict") == "approve", f"expected verdict=approve in child, got {req_review!r}"

    child_req = tmp_path / "todos" / "child-b" / "requirements.md"
    assert child_req.exists()
    content = child_req.read_text()
    assert "Requirements content" in content, "expected parent requirements.md content in child"


@patch("teleclaude.core.next_machine.core._emit_prepare_event")
@patch("teleclaude.todo_scaffold._emit_prepare_event", create=True)
def test_split_plan_approved_children_inherit_prepared(
    _mock_scaffold_emit: MagicMock,
    _mock_core_emit: MagicMock,
    tmp_path: Path,
) -> None:
    """Parent with approved plan → children inherit current=prepared with all verdicts."""
    project_root, parent_slug = _make_parent(tmp_path)
    (tmp_path / "todos" / parent_slug / "requirements.md").write_text(
        "Requirements content long enough to pass scaffold threshold check."
    )
    (tmp_path / "todos" / parent_slug / "implementation-plan.md").write_text(
        "Implementation plan content long enough to pass scaffold threshold check."
    )
    _set_parent_state(
        tmp_path,
        parent_slug,
        {
            "requirements_review": {
                "verdict": "approve",
                "findings_count": 0,
                "rounds": 1,
                "findings": [],
                "baseline_commit": "",
                "reviewed_at": "2025-01-01",
            },
            "plan_review": {
                "verdict": "approve",
                "findings_count": 0,
                "rounds": 1,
                "findings": [],
                "baseline_commit": "",
                "reviewed_at": "2025-01-01",
            },
        },
    )

    with (
        patch("teleclaude.core.next_machine.core.read_phase_state", side_effect=_yaml_read_state),
        patch("teleclaude.core.next_machine.core.write_phase_state", side_effect=_yaml_write_state),
    ):
        split_todo(project_root, parent_slug, ["child-c"])

    child_state = _read_child_state(tmp_path, "child-c")
    assert child_state.get("current") == "prepared", f"expected prepared, got {child_state.get('current')!r}"
    req_review = child_state.get("requirements_review", {})
    plan_review = child_state.get("plan_review", {})
    assert isinstance(req_review, dict) and req_review.get("verdict") == "approve"
    assert isinstance(plan_review, dict) and plan_review.get("verdict") == "approve"

    child_req = tmp_path / "todos" / "child-c" / "requirements.md"
    child_plan = tmp_path / "todos" / "child-c" / "implementation-plan.md"
    assert "Requirements content" in child_req.read_text()
    assert "Implementation plan content" in child_plan.read_text()
