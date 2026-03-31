"""Characterization tests for build gate orchestration helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from teleclaude.core.next_machine.build_gates import (
    _collect_scoped_test_targets,
    _count_test_failures,
    _PytestRunResult,
    run_build_gates,
)
from teleclaude.core.next_machine.path_checks import check_file_has_content


class _FakeGit:
    """Minimal git facade for diff-scope tests."""

    def merge_base(self, *_args: str) -> str:
        """Return a stable merge base for the fake worktree."""
        return "base-sha"

    def diff(self, *_args: str) -> str:
        """Return a deterministic changed-file set."""
        return "\n".join(
            [
                "teleclaude/foo/bar.py",
                "tools/lint/guardrails.py",
                "tests/integration/test_smoke.py",
                "README.md",
            ]
        )


def test_count_test_failures_returns_zero_when_summary_is_missing() -> None:
    """Missing pytest failure summaries should parse as zero failures."""
    assert _count_test_failures("collection completed with warnings only") == 0


def test_check_file_has_content_rejects_scaffold_templates_and_accepts_authored_content(tmp_path: Path) -> None:
    """Scaffold placeholders fail content checks while authored files pass."""
    scaffold = tmp_path / "todos" / "slug" / "requirements.md"
    scaffold.parent.mkdir(parents=True)
    scaffold.write_text("# Requirements\n\n- [ ] Define the intended outcome\n", encoding="utf-8")

    authored = tmp_path / "todos" / "slug" / "implementation-plan.md"
    authored.write_text("# Plan\n\nImplement the state transition and validate it.\n", encoding="utf-8")

    assert check_file_has_content(str(tmp_path), "todos/slug/requirements.md") is False
    assert check_file_has_content(str(tmp_path), "todos/slug/implementation-plan.md") is True


def test_check_file_has_content_accepts_from_main_marker_content(tmp_path: Path) -> None:
    """From-main marker content counts as authored work."""
    from_main_requirements = tmp_path / "todos" / "slug" / "requirements.md"
    from_main_requirements.parent.mkdir(parents=True)
    from_main_requirements.write_text(
        "<!-- from-main: inline work delivered under human supervision -->\n# Requirements: slug\n",
        encoding="utf-8",
    )

    assert check_file_has_content(str(tmp_path), "todos/slug/requirements.md") is True


def test_collect_scoped_test_targets_maps_changed_sources_and_tests(tmp_path: Path) -> None:
    """Diff-scoped test selection includes changed tests and mirrored companions."""
    (tmp_path / "tests" / "unit" / "foo").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "foo" / "test_bar.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "unit" / "tools" / "lint").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "tools" / "lint" / "test_guardrails.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "integration").mkdir(parents=True)
    (tmp_path / "tests" / "integration" / "test_smoke.py").write_text("", encoding="utf-8")

    with patch("teleclaude.core.next_machine.build_gates.Repo", return_value=SimpleNamespace(git=_FakeGit())):
        targets = _collect_scoped_test_targets(str(tmp_path))

    assert targets == [
        "tests/integration/test_smoke.py",
        "tests/unit/foo/test_bar.py",
        "tests/unit/tools/lint/test_guardrails.py",
    ]


def test_run_build_gates_skips_when_no_scoped_tests_are_selected(tmp_path: Path) -> None:
    """Zero selected tests should skip the gate instead of failing it."""
    with (
        patch("teleclaude.core.next_machine.build_gates._collect_scoped_test_targets", return_value=[]),
        patch("teleclaude.cli.demo_validation.validate_demo", return_value=(True, False, "demo ok")),
    ):
        passed, output = run_build_gates(str(tmp_path), "slug")

    assert passed is True
    assert "GATE SKIPPED: scoped tests" in output


def test_run_build_gates_retries_last_failed_tests_before_failing_the_gate(tmp_path: Path) -> None:
    """Low-count scoped test failures should trigger a last-failed retry."""
    with (
        patch(
            "teleclaude.core.next_machine.build_gates._collect_scoped_test_targets",
            return_value=["tests/unit/foo/test_bar.py"],
        ),
        patch("teleclaude.core.next_machine.build_gates._run_pytest_in_child_process") as run_pytest,
        patch("teleclaude.cli.demo_validation.validate_demo", return_value=(True, False, "demo ok")),
    ):
        run_pytest.side_effect = [
            _PytestRunResult(returncode=1, stdout="1 failed, 10 passed", stderr=""),
            _PytestRunResult(returncode=0, stdout="retry pass", stderr=""),
        ]

        passed, output = run_build_gates(str(tmp_path), "slug")

    assert passed is True
    assert output
    assert run_pytest.call_args_list[1].args[1] == ["--lf", "-m", "not expensive", "-q"]
