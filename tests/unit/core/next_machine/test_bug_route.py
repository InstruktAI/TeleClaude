"""Tests for bug route artifact verification and identity detection.

Guards the two regressions fixed: (1) bug identity came from bug.md file
existence instead of state.yaml kind field, (2) verify_artifacts checked
implementation-plan.md and quality-checklist.md for bugs, causing false failures.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from teleclaude.core.next_machine.core import is_bug_todo, verify_artifacts


def _write_state(todo_dir: Path, state: dict) -> None:
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "state.yaml").write_text(
        yaml.dump(state, default_flow_style=False), encoding="utf-8"
    )


class _git_result:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# -- Regression guard: identity comes from state, not file existence ----------


def test_bug_md_presence_does_not_determine_bug_identity(tmp_path: Path) -> None:
    """bug.md existing with kind='todo' must NOT make it a bug.

    This is the exact regression: the old is_bug_todo checked file existence.
    If someone reverts to check_file_exists, this test catches it.
    """
    todo_dir = tmp_path / "todos" / "add-feature"
    _write_state(todo_dir, {"kind": "todo", "build": "pending"})
    (todo_dir / "bug.md").write_text("misleading file", encoding="utf-8")

    assert is_bug_todo(str(tmp_path), "add-feature") is False


# -- Regression guard: bug builds don't need implementation-plan or checklist -


def test_bug_build_passes_without_implementation_plan_or_checklist(tmp_path: Path) -> None:
    """Bug build verification must pass with only bug.md and commits.

    No implementation-plan.md, no quality-checklist.md in the directory.
    If the code checks for either, passed becomes False.
    """
    todo_dir = tmp_path / "todos" / "fix-crash"
    _write_state(todo_dir, {"kind": "bug", "build": "complete"})
    (todo_dir / "bug.md").write_text("Real bug report content here.", encoding="utf-8")

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            _git_result(0, "abc123"),
            _git_result(0, "abc123 fix the crash"),
        ]
        passed, _ = verify_artifacts(str(tmp_path), "fix-crash", "build", is_bug=True)

    assert passed is True


# -- Regression guard: bug reviews don't need quality-checklist ---------------


def test_bug_review_passes_without_quality_checklist(tmp_path: Path) -> None:
    """Bug review verification must pass with only review-findings.md.

    No quality-checklist.md in the directory. If the code checks for it,
    passed becomes False.
    """
    todo_dir = tmp_path / "todos" / "fix-reviewed"
    _write_state(todo_dir, {"kind": "bug", "build": "complete", "review": "approved"})
    (todo_dir / "review-findings.md").write_text(
        "# Review Findings\n\n"
        "## Findings\n\n"
        "Code quality is solid. All edge cases handled correctly. "
        "No security concerns identified during the review process.\n\n"
        "## Verdict\n\n"
        "[x] APPROVE\n",
        encoding="utf-8",
    )

    passed, _ = verify_artifacts(str(tmp_path), "fix-reviewed", "review", is_bug=True)

    assert passed is True
