"""Build gates — test execution and artifact verification.

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

from teleclaude.core.next_machine._types import REVIEW_APPROVE_MARKER, PhaseName, StateValue
from teleclaude.core.next_machine.path_checks import (
    _has_from_main_marker,
)
from teleclaude.core.next_machine.state_io import _get_todos_db_sync
from teleclaude.git import GitCommandError, Repo

logger = get_logger(__name__)

GateCheck = Callable[[Path, list[str]], bool]
_PYTEST_GATE_TIMEOUT_SECONDS = 300
_PYTEST_RETRY_TIMEOUT_SECONDS = 120


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
    os.environ["TELECLAUDE_CONFIG_PATH"] = os.environ.get("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")
    os.environ["TELECLAUDE_ENV_PATH"] = os.environ.get("TELECLAUDE_ENV_PATH", "tests/integration/.env")

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
    except BaseException as exc:  # pylint: disable=broad-exception-caught
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
    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue()
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


def run_build_gates(worktree_cwd: str, slug: str) -> tuple[bool, str]:  # pylint: disable=unused-argument
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
                [*test_targets, "-m", "not expensive", "-q"],
                timeout_seconds=_PYTEST_GATE_TIMEOUT_SECONDS,
            )
        if test_result is not None and test_result.returncode != 0:
            output = test_result.stdout[-2000:] if test_result.stdout else ""
            stderr = test_result.stderr[-500:] if test_result.stderr else ""
            failure_count = _count_test_failures(test_result.stdout)
            if 1 <= failure_count <= 2:
                retry_result = _run_pytest_in_child_process(
                    worktree_cwd,
                    ["--lf", "-m", "not expensive", "-q"],
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
3. When the builder reports done:
   a. telec todo mark-phase {slug} --phase build --status complete   b. Call {next_call}
   If gates fail again, repeat from step 1."""


def _extract_checklist_section(content: str, section_name: str) -> str | None:
    """Extract content of a specific ## section from a checklist markdown file.

    Returns the text from the ## {section_name} header to the next ## header,
    or None if the section is not found.
    """
    lines = content.splitlines()
    in_section = False
    section_lines: list[str] = []
    for line in lines:
        if re.match(rf"^##\s+{re.escape(section_name)}", line):
            in_section = True
            continue
        if in_section:
            if re.match(r"^##\s+", line):
                break
            section_lines.append(line)
    if not in_section:
        return None
    return "\n".join(section_lines)


def _is_review_findings_template(content: str) -> bool:
    """Check if review-findings.md looks like an unfilled scaffold template.

    Returns True when the file is too short to contain real findings or has a
    Findings header but no verdict, which indicates an unfilled stub.
    """
    if len(content.strip()) < 50:
        return True
    # Template marker: has a Findings section but no verdict written yet
    has_findings_header = bool(re.search(r"^##\s+Findings\s*$", content, re.MULTILINE))
    has_verdict = bool(re.search(r"APPROVE|REQUEST CHANGES", content))
    if has_findings_header and not has_verdict:
        return True
    return False


def _read_artifact_content(todo_base: Path, artifact_name: str) -> str | None:
    """Read artifact content from todos.db. Returns None if not found."""
    # todo_base is Path(worktree_cwd) / "todos" / slug in old code;
    # extract cwd and slug to resolve DB path.
    slug = todo_base.name
    cwd = str(todo_base.parent.parent)
    db_name = artifact_name.removesuffix(".md") if artifact_name.endswith(".md") else artifact_name
    db = _get_todos_db_sync(cwd)
    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        row = conn.execute(
            "SELECT content FROM todo_artifacts WHERE slug = ? AND name = ? LIMIT 1",  # guard: raw-sql
            (slug, db_name),
        ).fetchone()
        return str(row[0]) if row else None
    finally:
        conn.close()


def verify_artifacts(worktree_cwd: str, slug: str, phase: str, *, is_bug: bool = False) -> tuple[bool, str]:
    """Mechanically verify artifacts for a given phase.

    Checks presence and completeness of artifacts for build or review phase.
    Does not replace functional gates (scoped tests) — complements
    them with artifact presence and consistency checks.

    When is_bug=True, checks bug.md instead of implementation-plan.md and
    quality-checklist.md (bugs don't have those artifacts).

    Returns:
        (passed: bool, report: str) where report lists each check with PASS/FAIL.
    """
    results: list[str] = []
    todo_base = Path(worktree_cwd) / "todos" / slug

    all_passed = _verify_state_yaml(todo_base, phase, results)

    if phase == PhaseName.BUILD.value:
        all_passed = _verify_build_artifacts(worktree_cwd, todo_base, is_bug, results) and all_passed
    elif phase == PhaseName.REVIEW.value:
        all_passed = _verify_review_artifacts(todo_base, is_bug, results) and all_passed
    else:
        all_passed = False
        results.append(f"FAIL: unknown phase '{phase}' (expected 'build' or 'review')")

    summary = "PASS" if all_passed else "FAIL"
    report = f"Artifact verification [{summary}] for {slug} phase={phase}\n" + "\n".join(results)
    return all_passed, report


def _verify_state_yaml(todo_base: Path, phase: str, results: list[str]) -> bool:
    """Validate state presence and phase consistency via DB."""
    try:
        from teleclaude.core.next_machine.state_io import read_phase_state  # pylint: disable=import-outside-toplevel

        cwd = str(todo_base.parent.parent)
        slug = todo_base.name
        state = read_phase_state(cwd, slug)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        results.append(f"FAIL: state is not readable: {exc}")
        return False

    results.append("PASS: state is readable")
    return _verify_phase_consistency(state, phase, results)


def _verify_phase_consistency(state: dict[str, StateValue], phase: str, results: list[str]) -> bool:
    """Verify the current state.yaml phase marker matches the requested gate."""
    current = str(state.get("current", ""))

    if phase == PhaseName.BUILD.value:
        build_states = {
            "build_started",
            "build_complete",
            "review_pending",
            "review_changes_requested",
            "review_approved",
            "finalize_ready",
            "finalize_handed_off",
        }
        if current not in build_states:
            results.append(f"FAIL: state.yaml current={current!r} — not in build phase")
            return False
        results.append(f"PASS: state.yaml current={current!r}")
        return True

    if phase == PhaseName.REVIEW.value:
        if current not in ("review_approved", "review_changes_requested"):
            results.append(
                f"FAIL: state.yaml current={current!r} (expected review_approved or review_changes_requested)"
            )
            return False
        results.append(f"PASS: state.yaml current={current!r}")
        return True

    return True


def _verify_build_artifacts(worktree_cwd: str, todo_base: Path, is_bug: bool, results: list[str]) -> bool:
    """Verify build-phase artifacts, commits, and checklist gates."""
    checks: list[GateCheck] = [_verify_bug_report if is_bug else _verify_implementation_plan]
    checks.append(_build_commit_check(worktree_cwd, results))
    if not is_bug:
        checks.append(_checklist_gate_check(todo_base, "Build Gates", results))
    return all(check(todo_base, results) for check in checks)


def _build_commit_check(worktree_cwd: str, results: list[str]) -> GateCheck:
    def _check(_todo_base: Path, _results: list[str]) -> bool:
        return _verify_build_commits(worktree_cwd, results)

    return _check


def _verify_bug_report(todo_base: Path, results: list[str]) -> bool:
    """Verify bug artifact exists and contains non-template content."""
    content = _read_artifact_content(todo_base, "bug")
    if content is None:
        results.append("FAIL: bug artifact does not exist")
        return False
    stripped = content.strip()
    if not stripped or (stripped.startswith("<!--") and stripped.endswith("-->")):
        results.append("FAIL: bug artifact is empty or contains only a template comment")
        return False
    results.append("PASS: bug artifact exists and has content")
    return True


def _verify_implementation_plan(todo_base: Path, results: list[str]) -> bool:
    """Verify implementation-plan artifact exists and all tasks are checked off."""
    content = _read_artifact_content(todo_base, "implementation-plan")
    if content is None:
        results.append("FAIL: implementation-plan artifact does not exist")
        return False
    if _has_from_main_marker(content):
        results.append("PASS: implementation-plan — from-main marker (human-supervised)")
        return True
    unchecked = re.findall(r"^\s*-\s*\[ \]", content, re.MULTILINE)
    if unchecked:
        results.append(
            f"FAIL: implementation-plan has {len(unchecked)} unchecked task(s) (all must be [x] before review)"
        )
        return False
    results.append("PASS: implementation-plan — all tasks checked [x]")
    return True


def _verify_build_commits(worktree_cwd: str, results: list[str]) -> bool:
    """Verify the worktree contains at least one build commit ahead of main."""
    try:
        repo = Repo(worktree_cwd)
        try:
            base = repo.git.merge_base("HEAD", "main").strip()
            log_output = repo.git.log("--oneline", f"{base}..HEAD")
        except GitCommandError:
            log_output = repo.git.log("--oneline", "-1")
        if log_output.strip():
            results.append("PASS: build commits exist on worktree branch")
            return True
        results.append("FAIL: no build commits found on worktree branch beyond main")
        return False
    except (GitCommandError, OSError, Exception) as exc:  # pylint: disable=broad-exception-caught
        results.append(f"FAIL: could not verify commits: {exc}")
        return False


def _verify_review_artifacts(todo_base: Path, is_bug: bool, results: list[str]) -> bool:
    """Verify review findings and checklist gates for review dispatch."""
    checks: list[GateCheck] = [_review_findings_check(todo_base, results)]
    if not is_bug:
        checks.append(_checklist_gate_check(todo_base, "Review Gates", results))
    return all(check(todo_base, results) for check in checks)


def _review_findings_check(todo_base: Path, results: list[str]) -> GateCheck:
    def _check(_unused_todo_base: Path, _unused_results: list[str]) -> bool:
        return _verify_review_findings(todo_base, results)

    return _check


def _checklist_gate_check(todo_base: Path, section: str, results: list[str]) -> GateCheck:
    def _check(_unused_todo_base: Path, _unused_results: list[str]) -> bool:
        return _verify_checklist_section(todo_base, section, results)

    return _check


def _verify_review_findings(todo_base: Path, results: list[str]) -> bool:
    """Verify review-findings artifact exists, is filled in, and includes a verdict."""
    content = _read_artifact_content(todo_base, "review-findings")
    if content is None:
        results.append("FAIL: review-findings artifact does not exist")
        return False

    passed = True
    if _is_review_findings_template(content):
        results.append("FAIL: review-findings appears to be an unfilled template")
        passed = False
    else:
        results.append("PASS: review-findings has real content (not template)")

    has_approve = REVIEW_APPROVE_MARKER in content
    has_request_changes = "REQUEST CHANGES" in content
    if not (has_approve or has_request_changes):
        results.append("FAIL: review-findings missing verdict (APPROVE or REQUEST CHANGES)")
        return False

    verdict = "APPROVE" if has_approve else "REQUEST CHANGES"
    results.append(f"PASS: review-findings verdict: {verdict}")
    return passed


def _verify_checklist_section(todo_base: Path, section_name: str, results: list[str]) -> bool:
    """Verify a checklist section exists and has at least one checked item."""
    content = _read_artifact_content(todo_base, "quality-checklist")
    if content is None:
        results.append("FAIL: quality-checklist artifact does not exist")
        return False

    if _has_from_main_marker(content):
        results.append(f"PASS: quality-checklist {section_name} — from-main marker (human-supervised)")
        return True

    section = _extract_checklist_section(content, section_name)
    if section is None:
        results.append(f"FAIL: quality-checklist missing '## {section_name}' section")
        return False

    checked = re.findall(r"^\s*-\s*\[x\]", section, re.MULTILINE | re.IGNORECASE)
    if not checked:
        results.append(f"FAIL: quality-checklist {section_name} — no checked items")
        return False

    results.append(f"PASS: quality-checklist {section_name} — {len(checked)} checked item(s)")
    return True
