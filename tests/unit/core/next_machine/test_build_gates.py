"""Characterization tests for build gate orchestration helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from teleclaude.core.next_machine.build_gates import (
    _count_test_failures,
    check_file_has_content,
    format_build_gate_failure,
    run_build_gates,
)


class _Result:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_count_test_failures_returns_zero_when_summary_is_missing() -> None:
    assert _count_test_failures("collection completed with warnings only") == 0


def test_check_file_has_content_rejects_scaffold_templates_and_accepts_authored_content(tmp_path: Path) -> None:
    scaffold = tmp_path / "todos" / "slug" / "requirements.md"
    scaffold.parent.mkdir(parents=True)
    scaffold.write_text("# Requirements\n\n- [ ] Define the intended outcome\n", encoding="utf-8")

    authored = tmp_path / "todos" / "slug" / "implementation-plan.md"
    authored.write_text("# Plan\n\nImplement the state transition and validate it.\n", encoding="utf-8")

    assert check_file_has_content(str(tmp_path), "todos/slug/requirements.md") is False
    assert check_file_has_content(str(tmp_path), "todos/slug/implementation-plan.md") is True


def test_run_build_gates_retries_last_failed_tests_before_failing_the_gate(tmp_path: Path) -> None:
    pytest_path = tmp_path / ".venv" / "bin" / "pytest"
    pytest_path.parent.mkdir(parents=True)
    pytest_path.write_text("", encoding="utf-8")

    with (
        patch("subprocess.run") as run,
        patch("teleclaude.cli.demo_validation.validate_demo", return_value=(True, False, "demo ok")),
    ):
        run.side_effect = [
            _Result(returncode=1, stdout="1 failed, 10 passed", stderr=""),
            _Result(returncode=0, stdout="retry pass", stderr=""),
        ]

        passed, output = run_build_gates(str(tmp_path), "slug")

    assert passed is True
    assert "retry passed after 1 flaky failure(s)" in output
    assert run.call_args_list[1].args[0] == [str(pytest_path), "--lf", "-q"]


def test_format_build_gate_failure_keeps_gate_output_and_next_call() -> None:
    message = format_build_gate_failure("slug", "GATE FAILED: make test", "telec todo work slug")

    assert "BUILD GATES FAILED: slug" in message
    assert "GATE FAILED: make test" in message
    assert "Call telec todo work slug" in message
