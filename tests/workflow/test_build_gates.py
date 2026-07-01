"""Functional tests for the scoped build-gate test runner.

Drives the public ``run_build_gates`` entry against a real temp git repo so the
diff-scoped target collection runs for real; the only fake is the pytest child
process (a process-boundary seam), whose exit code is what the gate must
interpret.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.core.next_machine.build_gates import _PytestRunResult, run_build_gates
from teleclaude.git import Repo

pytestmark = pytest.mark.functional

_RUN_PYTEST = "teleclaude.core.next_machine.build_gates._run_pytest_in_child_process"

# Gate status tokens the runner emits; identity, not prose, is the contract.
_SKIPPED_MARKER = "GATE SKIPPED"
_FAILED_MARKER = "GATE FAILED"
_PASSED_MARKER = "GATE PASSED"


def _repo_with_scoped_test(root: Path) -> None:
    """Init a repo whose HEAD adds one scoped test file ahead of main."""
    repo = Repo.init(root)
    repo.git.checkout("-B", "main")
    repo.git.config("user.name", "Gate Test")
    repo.git.config("user.email", "gate-test@example.test")
    (root / "seed.txt").write_text("c0\n", encoding="utf-8")
    repo.git.add(".")
    repo.git.commit("-m", "C0")

    repo.git.checkout("-b", "feature")
    test_dir = root / "tests" / "sample"
    test_dir.mkdir(parents=True)
    (test_dir / "test_sample.py").write_text("def test_ok() -> None:\n    assert True\n", encoding="utf-8")
    repo.git.add(".")
    repo.git.commit("-m", "C1 add scoped test")


@pytest.fixture
def scoped_repo(tmp_path: Path) -> Iterator[Path]:
    _repo_with_scoped_test(tmp_path)
    yield tmp_path


def test_exit_5_no_tests_collected_is_skipped_not_failed(scoped_repo: Path) -> None:
    # The scoped file is real, but the fast tier deselects it (e.g. process tier),
    # so pytest returns 5 (no tests collected). The gate must treat that as a skip.
    result = _PytestRunResult(returncode=5, stdout="no tests ran", stderr="")
    with patch(_RUN_PYTEST, return_value=result):
        passed, output = run_build_gates(str(scoped_repo), "slug")

    assert passed is True
    assert _SKIPPED_MARKER in output
    assert _FAILED_MARKER not in output


def test_real_failure_still_fails(scoped_repo: Path) -> None:
    result = _PytestRunResult(returncode=1, stdout="1 failed", stderr="")
    with patch(_RUN_PYTEST, return_value=result):
        passed, output = run_build_gates(str(scoped_repo), "slug")

    assert passed is False
    assert _FAILED_MARKER in output


def test_passing_run_passes(scoped_repo: Path) -> None:
    result = _PytestRunResult(returncode=0, stdout="1 passed", stderr="")
    with patch(_RUN_PYTEST, return_value=result):
        passed, output = run_build_gates(str(scoped_repo), "slug")

    assert passed is True
    assert _PASSED_MARKER in output
