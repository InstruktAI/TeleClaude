"""Unit tests for verify_artifacts() — artifact presence and consistency checks."""

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import yaml

from teleclaude.core.next_machine.core import (
    _extract_checklist_section,
    _is_review_findings_template,
    verify_artifacts,
)

# =============================================================================
# Helper
# =============================================================================


def _make_todo_dir(tmpdir: str, slug: str) -> Path:
    """Create todos/{slug}/ directory structure."""
    todo_dir = Path(tmpdir) / "todos" / slug
    todo_dir.mkdir(parents=True, exist_ok=True)
    return todo_dir


def _write_state(todo_dir: Path, build: str = "complete", review: str = "pending") -> None:
    state = {"build": build, "review": review}
    (todo_dir / "state.yaml").write_text(yaml.dump(state), encoding="utf-8")


def _write_impl_plan(todo_dir: Path, *, all_checked: bool = True) -> None:
    if all_checked:
        content = "# Plan\n\n- [x] Task 1\n- [x] Task 2\n"
    else:
        content = "# Plan\n\n- [x] Task 1\n- [ ] Task 2\n"
    (todo_dir / "implementation-plan.md").write_text(content, encoding="utf-8")


def _write_checklist_build(todo_dir: Path, *, checked: bool = True) -> None:
    mark = "x" if checked else " "
    content = (
        "# Quality Checklist\n\n"
        "## Build Gates (Builder)\n\n"
        f"- [{mark}] Tests pass\n"
        f"- [{mark}] Lint passes\n\n"
        "## Review Gates (Reviewer)\n\n"
        "- [ ] Findings written\n"
    )
    (todo_dir / "quality-checklist.md").write_text(content, encoding="utf-8")


def _write_checklist_review(todo_dir: Path, *, checked: bool = True) -> None:
    mark = "x" if checked else " "
    content = (
        "# Quality Checklist\n\n"
        "## Build Gates (Builder)\n\n"
        "- [x] Tests pass\n\n"
        "## Review Gates (Reviewer)\n\n"
        f"- [{mark}] Findings written\n"
        f"- [{mark}] Verdict recorded\n"
    )
    (todo_dir / "quality-checklist.md").write_text(content, encoding="utf-8")


def _write_review_findings(todo_dir: Path, verdict: str = "APPROVE", *, template: bool = False) -> None:
    if template:
        # Scaffold template: has ## Findings but no verdict
        content = "# Review Findings\n\n## Findings\n\n_No findings yet._\n"
    elif verdict == "APPROVE":
        content = "# Review Findings\n\n## Critical\n\nNone.\n\n## Verdict: APPROVE\n\n[x] APPROVE\n"
    else:
        content = "# Review Findings\n\n## Critical\n\nSome issues.\n\n## Verdict: REQUEST CHANGES\n"
    (todo_dir / "review-findings.md").write_text(content, encoding="utf-8")


def _mock_commits_exist(has_commits: bool = True) -> MagicMock:
    """Return a mock for subprocess.run that simulates git commit checking."""
    merge_base_result = MagicMock()
    merge_base_result.returncode = 0
    merge_base_result.stdout = "abc123\n"

    log_result = MagicMock()
    log_result.returncode = 0
    log_result.stdout = "abc123 feat: initial commit\n" if has_commits else ""

    def side_effect(cmd: list[str], /, *args: Any, **kwargs: Any) -> MagicMock:  # noqa: ARG001
        if "merge-base" in cmd:
            return merge_base_result
        return log_result

    mock = MagicMock(side_effect=side_effect)
    return mock


# =============================================================================
# _extract_checklist_section
# =============================================================================


def test_extract_checklist_section_found() -> None:
    content = "## Build Gates (Builder)\n\n- [x] Tests pass\n\n## Review Gates (Reviewer)\n\n- [ ] Done\n"
    result = _extract_checklist_section(content, "Build Gates (Builder)")
    assert result is not None
    assert "[x] Tests pass" in result
    assert "Review Gates" not in result


def test_extract_checklist_section_not_found() -> None:
    content = "## Other Section\n\n- [x] Something\n"
    result = _extract_checklist_section(content, "Build Gates")
    assert result is None


def test_extract_checklist_section_stops_at_next_h2() -> None:
    content = "## Section A\n\n- [x] A item\n\n## Section B\n\n- [x] B item\n"
    result = _extract_checklist_section(content, "Section A")
    assert result is not None
    assert "A item" in result
    assert "B item" not in result


# =============================================================================
# _is_review_findings_template
# =============================================================================


def test_is_review_findings_template_too_short() -> None:
    assert _is_review_findings_template("# Review\n") is True


def test_is_review_findings_template_empty_findings_no_verdict() -> None:
    content = "# Review Findings\n\n## Findings\n\n_No findings yet._\n"
    assert _is_review_findings_template(content) is True


def test_is_review_findings_template_real_content_with_approve() -> None:
    content = "# Review Findings\n\n## Critical\n\nNone.\n\n## Verdict: APPROVE\n\n[x] APPROVE\n"
    assert _is_review_findings_template(content) is False


def test_is_review_findings_template_real_content_with_request_changes() -> None:
    content = "# Review Findings\n\n## Critical\n\nHere are issues.\n\n## Verdict: REQUEST CHANGES\n"
    assert _is_review_findings_template(content) is False


# =============================================================================
# verify_artifacts — build phase: PASS cases
# =============================================================================


def test_verify_artifacts_build_pass() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        todo_dir = _make_todo_dir(tmpdir, slug)
        _write_state(todo_dir, build="complete")
        _write_impl_plan(todo_dir, all_checked=True)
        _write_checklist_build(todo_dir, checked=True)

        with patch("subprocess.run", side_effect=_mock_commits_exist(True)):
            passed, report = verify_artifacts(tmpdir, slug, "build")

    assert passed is True
    assert "PASS" in report
    assert "FAIL" not in report


# =============================================================================
# verify_artifacts — build phase: FAIL cases
# =============================================================================


def test_verify_artifacts_build_fail_missing_state() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        _make_todo_dir(tmpdir, slug)
        # No state.yaml written

        with patch("subprocess.run", side_effect=_mock_commits_exist(True)):
            passed, report = verify_artifacts(tmpdir, slug, "build")

    assert passed is False
    assert "state.yaml does not exist" in report


def test_verify_artifacts_build_fail_state_pending() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        todo_dir = _make_todo_dir(tmpdir, slug)
        _write_state(todo_dir, build="pending")
        _write_impl_plan(todo_dir, all_checked=True)
        _write_checklist_build(todo_dir, checked=True)

        with patch("subprocess.run", side_effect=_mock_commits_exist(True)):
            passed, report = verify_artifacts(tmpdir, slug, "build")

    assert passed is False
    assert "still pending" in report


def test_verify_artifacts_build_fail_unchecked_tasks() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        todo_dir = _make_todo_dir(tmpdir, slug)
        _write_state(todo_dir, build="complete")
        _write_impl_plan(todo_dir, all_checked=False)
        _write_checklist_build(todo_dir, checked=True)

        with patch("subprocess.run", side_effect=_mock_commits_exist(True)):
            passed, report = verify_artifacts(tmpdir, slug, "build")

    assert passed is False
    assert "unchecked task" in report


def test_verify_artifacts_build_fail_no_commits() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        todo_dir = _make_todo_dir(tmpdir, slug)
        _write_state(todo_dir, build="complete")
        _write_impl_plan(todo_dir, all_checked=True)
        _write_checklist_build(todo_dir, checked=True)

        with patch("subprocess.run", side_effect=_mock_commits_exist(False)):
            passed, report = verify_artifacts(tmpdir, slug, "build")

    assert passed is False
    assert "no build commits" in report


def test_verify_artifacts_build_fail_empty_checklist() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        todo_dir = _make_todo_dir(tmpdir, slug)
        _write_state(todo_dir, build="complete")
        _write_impl_plan(todo_dir, all_checked=True)
        _write_checklist_build(todo_dir, checked=False)

        with patch("subprocess.run", side_effect=_mock_commits_exist(True)):
            passed, report = verify_artifacts(tmpdir, slug, "build")

    assert passed is False
    assert "no checked items" in report


def test_verify_artifacts_build_fail_missing_impl_plan() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        todo_dir = _make_todo_dir(tmpdir, slug)
        _write_state(todo_dir, build="complete")
        # No implementation-plan.md
        _write_checklist_build(todo_dir, checked=True)

        with patch("subprocess.run", side_effect=_mock_commits_exist(True)):
            passed, report = verify_artifacts(tmpdir, slug, "build")

    assert passed is False
    assert "implementation-plan.md does not exist" in report


# =============================================================================
# verify_artifacts — review phase: PASS cases
# =============================================================================


def test_verify_artifacts_review_pass_approve() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        todo_dir = _make_todo_dir(tmpdir, slug)
        _write_state(todo_dir, review="approved")
        _write_review_findings(todo_dir, verdict="APPROVE")
        _write_checklist_review(todo_dir, checked=True)

        passed, report = verify_artifacts(tmpdir, slug, "review")

    assert passed is True
    assert "FAIL" not in report


def test_verify_artifacts_review_pass_request_changes() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        todo_dir = _make_todo_dir(tmpdir, slug)
        _write_state(todo_dir, review="changes_requested")
        _write_review_findings(todo_dir, verdict="REQUEST CHANGES")
        _write_checklist_review(todo_dir, checked=True)

        passed, report = verify_artifacts(tmpdir, slug, "review")

    assert passed is True
    assert "FAIL" not in report


# =============================================================================
# verify_artifacts — review phase: FAIL cases
# =============================================================================


def test_verify_artifacts_review_fail_template_findings() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        todo_dir = _make_todo_dir(tmpdir, slug)
        _write_state(todo_dir, review="approved")
        _write_review_findings(todo_dir, template=True)
        _write_checklist_review(todo_dir, checked=True)

        passed, report = verify_artifacts(tmpdir, slug, "review")

    assert passed is False
    assert "unfilled template" in report


def test_verify_artifacts_review_fail_missing_verdict() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        todo_dir = _make_todo_dir(tmpdir, slug)
        _write_state(todo_dir, review="approved")
        # Findings with real content but no verdict keyword
        (todo_dir / "review-findings.md").write_text(
            "# Review Findings\n\n## Critical\n\nSome long finding text here.\n",
            encoding="utf-8",
        )
        _write_checklist_review(todo_dir, checked=True)

        passed, report = verify_artifacts(tmpdir, slug, "review")

    assert passed is False
    assert "missing verdict" in report


def test_verify_artifacts_review_fail_missing_findings_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        todo_dir = _make_todo_dir(tmpdir, slug)
        _write_state(todo_dir, review="approved")
        # No review-findings.md
        _write_checklist_review(todo_dir, checked=True)

        passed, report = verify_artifacts(tmpdir, slug, "review")

    assert passed is False
    assert "review-findings.md does not exist" in report


def test_verify_artifacts_review_fail_state_pending() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        todo_dir = _make_todo_dir(tmpdir, slug)
        _write_state(todo_dir, review="pending")
        _write_review_findings(todo_dir, verdict="APPROVE")
        _write_checklist_review(todo_dir, checked=True)

        passed, report = verify_artifacts(tmpdir, slug, "review")

    assert passed is False
    assert "expected 'approved' or 'changes_requested'" in report


def test_verify_artifacts_review_fail_empty_review_checklist() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        todo_dir = _make_todo_dir(tmpdir, slug)
        _write_state(todo_dir, review="approved")
        _write_review_findings(todo_dir, verdict="APPROVE")
        _write_checklist_review(todo_dir, checked=False)

        passed, report = verify_artifacts(tmpdir, slug, "review")

    assert passed is False
    assert "no checked items" in report


# =============================================================================
# verify_artifacts — general checks
# =============================================================================


def test_verify_artifacts_fail_malformed_state_yaml() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        todo_dir = _make_todo_dir(tmpdir, slug)
        (todo_dir / "state.yaml").write_text("{ not: [valid: yaml", encoding="utf-8")
        _write_impl_plan(todo_dir, all_checked=True)
        _write_checklist_build(todo_dir, checked=True)

        with patch("subprocess.run", side_effect=_mock_commits_exist(True)):
            passed, report = verify_artifacts(tmpdir, slug, "build")

    assert passed is False
    assert "not parseable" in report


def test_verify_artifacts_fail_state_yaml_not_mapping() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        todo_dir = _make_todo_dir(tmpdir, slug)
        (todo_dir / "state.yaml").write_text("- item1\n- item2\n", encoding="utf-8")
        _write_impl_plan(todo_dir, all_checked=True)
        _write_checklist_build(todo_dir, checked=True)

        with patch("subprocess.run", side_effect=_mock_commits_exist(True)):
            passed, report = verify_artifacts(tmpdir, slug, "build")

    assert passed is False
    assert "not parseable" in report


def test_verify_artifacts_unknown_phase() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        slug = "my-slug"
        todo_dir = _make_todo_dir(tmpdir, slug)
        _write_state(todo_dir)

        passed, report = verify_artifacts(tmpdir, slug, "unknown-phase")

    assert passed is False
    assert "unknown phase" in report
