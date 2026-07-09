"""Functional test pinning guardrails subprocess interpreter selection.

Prevents the regression: a guardrails-lane step that imports teleclaude must
run under the bundled TeleClaude checkout's venv interpreter, never under
whichever interpreter launched telec — the launcher may lack teleclaude's
runtime dependencies (pyyaml, pydantic) and die on import.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import teleclaude.quality.lint as lint_module
from teleclaude.paths import REPO_ROOT

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/agent_runtime/quality-runner-process-groups"
_LAUNCHER_SENTINEL = "/no/teleclaude/deps/python-sentinel"
_SHELL_SCRIPT_SUFFIX = ".sh"


@pytest.mark.spec(_SPEC, "UC-CQD2")
def test_guardrails_lane_uses_bundled_interpreter_not_the_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "executable", _LAUNCHER_SENTINEL)
    monkeypatch.setattr(lint_module, "_pipeline_ctx", [tmp_path])

    invocations: list[list[str]] = []

    def fake_run(cmd: list[str], *_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        invocations.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    lint_module.run_pipeline([], run_all=True)

    expected_python = str(REPO_ROOT / ".venv" / "bin" / "python")
    python_launched = [cmd for cmd in invocations if not cmd[0].endswith(_SHELL_SCRIPT_SUFFIX)]
    assert python_launched, f"expected at least one python-launched guardrails step, got: {invocations}"
    for cmd in python_launched:
        assert cmd[0] == expected_python, f"guardrails step launched under wrong interpreter: {cmd}"
        assert cmd[0] != _LAUNCHER_SENTINEL
