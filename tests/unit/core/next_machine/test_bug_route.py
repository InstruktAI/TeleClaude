"""Tests for bug route artifact verification and identity detection.

Guards the behavioral contract where bug identity comes from state.yaml
kind='bug', not from bug.md file existence — and where verify_artifacts
checks the right artifacts for each kind.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from teleclaude.core.next_machine.core import is_bug_todo, verify_artifacts


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _write_state(todo_dir: Path, state: dict) -> None:
    """Write state.yaml into a todo directory."""
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "state.yaml").write_text(
        yaml.dump(state, default_flow_style=False), encoding="utf-8"
    )


def _scaffold_bug_todo(tmp_path: Path, slug: str, *, bug_content: str = "Real bug report content here.") -> Path:
    """Create a minimal bug todo with state.yaml kind=bug and bug.md."""
    todo_dir = tmp_path / "todos" / slug
    _write_state(todo_dir, {"kind": "bug", "build": "complete", "review": "pending"})
    (todo_dir / "bug.md").write_text(bug_content, encoding="utf-8")
    return todo_dir


def _scaffold_regular_todo(tmp_path: Path, slug: str) -> Path:
    """Create a minimal regular todo with state.yaml kind=todo."""
    todo_dir = tmp_path / "todos" / slug
    _write_state(todo_dir, {"kind": "todo", "build": "complete", "review": "pending"})
    return todo_dir


# ---------------------------------------------------------------------------
# is_bug_todo: identity from state, not file existence
# ---------------------------------------------------------------------------


def test_is_bug_todo_true_when_kind_is_bug(tmp_path: Path) -> None:
    """kind='bug' in state.yaml identifies the todo as a bug."""
    _scaffold_bug_todo(tmp_path, "fix-something")
    assert is_bug_todo(str(tmp_path), "fix-something") is True


def test_is_bug_todo_false_when_kind_is_todo(tmp_path: Path) -> None:
    """kind='todo' in state.yaml means it is not a bug, even if bug.md exists."""
    todo_dir = _scaffold_regular_todo(tmp_path, "add-feature")
    # Plant a bug.md file — should NOT make it a bug
    (todo_dir / "bug.md").write_text("misleading file", encoding="utf-8")
    assert is_bug_todo(str(tmp_path), "add-feature") is False


def test_is_bug_todo_false_when_kind_missing(tmp_path: Path) -> None:
    """Legacy state.yaml without kind field defaults to non-bug."""
    todo_dir = tmp_path / "todos" / "legacy-item"
    _write_state(todo_dir, {"build": "pending", "review": "pending"})
    assert is_bug_todo(str(tmp_path), "legacy-item") is False


def test_is_bug_todo_false_when_no_state(tmp_path: Path) -> None:
    """Missing state.yaml entirely returns False (default state has no kind='bug')."""
    (tmp_path / "todos" / "ghost").mkdir(parents=True)
    assert is_bug_todo(str(tmp_path), "ghost") is False


# ---------------------------------------------------------------------------
# verify_artifacts BUILD phase: bug path
# ---------------------------------------------------------------------------


def test_verify_bug_build_passes_with_valid_bug_md(tmp_path: Path) -> None:
    """Bug build verification passes when bug.md has content and commits exist."""
    _scaffold_bug_todo(tmp_path, "fix-crash")

    with patch("subprocess.run") as mock_run:
        # merge-base succeeds, log shows commits
        mock_run.side_effect = [
            _git_result(0, "abc123"),  # merge-base
            _git_result(0, "abc123 fix the crash"),  # log
        ]
        passed, report = verify_artifacts(str(tmp_path), "fix-crash", "build", is_bug=True)

    assert passed is True
    assert "PASS: bug.md exists and has content" in report
    assert "PASS: build commits exist" in report
    # Must NOT check implementation-plan or quality-checklist
    assert "implementation-plan" not in report
    assert "quality-checklist" not in report


def test_verify_bug_build_fails_without_bug_md(tmp_path: Path) -> None:
    """Bug build verification fails when bug.md is missing."""
    todo_dir = tmp_path / "todos" / "fix-missing"
    _write_state(todo_dir, {"kind": "bug", "build": "complete"})
    # No bug.md created

    passed, report = verify_artifacts(str(tmp_path), "fix-missing", "build", is_bug=True)

    assert passed is False
    assert "FAIL: bug.md does not exist" in report


def test_verify_bug_build_fails_with_empty_bug_md(tmp_path: Path) -> None:
    """Bug build verification fails when bug.md is empty."""
    _scaffold_bug_todo(tmp_path, "fix-empty", bug_content="")

    passed, report = verify_artifacts(str(tmp_path), "fix-empty", "build", is_bug=True)

    assert passed is False
    assert "FAIL: bug.md is empty" in report


def test_verify_bug_build_fails_with_template_comment_only(tmp_path: Path) -> None:
    """Bug build verification fails when bug.md has only a HTML comment template."""
    _scaffold_bug_todo(tmp_path, "fix-template", bug_content="<!-- No additional detail provided -->")

    passed, report = verify_artifacts(str(tmp_path), "fix-template", "build", is_bug=True)

    assert passed is False
    assert "FAIL: bug.md is empty or contains only a template comment" in report


def test_verify_regular_build_checks_impl_plan_not_bug_md(tmp_path: Path) -> None:
    """Regular (non-bug) build verification checks implementation-plan.md, not bug.md."""
    todo_dir = _scaffold_regular_todo(tmp_path, "add-feature")
    (todo_dir / "implementation-plan.md").write_text("- [x] Done task\n", encoding="utf-8")
    (todo_dir / "quality-checklist.md").write_text(
        "## Build Gates\n- [x] Tests pass\n", encoding="utf-8"
    )

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            _git_result(0, "abc123"),
            _git_result(0, "abc123 add feature"),
        ]
        passed, report = verify_artifacts(str(tmp_path), "add-feature", "build", is_bug=False)

    assert passed is True
    assert "implementation-plan.md" in report
    assert "quality-checklist.md" in report
    assert "bug.md" not in report


# ---------------------------------------------------------------------------
# verify_artifacts REVIEW phase: bug path skips quality-checklist
# ---------------------------------------------------------------------------


_REVIEW_FINDINGS_APPROVED = (
    "# Review Findings\n\n"
    "## Findings\n\n"
    "Code quality is solid. All edge cases handled correctly. "
    "No security concerns identified during the review process.\n\n"
    "## Verdict\n\n"
    "[x] APPROVE\n"
)


def test_verify_bug_review_skips_quality_checklist(tmp_path: Path) -> None:
    """Bug review verification checks review-findings.md but skips quality-checklist."""
    todo_dir = tmp_path / "todos" / "fix-reviewed"
    _write_state(todo_dir, {"kind": "bug", "build": "complete", "review": "approved"})
    (todo_dir / "review-findings.md").write_text(_REVIEW_FINDINGS_APPROVED, encoding="utf-8")

    passed, report = verify_artifacts(str(tmp_path), "fix-reviewed", "review", is_bug=True)

    assert passed is True
    assert "review-findings.md" in report
    assert "quality-checklist" not in report


def test_verify_regular_review_checks_quality_checklist(tmp_path: Path) -> None:
    """Regular review verification checks both review-findings.md and quality-checklist."""
    todo_dir = _scaffold_regular_todo(tmp_path, "feat-reviewed")
    _write_state(todo_dir, {"kind": "todo", "build": "complete", "review": "approved"})
    (todo_dir / "review-findings.md").write_text(_REVIEW_FINDINGS_APPROVED, encoding="utf-8")
    (todo_dir / "quality-checklist.md").write_text(
        "## Review Gates\n- [x] Code reviewed\n", encoding="utf-8"
    )

    passed, report = verify_artifacts(str(tmp_path), "feat-reviewed", "review", is_bug=False)

    assert passed is True
    assert "review-findings.md" in report
    assert "quality-checklist.md" in report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _git_result:
    """Minimal subprocess.CompletedProcess stand-in."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
