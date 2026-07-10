"""Build gates — run the project's native test suite for the worktree.

The gate pushes the project's own button: `make test`, executed as a subprocess
with the worktree as cwd, in the project's own environment. The platform never
runs project tests in-process — doing so leaks the daemon's interpreter,
site-packages, and already-imported modules into the run and can shadow the
very code under test. The Makefile owns the toolchain (language-agnostic:
Python, TypeScript, Rust alike); the gate only observes the exit code.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
from pathlib import Path
from typing import NamedTuple

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

# Ceiling only — the project's own test harness enforces its real budgets
# (tiered session timeouts); this bound exists to reap a wedged make process.
_TEST_GATE_TIMEOUT_SECONDS = 600
_OUTPUT_TAIL_CHARS = 2000
_STDERR_TAIL_CHARS = 500


class _TestRunResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


def _has_make_test_target(worktree_root: Path) -> bool:
    """Return True when the worktree's Makefile declares a `test` target."""
    makefile = worktree_root / "Makefile"
    try:
        content = makefile.read_text(encoding="utf-8")
    except OSError:
        return False
    return re.search(r"^test\s*:", content, re.MULTILINE) is not None


def _run_make_test(worktree_root: Path, *, timeout_seconds: int) -> _TestRunResult:
    """Run `make test` in the worktree's own environment and capture the result."""
    # Strip platform-environment leakage so the project resolves its own
    # interpreter and packages exactly as it would standalone.
    env = {
        key: value for key, value in os.environ.items() if key not in {"VIRTUAL_ENV", "PYTHONPATH", "PYTEST_ADDOPTS"}
    }
    env["PWD"] = str(worktree_root)
    env["TELEC_INVOCATION_CWD"] = str(worktree_root)
    # subprocess is the point of this gate: the project's native `make test`
    # must run outside the platform interpreter; no Python API provides that
    # isolation. The process group is killed on timeout so nothing leaks.
    process = subprocess.Popen(
        ["make", "test"],
        cwd=str(worktree_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
        env=env,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        stdout, stderr = process.communicate()
        return _TestRunResult(
            returncode=124,
            stdout=stdout or "",
            stderr=f"{stderr or ''}\ntimed out after {timeout_seconds}s",
        )
    return _TestRunResult(returncode=process.returncode, stdout=stdout or "", stderr=stderr or "")


def run_build_gates(worktree_cwd: str, slug: str) -> tuple[bool, str]:
    """Run build gates in the worktree.

    Returns (all_passed, output_details).
    """
    results: list[str] = []
    all_passed = True

    worktree_root = Path(worktree_cwd)
    if not _has_make_test_target(worktree_root):
        # Fail closed: the native Makefile contract requires a `test` target,
        # so its absence is a broken worktree, never a green light.
        return (
            False,
            "GATE FAILED: native tests (no `make test` target in the worktree — the native Makefile contract requires one)",
        )

    logger.info("build_gate_make_test", slug=slug, worktree=str(worktree_root))
    try:
        test_result = _run_make_test(worktree_root, timeout_seconds=_TEST_GATE_TIMEOUT_SECONDS)
    except OSError as exc:
        return False, f"GATE FAILED: native tests (error: {exc})"

    if test_result.returncode == 0:
        results.append("GATE PASSED: native tests (make test)")
    else:
        all_passed = False
        output = test_result.stdout[-_OUTPUT_TAIL_CHARS:] if test_result.stdout else ""
        stderr = test_result.stderr[-_STDERR_TAIL_CHARS:] if test_result.stderr else ""
        results.append(f"GATE FAILED: native tests (exit {test_result.returncode})\n{output}\n{stderr}")

    return all_passed, "\n".join(results)


def format_build_gate_failure(slug: str, gate_output: str, next_call: str) -> str:
    """Format a gate-failure response for the orchestrator.

    Instructs the orchestrator to send the failure details to the builder session
    (without ending it) and wait for the builder to fix and report done again.
    """
    return f"""BUILD GATES FAILED: {slug}

{gate_output}

INSTRUCTIONS FOR ORCHESTRATOR:
1. Send the above gate failure details to the builder session via telec sessions send <session_id> "<message>".
   Tell the builder which gate(s) failed and include the output.
   Do NOT end the builder session.
2. Wait for the builder to report completion again.
3. When the builder reports done, call {next_call}.
   If gates fail again, repeat from step 1."""
