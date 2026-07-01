"""Build gates — pytest execution for the worktree scoped test set.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import contextlib
import io
import multiprocessing as mp
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple, TypedDict, cast

import pytest
from instrukt_ai_logging import get_logger
from sqlmodel import SQLModel
from sqlmodel.main import default_registry

from teleclaude.git import GitCommandError, Repo

logger = get_logger(__name__)

GateCheck = Callable[[Path, list[str]], bool]
_PYTEST_GATE_TIMEOUT_SECONDS = 300
_PYTEST_RETRY_TIMEOUT_SECONDS = 120
# pytest's exit status when collection finds no tests (EXIT_NOTESTSCOLLECTED).
_PYTEST_NO_TESTS_COLLECTED = 5


class _PytestRunResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


class _PytestResultPayload(TypedDict):
    returncode: int
    stdout: str
    stderr: str


def _count_test_failures(output: str) -> int:
    """Parse pytest summary line for failure count. Returns 0 if not found."""
    match = re.search(r"(\d+) failed", output)
    return int(match.group(1)) if match else 0


def _mirror_test_path(source_path: str) -> str | None:
    """Map a changed source file to its expected unit-test companion."""
    prefix_map = {
        "teleclaude/": "tests/unit/",
        "tools/": "tests/unit/tools/",
        "scripts/": "tests/unit/scripts/",
        "bin/": "tests/unit/bin/",
    }
    for source_prefix, test_prefix in prefix_map.items():
        if not source_path.startswith(source_prefix):
            continue
        if not source_path.endswith((".py", ".pyi")):
            return None
        without_prefix = source_path.removeprefix(source_prefix)
        parent, filename = without_prefix.rsplit("/", 1) if "/" in without_prefix else ("", without_prefix)
        stem = Path(filename).stem
        test_filename = f"test_{stem}.py"
        if parent:
            return f"{test_prefix}{parent}/{test_filename}"
        return f"{test_prefix}{test_filename}"
    return None


def _collect_scoped_test_targets(worktree_cwd: str) -> list[str]:
    """Return diff-scoped test files for the current worktree."""
    repo = Repo(worktree_cwd)
    merge_base = repo.git.merge_base("HEAD", "main").strip()
    changed_files = [
        line.strip() for line in repo.git.diff("--name-only", f"{merge_base}..HEAD").splitlines() if line.strip()
    ]

    targets: set[str] = set()
    worktree_root = Path(worktree_cwd)
    for rel_path in changed_files:
        candidate = worktree_root / rel_path
        if (
            rel_path.startswith("tests/")
            and candidate.is_file()
            and candidate.name.startswith("test_")
            and candidate.suffix == ".py"
        ):
            targets.add(rel_path)
            continue

        companion = _mirror_test_path(rel_path)
        if companion is None:
            continue
        if (worktree_root / companion).is_file():
            targets.add(companion)

    return sorted(targets)


def _reset_pytest_worker_import_state() -> None:
    """Drop cached TeleClaude modules and reset SQLModel globals before pytest import collection.

    The gate worker can start in a process that already imported TeleClaude
    modules from a different checkout. Removing only ``sys.modules`` is not
    enough because SQLModel keeps table metadata and mapped classes in global
    registries. Those leftovers can make a second import of the todos models
    fail with SQLAlchemy table redefinition errors.
    """
    for name in list(sys.modules):
        if name == "teleclaude" or name.startswith("teleclaude.") or name == "tests" or name.startswith("tests."):
            sys.modules.pop(name, None)
    SQLModel.metadata.clear()
    default_registry.dispose()


def _pytest_worker(worktree_cwd: str, pytest_args: list[str], result_queue: Any) -> None:
    """Run pytest in a fresh Python process against the worktree checkout."""
    worktree_root = Path(worktree_cwd).resolve()
    canonical_root = Path(__file__).resolve().parents[3]

    _reset_pytest_worker_import_state()

    sys.path = [
        str(worktree_root),
        *[
            entry
            for entry in sys.path
            if entry and Path(entry).resolve() != canonical_root and Path(entry).resolve() != worktree_root
        ],
    ]
    os.chdir(worktree_root)

    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
            exit_code = int(pytest.main(pytest_args))
        result_queue.put(
            {
                "returncode": exit_code,
                "stdout": stdout_buffer.getvalue(),
                "stderr": stderr_buffer.getvalue(),
            }
        )
    except BaseException as exc:
        result_queue.put(
            {
                "returncode": 1,
                "stdout": stdout_buffer.getvalue(),
                "stderr": f"{stderr_buffer.getvalue()}\npytest worker error: {type(exc).__name__}: {exc}",
            }
        )


def _run_pytest_in_child_process(
    worktree_cwd: str, pytest_args: list[str], *, timeout_seconds: int
) -> _PytestRunResult:
    """Execute pytest in an isolated Python child process and capture its output."""
    # SimpleQueue has no background feeder thread, so the parent process exits
    # cleanly. mp.Queue's feeder thread blocks Py_FinalizeEx and produces zombies.
    ctx = mp.get_context("spawn")
    result_queue = ctx.SimpleQueue()
    process = ctx.Process(target=_pytest_worker, args=(worktree_cwd, pytest_args, result_queue))
    process.start()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join()
        return _PytestRunResult(
            returncode=124,
            stdout="",
            stderr=f"timed out after {timeout_seconds}s",
        )

    if not result_queue.empty():
        payload = cast(_PytestResultPayload, result_queue.get())
        return _PytestRunResult(
            returncode=payload["returncode"],
            stdout=payload["stdout"],
            stderr=payload["stderr"],
        )

    return _PytestRunResult(
        returncode=process.exitcode or 1,
        stdout="",
        stderr="pytest worker exited without reporting a result",
    )


def run_build_gates(worktree_cwd: str, slug: str) -> tuple[bool, str]:
    """Run build gates in the worktree.

    Returns (all_passed, output_details).
    """
    results: list[str] = []
    all_passed = True

    # Gate 1: Test suite
    try:
        test_targets = _collect_scoped_test_targets(worktree_cwd)
        if not test_targets:
            results.append("GATE SKIPPED: scoped tests (no changed or mapped test files)")
            test_result = None
        else:
            test_result = _run_pytest_in_child_process(
                worktree_cwd,
                [*test_targets, "-q"],
                timeout_seconds=_PYTEST_GATE_TIMEOUT_SECONDS,
            )
        if test_result is not None and test_result.returncode == _PYTEST_NO_TESTS_COLLECTED:
            # pytest exit 5 = no tests collected. For a diff-scoped fast-tier run
            # this means every changed test file was deselected by the suite's
            # marker filter — e.g. coverage that legitimately lives in the process
            # tier (run serially by `make test-meta`), which the fast tier excludes.
            # Nothing to run in the fast tier is a skip, not a failure; it mirrors
            # the no-targets skip above.
            results.append(
                "GATE SKIPPED: scoped tests (no fast-tier tests collected; coverage runs in the process tier)"
            )
        elif test_result is not None and test_result.returncode != 0:
            output = test_result.stdout[-2000:] if test_result.stdout else ""
            stderr = test_result.stderr[-500:] if test_result.stderr else ""
            failure_count = _count_test_failures(test_result.stdout)
            if 1 <= failure_count <= 2:
                retry_result = _run_pytest_in_child_process(
                    worktree_cwd,
                    ["--lf", "-q"],
                    timeout_seconds=_PYTEST_RETRY_TIMEOUT_SECONDS,
                )
                if retry_result.returncode == 0:
                    results.append(f"GATE PASSED: scoped tests (retry passed after {failure_count} flaky failure(s))")
                else:
                    all_passed = False
                    retry_output = retry_result.stdout[-1000:] if retry_result.stdout else ""
                    retry_stderr = retry_result.stderr[-500:] if retry_result.stderr else ""
                    results.append(
                        f"GATE FAILED: scoped tests (exit {test_result.returncode})\n{output}\n{stderr}"
                        f"\n--- RETRY ALSO FAILED ---\n{retry_output}\n{retry_stderr}"
                    )
            else:
                all_passed = False
                results.append(f"GATE FAILED: scoped tests (exit {test_result.returncode})\n{output}\n{stderr}")
        elif test_result is not None:
            results.append("GATE PASSED: scoped tests")
    except (GitCommandError, OSError) as exc:
        all_passed = False
        results.append(f"GATE FAILED: scoped tests (error: {exc})")

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
