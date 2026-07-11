"""Process-tier test for the native build-gate timeout ceiling.

Drives the public ``run_build_gates`` entry against a real temp worktree whose
Makefile wedges its ``test`` target, proving the gate group-kills the run at the
ceiling instead of hanging.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.core.next_machine import build_gates
from teleclaude.core.next_machine.build_gates import run_build_gates

pytestmark = pytest.mark.process

_FAILED_MARKER = "GATE FAILED"
_TIMEOUT_EXIT = "exit 124"
_TIMEOUT_SECONDS = 1
_TIMEOUT_MESSAGE = f"timed out after {_TIMEOUT_SECONDS}s"


def _worktree_with_test_target(root: Path, recipe: str) -> Path:
    """Write a Makefile whose `test` target runs the given shell recipe."""
    (root / "Makefile").write_text(f"test:\n\t@{recipe}\n", encoding="utf-8")
    return root


def test_wedged_make_test_is_group_killed_at_the_ceiling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_gates, "_TEST_GATE_TIMEOUT_SECONDS", _TIMEOUT_SECONDS)
    _worktree_with_test_target(tmp_path, "sleep 30")

    passed, output = run_build_gates(str(tmp_path), "slug")

    assert passed is False
    assert _FAILED_MARKER in output
    assert _TIMEOUT_EXIT in output
    assert _TIMEOUT_MESSAGE in output
