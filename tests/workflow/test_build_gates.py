"""Functional tests for the native build-gate test runner.

Drives the public ``run_build_gates`` entry against real temp worktrees whose
Makefiles carry real ``test`` targets — the gate's whole contract is executing
the project's native button as a subprocess, so the tests exercise that real
boundary end to end with no fakes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.core.next_machine import build_gates
from teleclaude.core.next_machine.build_gates import run_build_gates

pytestmark = pytest.mark.functional

# Gate status tokens the runner emits; identity, not prose, is the contract.
_FAILED_MARKER = "GATE FAILED"
_PASSED_MARKER = "GATE PASSED"
_TIMEOUT_EXIT = "exit 124"
_MISSING_TARGET_TOKEN = "make test"
_FAILURE_PROBE = "boom"
_TIMEOUT_SECONDS = 1
_TIMEOUT_MESSAGE = f"timed out after {_TIMEOUT_SECONDS}s"


def _worktree_with_test_target(root: Path, recipe: str) -> Path:
    """Write a Makefile whose `test` target runs the given shell recipe."""
    (root / "Makefile").write_text(f"test:\n\t@{recipe}\n", encoding="utf-8")
    return root


def test_missing_make_test_target_fails_closed(tmp_path: Path) -> None:
    # No Makefile at all: the native contract requires a `test` target, so the
    # gate must block instead of waving the build through with zero tests run.
    passed, output = run_build_gates(str(tmp_path), "slug")

    assert passed is False
    assert _FAILED_MARKER in output
    assert _MISSING_TARGET_TOKEN in output


def test_passing_make_test_passes(tmp_path: Path) -> None:
    _worktree_with_test_target(tmp_path, "echo all green")

    passed, output = run_build_gates(str(tmp_path), "slug")

    assert passed is True
    assert _PASSED_MARKER in output


def test_failing_make_test_fails_with_output_tail(tmp_path: Path) -> None:
    _worktree_with_test_target(tmp_path, f"echo {_FAILURE_PROBE}; exit 3")

    passed, output = run_build_gates(str(tmp_path), "slug")

    assert passed is False
    assert _FAILED_MARKER in output
    assert _FAILURE_PROBE in output


def test_platform_env_is_stripped_from_the_test_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The project must resolve its own environment: platform interpreter
    # variables never reach the native test run.
    monkeypatch.setenv("VIRTUAL_ENV", "/platform/venv")
    _worktree_with_test_target(tmp_path, 'test -z "$$VIRTUAL_ENV"')

    passed, _ = run_build_gates(str(tmp_path), "slug")

    assert passed is True


@pytest.mark.process
def test_wedged_make_test_is_group_killed_at_the_ceiling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_gates, "_TEST_GATE_TIMEOUT_SECONDS", _TIMEOUT_SECONDS)
    _worktree_with_test_target(tmp_path, "sleep 30")

    passed, output = run_build_gates(str(tmp_path), "slug")

    assert passed is False
    assert _FAILED_MARKER in output
    assert _TIMEOUT_EXIT in output
    assert _TIMEOUT_MESSAGE in output
