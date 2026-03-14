"""Tests for teleclaude.todo_scaffold — split_todo parent-to-child inheritance."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from teleclaude.core.next_machine._types import StateValue

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
    state_path = tmp_path / "todos" / child_slug / "state.yaml"
    return yaml.safe_load(state_path.read_text()) or {}


# ---------------------------------------------------------------------------
# split_todo — parent-to-child inheritance
# ---------------------------------------------------------------------------


@patch("teleclaude.core.next_machine.core._emit_prepare_event")
@patch("teleclaude.todo_scaffold._emit_prepare_event", create=True)
def test_split_no_approval_children_start_at_discovery(
    mock_scaffold_emit: MagicMock,
    mock_core_emit: MagicMock,
    tmp_path: Path,
) -> None:
    """Parent with no approved phase → children start without inherited phase."""
    from teleclaude.todo_scaffold import split_todo

    project_root, parent_slug = _make_parent(tmp_path)

    with patch("teleclaude.core.next_machine.core.add_to_roadmap", return_value=None):
        split_todo(project_root, parent_slug, ["child-a"])

    child_state = _read_child_state(tmp_path, "child-a")
    assert child_state.get("prepare_phase", "") == "", (
        f"expected empty prepare_phase, got {child_state.get('prepare_phase')!r}"
    )


@patch("teleclaude.core.next_machine.core._emit_prepare_event")
@patch("teleclaude.todo_scaffold._emit_prepare_event", create=True)
def test_split_req_approved_children_inherit_plan_drafting(
    mock_scaffold_emit: MagicMock,
    mock_core_emit: MagicMock,
    tmp_path: Path,
) -> None:
    """Parent with approved requirements → children inherit prepare_phase=plan_drafting."""
    from teleclaude.todo_scaffold import split_todo

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

    with patch("teleclaude.core.next_machine.core.add_to_roadmap", return_value=None):
        split_todo(project_root, parent_slug, ["child-b"])

    child_state = _read_child_state(tmp_path, "child-b")
    assert child_state.get("prepare_phase") == "plan_drafting", (
        f"expected plan_drafting, got {child_state.get('prepare_phase')!r}"
    )
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
    mock_scaffold_emit: MagicMock,
    mock_core_emit: MagicMock,
    tmp_path: Path,
) -> None:
    """Parent with approved plan → children inherit prepare_phase=prepared with all verdicts."""
    from teleclaude.todo_scaffold import split_todo

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

    with patch("teleclaude.core.next_machine.core.add_to_roadmap", return_value=None):
        split_todo(project_root, parent_slug, ["child-c"])

    child_state = _read_child_state(tmp_path, "child-c")
    assert child_state.get("prepare_phase") == "prepared", (
        f"expected prepared, got {child_state.get('prepare_phase')!r}"
    )
    req_review = child_state.get("requirements_review", {})
    plan_review = child_state.get("plan_review", {})
    assert isinstance(req_review, dict) and req_review.get("verdict") == "approve"
    assert isinstance(plan_review, dict) and plan_review.get("verdict") == "approve"

    child_req = tmp_path / "todos" / "child-c" / "requirements.md"
    child_plan = tmp_path / "todos" / "child-c" / "implementation-plan.md"
    assert "Requirements content" in child_req.read_text()
    assert "Implementation plan content" in child_plan.read_text()
