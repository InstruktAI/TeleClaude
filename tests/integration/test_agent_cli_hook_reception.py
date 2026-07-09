"""Functional coverage for the agent CLI hook receiver bootstrap."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/integration/agent-cli-hook-reception"
_RECEIVER = Path(__file__).resolve().parents[2] / "teleclaude" / "hooks" / "receiver" / "__main__.py"


@pytest.mark.process
@pytest.mark.spec(_SPEC, "UC-R7")
def test_receiver_bootstraps_when_the_resolved_python_is_not_the_project_venv(tmp_path: Path) -> None:
    """The receiver re-execs under the project venv and imports its dependencies.

    ``-S`` skips ``site``, which both hides the editable install of ``teleclaude`` and
    makes ``sys.prefix`` resolve to the base interpreter, so the venv re-exec branch
    fires. ``-E`` ignores ``PYTHONPATH``. Together they reproduce an agent CLI invoking
    the receiver where the resolved Python is the system Python. Without ``-S`` the
    editable install satisfies the import and this test can never fail.
    """
    result = subprocess.run(
        [sys.executable, "-S", "-E", str(_RECEIVER), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip()
