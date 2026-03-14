"""Build gates — test execution, demo validation, artifact verification.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.core.next_machine._types import REVIEW_APPROVE_MARKER, PhaseName, PhaseStatus, StateValue
from teleclaude.core.next_machine.state_io import is_bug_todo

logger = get_logger(__name__)

GateCheck = Callable[[Path, list[str]], bool]


def _count_test_failures(output: str) -> int:
    """Parse pytest summary line for failure count. Returns 0 if not found."""
    match = re.search(r"(\d+) failed", output)
    return int(match.group(1)) if match else 0


def run_build_gates(worktree_cwd: str, slug: str) -> tuple[bool, str]:
    """Run build gates (tests + demo validation) in the worktree.

    Returns (all_passed, output_details).
    """
    results: list[str] = []
    all_passed = True

    # Gate 1: Test suite
    try:
        test_result = subprocess.run(
            ["make", "test"],
            cwd=worktree_cwd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if test_result.returncode != 0:
            output = test_result.stdout[-2000:] if test_result.stdout else ""
            stderr = test_result.stderr[-500:] if test_result.stderr else ""
            failure_count = _count_test_failures(test_result.stdout)
            if 1 <= failure_count <= 2:
                # Single retry for low-count flaky test failures
                venv_pytest = Path(worktree_cwd) / ".venv" / "bin" / "pytest"
                pytest_cmd = str(venv_pytest) if venv_pytest.exists() else "pytest"
                # Explicit config paths are required for pytest --lf because the
                # Makefile's `test` target sets them via its own environment; running
                # pytest directly bypasses the Makefile, so we mirror those paths here
                # to keep the retry under the same configuration as the original run.
                retry_env = {
                    **os.environ,
                    "TELECLAUDE_CONFIG_PATH": "tests/integration/config.yml",
                    "TELECLAUDE_ENV_PATH": "tests/integration/.env",
                }
                try:
                    retry_result = subprocess.run(
                        [pytest_cmd, "--lf", "-q"],
                        cwd=worktree_cwd,
                        capture_output=True,
                        text=True,
                        timeout=120,
                        env=retry_env,
                    )
                    if retry_result.returncode == 0:
                        results.append(f"GATE PASSED: make test (retry passed after {failure_count} flaky failure(s))")
                    else:
                        all_passed = False
                        retry_output = retry_result.stdout[-1000:] if retry_result.stdout else ""
                        results.append(
                            f"GATE FAILED: make test (exit {test_result.returncode})\n{output}\n{stderr}"
                            f"\n--- RETRY ALSO FAILED ---\n{retry_output}"
                        )
                except (subprocess.TimeoutExpired, OSError) as exc:
                    all_passed = False
                    results.append(
                        f"GATE FAILED: make test (exit {test_result.returncode})\n{output}\n{stderr}"
                        f"\n--- RETRY ERROR: {exc} ---"
                    )
            else:
                all_passed = False
                results.append(f"GATE FAILED: make test (exit {test_result.returncode})\n{output}\n{stderr}")
        else:
            results.append("GATE PASSED: make test")
    except subprocess.TimeoutExpired:
        all_passed = False
        results.append("GATE FAILED: make test (timed out after 300s)")
    except OSError as exc:
        all_passed = False
        results.append(f"GATE FAILED: make test (error: {exc})")

    # Gate 2: Demo structure validation (inline — no subprocess)
    if is_bug_todo(worktree_cwd, slug):
        results.append("GATE SKIPPED: demo validate (bug workflow)")
    else:
        from teleclaude.cli.demo_validation import validate_demo

        passed, is_no_demo, message = validate_demo(slug, Path(worktree_cwd))
        if not passed:
            all_passed = False
            results.append(f"GATE FAILED: demo validate\n{message}")
        elif is_no_demo:
            results.append(f"GATE WARNING: demo validate — no-demo marker used, reviewer must verify\n{message}")
        else:
            results.append(f"GATE PASSED: demo validate\n{message.strip()}")

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


def _is_scaffold_template(content: str) -> bool:
    """Check if a todo artifact is an unfilled scaffold template.

    The scaffold creator (``telec todo create``) writes all files from
    ``templates/todos/`` with placeholder content.  A file that still matches
    its scaffold shape should be treated as *not yet written* by the state
    machine so that it routes to the authoring phase rather than the review
    phase.

    Heuristic: scaffold templates are short and contain only headings,
    empty list markers (``- [ ]``, ``-``), placeholder prose from the
    template (``Define the intended outcome``, ``Summarize the approach``),
    and whitespace.  Real authored content will exceed these markers.
    """
    stripped = content.strip()
    if len(stripped) < 50:
        return True

    # Known phrases that appear only in scaffold templates.
    _SCAFFOLD_PHRASES = (
        "Define the intended outcome",
        "Summarize the approach",
        "Complete this task",
        "Add or update tests",
        "Run `make test`",
        "Run `make lint`",
        "Verify no unchecked",
        "Confirm requirements are reflected",
        "Confirm implementation tasks",
        "Document any deferrals",
        "In scope",
        "Out of scope",
    )

    remaining_lines: list[str] = []
    for line in stripped.splitlines():
        text = line.strip()
        # Skip blank lines, headings, horizontal rules
        if not text or text.startswith("#") or re.fullmatch(r"-{3,}", text):
            continue
        # Skip bare list markers (-, - [ ], - [x])
        if re.fullmatch(r"-\s*(\[[ x]?\]\s*)?", text):
            continue
        # Skip **File(s):** `` (empty file ref from impl plan template)
        if re.fullmatch(r"\*\*[^*]+\*\*\s*``", text):
            continue
        # Skip lines that consist entirely of a scaffold phrase (with optional list marker)
        bare = re.sub(r"^-\s*", "", text)
        if any(phrase in bare for phrase in _SCAFFOLD_PHRASES):
            continue
        remaining_lines.append(text)

    remaining = " ".join(remaining_lines).strip()
    return len(remaining) < 30


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


def check_file_has_content(cwd: str, relative_path: str) -> bool:
    """Check if a file exists and contains real (non-scaffold) content.

    Returns False when the file is missing or is still an unfilled scaffold
    template from ``telec todo create``.
    """
    fpath = Path(cwd) / relative_path
    if not fpath.exists():
        return False
    try:
        content = fpath.read_text(encoding="utf-8")
    except OSError:
        return False
    return not _is_scaffold_template(content)


def verify_artifacts(worktree_cwd: str, slug: str, phase: str, *, is_bug: bool = False) -> tuple[bool, str]:
    """Mechanically verify artifacts for a given phase.

    Checks presence and completeness of artifacts for build or review phase.
    Does not replace functional gates (make test, demo validate) — complements
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
    """Validate state.yaml presence, parseability, and phase consistency."""
    state_path = todo_base / "state.yaml"
    if not state_path.exists():
        results.append("FAIL: state.yaml does not exist")
        return False

    try:
        state_content = state_path.read_text(encoding="utf-8")
        raw_state = yaml.safe_load(state_content)
        if raw_state is None:
            raw_state = {}
        if not isinstance(raw_state, dict):
            raise ValueError("state.yaml content is not a mapping")
        state: dict[str, StateValue] = raw_state
    except Exception as exc:
        results.append(f"FAIL: state.yaml is not parseable: {exc}")
        return False

    results.append("PASS: state.yaml is parseable YAML")
    return _verify_phase_consistency(state, phase, results)


def _verify_phase_consistency(state: dict[str, StateValue], phase: str, results: list[str]) -> bool:
    """Verify the current state.yaml phase marker matches the requested gate."""
    if phase == PhaseName.BUILD.value:
        build_val = state.get(PhaseName.BUILD.value)
        if build_val == PhaseStatus.PENDING.value:
            results.append(f"FAIL: state.yaml build={build_val!r} — still pending, expected 'complete' or later")
            return False
        results.append(f"PASS: state.yaml build={build_val!r}")
        return True

    if phase == PhaseName.REVIEW.value:
        review_val = state.get(PhaseName.REVIEW.value)
        if review_val not in (PhaseStatus.APPROVED.value, PhaseStatus.CHANGES_REQUESTED.value):
            results.append(f"FAIL: state.yaml review={review_val!r} (expected 'approved' or 'changes_requested')")
            return False
        results.append(f"PASS: state.yaml review={review_val!r}")
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
    """Verify bug.md exists and contains non-template content."""
    bug_path = todo_base / "bug.md"
    if not bug_path.exists():
        results.append("FAIL: bug.md does not exist")
        return False
    content = bug_path.read_text(encoding="utf-8")
    stripped = content.strip()
    if not stripped or (stripped.startswith("<!--") and stripped.endswith("-->")):
        results.append("FAIL: bug.md is empty or contains only a template comment")
        return False
    results.append("PASS: bug.md exists and has content")
    return True


def _verify_implementation_plan(todo_base: Path, results: list[str]) -> bool:
    """Verify implementation-plan.md exists and all tasks are checked off."""
    plan_path = todo_base / "implementation-plan.md"
    if not plan_path.exists():
        results.append("FAIL: implementation-plan.md does not exist")
        return False
    content = plan_path.read_text(encoding="utf-8")
    unchecked = re.findall(r"^\s*-\s*\[ \]", content, re.MULTILINE)
    if unchecked:
        results.append(
            f"FAIL: implementation-plan.md has {len(unchecked)} unchecked task(s) (all must be [x] before review)"
        )
        return False
    results.append("PASS: implementation-plan.md — all tasks checked [x]")
    return True


def _verify_build_commits(worktree_cwd: str, results: list[str]) -> bool:
    """Verify the worktree contains at least one build commit ahead of main."""
    try:
        merge_base_result = subprocess.run(
            ["git", "-C", worktree_cwd, "merge-base", "HEAD", "main"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if merge_base_result.returncode == 0:
            base = merge_base_result.stdout.strip()
            log_result = subprocess.run(
                ["git", "-C", worktree_cwd, "log", "--oneline", f"{base}..HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        else:
            log_result = subprocess.run(
                ["git", "-C", worktree_cwd, "log", "--oneline", "-1"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        if log_result.stdout.strip():
            results.append("PASS: build commits exist on worktree branch")
            return True
        results.append("FAIL: no build commits found on worktree branch beyond main")
        return False
    except (subprocess.TimeoutExpired, OSError) as exc:
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
    """Verify review-findings.md exists, is filled in, and includes a verdict."""
    findings_path = todo_base / "review-findings.md"
    if not findings_path.exists():
        results.append("FAIL: review-findings.md does not exist")
        return False

    content = findings_path.read_text(encoding="utf-8")
    passed = True
    if _is_review_findings_template(content):
        results.append("FAIL: review-findings.md appears to be an unfilled template")
        passed = False
    else:
        results.append("PASS: review-findings.md has real content (not template)")

    has_approve = REVIEW_APPROVE_MARKER in content
    has_request_changes = "REQUEST CHANGES" in content
    if not (has_approve or has_request_changes):
        results.append("FAIL: review-findings.md missing verdict (APPROVE or REQUEST CHANGES)")
        return False

    verdict = "APPROVE" if has_approve else "REQUEST CHANGES"
    results.append(f"PASS: review-findings.md verdict: {verdict}")
    return passed


def _verify_checklist_section(todo_base: Path, section_name: str, results: list[str]) -> bool:
    """Verify a checklist section exists and has at least one checked item."""
    checklist_path = todo_base / "quality-checklist.md"
    if not checklist_path.exists():
        results.append("FAIL: quality-checklist.md does not exist")
        return False

    content = checklist_path.read_text(encoding="utf-8")
    section = _extract_checklist_section(content, section_name)
    if section is None:
        results.append(f"FAIL: quality-checklist.md missing '## {section_name}' section")
        return False

    checked = re.findall(r"^\s*-\s*\[x\]", section, re.MULTILINE | re.IGNORECASE)
    if not checked:
        results.append(f"FAIL: quality-checklist.md {section_name} — no checked items")
        return False

    results.append(f"PASS: quality-checklist.md {section_name} — {len(checked)} checked item(s)")
    return True
