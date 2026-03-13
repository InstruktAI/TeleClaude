"""Build gates — test execution, demo validation, artifact verification.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.core.next_machine._types import REVIEW_APPROVE_MARKER, PhaseName, PhaseStatus, StateValue
from teleclaude.core.next_machine.state_io import is_bug_todo

logger = get_logger(__name__)


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
    all_passed = True
    todo_base = Path(worktree_cwd) / "todos" / slug

    # General checks (all phases): state.yaml parseable and consistent
    state_path = todo_base / "state.yaml"
    if not state_path.exists():
        all_passed = False
        results.append("FAIL: state.yaml does not exist")
    else:
        try:
            state_content = state_path.read_text(encoding="utf-8")
            raw_state = yaml.safe_load(state_content)
            if raw_state is None:
                raw_state = {}
            if not isinstance(raw_state, dict):
                raise ValueError("state.yaml content is not a mapping")
            state: dict[str, StateValue] = raw_state
            results.append("PASS: state.yaml is parseable YAML")
            # Phase field consistency
            if phase == PhaseName.BUILD.value:
                build_val = state.get(PhaseName.BUILD.value)
                if build_val == PhaseStatus.PENDING.value:
                    all_passed = False
                    results.append(
                        f"FAIL: state.yaml build={build_val!r} — still pending, expected 'complete' or later"
                    )
                else:
                    results.append(f"PASS: state.yaml build={build_val!r}")
            elif phase == PhaseName.REVIEW.value:
                review_val = state.get(PhaseName.REVIEW.value)
                if review_val not in (
                    PhaseStatus.APPROVED.value,
                    PhaseStatus.CHANGES_REQUESTED.value,
                ):
                    all_passed = False
                    results.append(
                        f"FAIL: state.yaml review={review_val!r} (expected 'approved' or 'changes_requested')"
                    )
                else:
                    results.append(f"PASS: state.yaml review={review_val!r}")
        except Exception as exc:
            all_passed = False
            results.append(f"FAIL: state.yaml is not parseable: {exc}")

    if phase == PhaseName.BUILD.value:
        if is_bug:
            # Bug builds: check bug.md exists and has content
            bug_path = todo_base / "bug.md"
            if not bug_path.exists():
                all_passed = False
                results.append("FAIL: bug.md does not exist")
            else:
                content = bug_path.read_text(encoding="utf-8")
                stripped = content.strip()
                if not stripped or stripped.startswith("<!--") and stripped.endswith("-->"):
                    all_passed = False
                    results.append("FAIL: bug.md is empty or contains only a template comment")
                else:
                    results.append("PASS: bug.md exists and has content")
        else:
            # Regular builds: check implementation-plan.md exists and all checkboxes are [x]
            plan_path = todo_base / "implementation-plan.md"
            if not plan_path.exists():
                all_passed = False
                results.append("FAIL: implementation-plan.md does not exist")
            else:
                content = plan_path.read_text(encoding="utf-8")
                unchecked = re.findall(r"^\s*-\s*\[ \]", content, re.MULTILINE)
                if unchecked:
                    all_passed = False
                    results.append(
                        f"FAIL: implementation-plan.md has {len(unchecked)} unchecked task(s) "
                        f"(all must be [x] before review)"
                    )
                else:
                    results.append("PASS: implementation-plan.md — all tasks checked [x]")

        # Check: build commits exist on worktree branch beyond merge-base with main
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
                has_commits = bool(log_result.stdout.strip())
            else:
                log_result = subprocess.run(
                    ["git", "-C", worktree_cwd, "log", "--oneline", "-1"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                has_commits = bool(log_result.stdout.strip())
            if has_commits:
                results.append("PASS: build commits exist on worktree branch")
            else:
                all_passed = False
                results.append("FAIL: no build commits found on worktree branch beyond main")
        except (subprocess.TimeoutExpired, OSError) as exc:
            all_passed = False
            results.append(f"FAIL: could not verify commits: {exc}")

        if not is_bug:
            # Check: quality-checklist.md Build Gates section has at least one [x]
            checklist_path = todo_base / "quality-checklist.md"
            if not checklist_path.exists():
                all_passed = False
                results.append("FAIL: quality-checklist.md does not exist")
            else:
                content = checklist_path.read_text(encoding="utf-8")
                build_section = _extract_checklist_section(content, "Build Gates")
                if build_section is None:
                    all_passed = False
                    results.append("FAIL: quality-checklist.md missing '## Build Gates' section")
                else:
                    checked = re.findall(r"^\s*-\s*\[x\]", build_section, re.MULTILINE | re.IGNORECASE)
                    if not checked:
                        all_passed = False
                        results.append("FAIL: quality-checklist.md Build Gates — no checked items")
                    else:
                        results.append(f"PASS: quality-checklist.md Build Gates — {len(checked)} checked item(s)")

    elif phase == PhaseName.REVIEW.value:
        # Check: review-findings.md exists and is not a scaffold template
        findings_path = todo_base / "review-findings.md"
        if not findings_path.exists():
            all_passed = False
            results.append("FAIL: review-findings.md does not exist")
        else:
            content = findings_path.read_text(encoding="utf-8")
            if _is_review_findings_template(content):
                all_passed = False
                results.append("FAIL: review-findings.md appears to be an unfilled template")
            else:
                results.append("PASS: review-findings.md has real content (not template)")

            # Check: verdict present
            has_approve = REVIEW_APPROVE_MARKER in content
            has_request_changes = "REQUEST CHANGES" in content
            if not (has_approve or has_request_changes):
                all_passed = False
                results.append("FAIL: review-findings.md missing verdict (APPROVE or REQUEST CHANGES)")
            else:
                verdict = "APPROVE" if has_approve else "REQUEST CHANGES"
                results.append(f"PASS: review-findings.md verdict: {verdict}")

        if not is_bug:
            # Check: quality-checklist.md Review Gates section has at least one [x]
            checklist_path = todo_base / "quality-checklist.md"
            if not checklist_path.exists():
                all_passed = False
                results.append("FAIL: quality-checklist.md does not exist")
            else:
                content = checklist_path.read_text(encoding="utf-8")
                review_section = _extract_checklist_section(content, "Review Gates")
                if review_section is None:
                    all_passed = False
                    results.append("FAIL: quality-checklist.md missing '## Review Gates' section")
                else:
                    checked = re.findall(r"^\s*-\s*\[x\]", review_section, re.MULTILINE | re.IGNORECASE)
                    if not checked:
                        all_passed = False
                        results.append("FAIL: quality-checklist.md Review Gates — no checked items")
                    else:
                        results.append(f"PASS: quality-checklist.md Review Gates — {len(checked)} checked item(s)")

    else:
        all_passed = False
        results.append(f"FAIL: unknown phase '{phase}' (expected 'build' or 'review')")

    summary = "PASS" if all_passed else "FAIL"
    report = f"Artifact verification [{summary}] for {slug} phase={phase}\n" + "\n".join(results)
    return all_passed, report
