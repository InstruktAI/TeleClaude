"""Next Machine - Deterministic workflow state machine for orchestrating work.

This module provides two main functions:
- next_prepare(): Phase A state machine for collaborative architect work
- next_work(): Phase B state machine for deterministic builder work

Both derive state from files (stateless) and return plain text instructions
for the orchestrator AI to execute literally.
"""

import asyncio
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import TypeAlias, TypedDict, cast

import yaml
from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError, NoSuchPathError
from instrukt_ai_logging import get_logger

from teleclaude.config import config as app_config
from teleclaude.constants import WORKTREE_DIR, SlashCommand
from teleclaude.core.agents import AgentName
from teleclaude.core.db import Db
from teleclaude.core.integration_bridge import emit_branch_pushed, emit_deployment_started, emit_review_approved

logger = get_logger(__name__)

StateScalar: TypeAlias = str | bool | int | None
StateValue: TypeAlias = StateScalar | list["StateValue"] | dict[str, "StateValue"]


class FinalizeState(TypedDict, total=False):
    status: str
    branch: str
    sha: str
    ready_at: str
    worker_session_id: str
    handed_off_at: str
    handoff_session_id: str


class PhaseName(str, Enum):
    BUILD = "build"
    REVIEW = "review"


class PhaseStatus(str, Enum):
    PENDING = "pending"
    STARTED = "started"
    COMPLETE = "complete"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


class ItemPhase(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class PreparePhase(str, Enum):
    """All valid prepare lifecycle phases for the state machine."""

    INPUT_ASSESSMENT = "input_assessment"
    TRIANGULATION = "triangulation"
    REQUIREMENTS_REVIEW = "requirements_review"
    PLAN_DRAFTING = "plan_drafting"
    PLAN_REVIEW = "plan_review"
    GATE = "gate"
    GROUNDING_CHECK = "grounding_check"
    RE_GROUNDING = "re_grounding"
    PREPARED = "prepared"
    BLOCKED = "blocked"


_PREPARE_LOOP_LIMIT = 20

DOR_READY_THRESHOLD = 8


class WorktreeScript(str, Enum):
    PREPARE = "worktree:prepare"


SCRIPTS_KEY = "scripts"
REVIEW_APPROVE_MARKER = "[x] APPROVE"
PAREN_OPEN = "("
DEFAULT_MAX_REVIEW_ROUNDS = 3
FINDING_ID_PATTERN = re.compile(r"\bR\d+-F\d+\b")
NEXT_WORK_PHASE_LOG = "NEXT_WORK_PHASE"
_PREP_STATE_VERSION = 1
_WORKTREE_PREP_STATE_REL = ".teleclaude/worktree-prep-state.json"
_PREP_INPUT_FILES = (
    "Makefile",
    "package.json",
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",
    "requirements-dev.txt",
    "poetry.lock",
)
_PREP_ROOT_INPUT_FILES = (
    "config.yml",
    "tools/worktree-prepare.sh",
)
_SINGLE_FLIGHT_GUARD = threading.Lock()
_SINGLE_FLIGHT_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


@dataclass(frozen=True)
class WorktreePrepDecision:
    should_prepare: bool
    reason: str
    inputs_digest: str


@dataclass(frozen=True)
class EnsureWorktreeResult:
    created: bool
    prepared: bool
    prep_reason: str


async def _get_slug_single_flight_lock(cwd: str, slug: str) -> asyncio.Lock:
    """Return repo+slug lock keyed by canonical project root for strict isolation."""
    canonical_cwd = await asyncio.to_thread(resolve_canonical_project_root, cwd)
    key = (canonical_cwd, slug)
    with _SINGLE_FLIGHT_GUARD:
        lock = _SINGLE_FLIGHT_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _SINGLE_FLIGHT_LOCKS[key] = lock
    return lock


def _log_next_work_phase(slug: str, phase: str, started_at: float, decision: str, reason: str) -> None:
    """Emit grep-friendly phase timing logs for /todos/work."""
    elapsed_ms = int((perf_counter() - started_at) * 1000)
    phase_slug = slug or "<auto>"
    logger.info(
        "%s slug=%s phase=%s decision=%s reason=%s duration_ms=%d",
        NEXT_WORK_PHASE_LOG,
        phase_slug,
        phase,
        decision,
        reason,
        elapsed_ms,
    )
    try:
        from teleclaude.core.operations import emit_operation_progress

        emit_operation_progress(phase, decision, reason)
    except Exception:
        logger.debug("Operation progress emission skipped", exc_info=True)


# Post-completion instructions for each command (used in format_tool_call)
# These tell the orchestrator what to do AFTER a worker completes.
#
# ORCHESTRATOR BOUNDARY RULES:
# - The orchestrator NEVER runs tests, lint, or make in/targeting worktrees
# - The orchestrator NEVER edits or commits files in worktrees
# - The orchestrator NEVER cd's into worktrees
# - Workers are ephemeral: every session is ended after its step completes
# - If mark_phase rejects, the state machine routes to the appropriate fix —
#   the orchestrator does NOT compensate by editing files itself
# - Process gates (pre-commit hooks, mark_phase clerical checks) ARE the
#   verification. The orchestrator trusts them.
POST_COMPLETION: dict[str, str] = {
    "next-build": """WHEN WORKER COMPLETES:
1. Read worker output via get_session_data
2. Call {next_call}
3. If next_work returns BUILD GATES FAILED or ARTIFACT VERIFICATION FAILED:
   - Send the failure details to the builder (do NOT end the session)
   - Wait for builder to report completion again
   - Repeat from step 2
4. Non-recoverable errors (FATAL/BLOCKER reported by worker):
   - Do NOT end the session — keep it alive as a signal for human investigation
   - Report the error status and session ID to the user for manual intervention
5. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-bugs-fix": """WHEN WORKER COMPLETES:
1. Read worker output via get_session_data
2. Call {next_call}
3. If next_work returns BUILD GATES FAILED or ARTIFACT VERIFICATION FAILED:
   - Send the failure details to the builder (do NOT end the session)
   - Wait for builder to report completion again
   - Repeat from step 2
4. Non-recoverable errors (FATAL/BLOCKER reported by worker):
   - Do NOT end the session — keep it alive as a signal for human investigation
   - Report the error status and session ID to the user for manual intervention
5. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-review-build": """WHEN WORKER COMPLETES:
1. Read worker output via get_session_data to extract verdict
2. If verdict is APPROVE:
   a. telec sessions end <session_id>
   b. telec todo mark-phase {args} --phase review --status approved   c. Call {next_call}
3. If verdict is REQUEST CHANGES — PEER CONVERSATION PROTOCOL (keep reviewer alive):
   a. DO NOT end the reviewer session — keep it alive throughout peer iteration
   b. telec todo mark-phase {args} --phase review --status changes_requested   c. Dispatch fixer: telec sessions run --command /next-fix-review --args {args} \\
        --project <project-root> --subfolder trees/{args}
   d. Save <reviewer_session_id> and <fixer_session_id>
   e. Tell the reviewer to start a direct conversation with the fixer:
        telec sessions send <reviewer_session_id> "A fixer is active at <fixer_session_id>. \\
        Start a direct conversation: telec sessions send <fixer_session_id> '<your findings summary>' --direct. \\
        Collaborate until all findings are resolved, then update review-findings.md verdict \\
        to APPROVE and report FIX COMPLETE." (you will use regular send, NOT --direct)
   f. Wait for fixer to complete (monitor via heartbeat; do not poll continuously)
   g. When fixer reports FIX COMPLETE:
      - Read review-findings.md verdict
      - If APPROVE: telec sessions end <fixer_session_id>, telec sessions end <reviewer_session_id>,
          telec todo mark-phase {args} --phase review --status approved,
          call {next_call}
      - If still REQUEST CHANGES: telec sessions end <fixer_session_id>,
          telec sessions end <reviewer_session_id>,
          call {next_call} (state machine manages the round count and limit)
4. Non-recoverable errors (FATAL/BLOCKER reported by worker):
   - Do NOT end the session — keep it alive as a signal for human investigation
   - Report the error status and session ID to the user for manual intervention
5. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-fix-review": """WHEN WORKER COMPLETES:
1. Read worker output via get_session_data
2. telec sessions end <session_id>
3. telec todo mark-phase {args} --phase review --status pending4. Call {next_call}
5. Non-recoverable errors (FATAL/BLOCKER reported by worker):
   - Do NOT end the session — keep it alive as a signal for human investigation
   - Report the error status and session ID to the user for manual intervention
6. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-defer": """WHEN WORKER COMPLETES:
1. Read worker output. Confirm deferrals_processed in state.yaml
2. telec sessions end <session_id>
3. Call {next_call}
4. Non-recoverable errors (FATAL/BLOCKER reported by worker):
   - Do NOT end the session — keep it alive as a signal for human investigation
   - Report the error status and session ID to the user for manual intervention
5. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-finalize": """# state.yaml lives in the worktree only — never commit it to main directly.

WHEN WORKER COMPLETES:
1. Read worker output via get_session_data.
2. Accept completion only for the dispatched worker session `<session_id>`.
   Ignore notifications from any other session.
3. Confirm worker reported exactly `FINALIZE_READY: {args}` in session `<session_id>` transcript.
   If missing: send worker feedback to report FINALIZE_READY and stop (do NOT apply).
4. telec todo mark-finalize-ready {args} --worker-session-id <session_id>
5. telec sessions end <session_id>
6. Call {next_call}
7. Non-recoverable errors (FATAL/BLOCKER reported by worker):
   - Do NOT end the session — keep it alive as a signal for human investigation
   - Report the error status and session ID to the user for manual intervention
8. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
}

REVIEW_DIFF_NOTE = (
    "Review guard: if `git log --oneline HEAD..main` shows commits, "
    "diff must use merge-base: `git diff $(git merge-base HEAD main)..HEAD`."
)


# =============================================================================
# Response Formatters (plain text output)
# =============================================================================


def format_tool_call(
    command: str,
    args: str,
    project: str,
    guidance: str,
    subfolder: str,
    note: str = "",
    next_call: str = "",
    completion_args: str | None = None,
    pre_dispatch: str = "",
) -> str:
    """Format a literal tool call for the orchestrator to execute."""
    raw_command = command.lstrip("/")
    formatted_command = f"/{raw_command}"

    # Get post-completion instructions for this command
    post_completion = POST_COMPLETION.get(command, "")
    if post_completion:
        next_call_display = next_call.strip()
        if next_call_display and PAREN_OPEN not in next_call_display and " " not in next_call_display:
            next_call_display = f"{next_call_display}()"
        completion_value = completion_args if completion_args is not None else args
        # Substitute {args} and {next_call} placeholders
        post_completion = post_completion.format(args=completion_value, next_call=next_call_display)

    pre_dispatch_block = ""
    if pre_dispatch:
        pre_dispatch_block = f"""STEP 0 - BEFORE DISPATCHING:
{pre_dispatch}

"""

    result = f"""IMPORTANT: This output is an execution script. Follow it verbatim.

Execute these steps in order (FOLLOW TO THE LETTER!):

{pre_dispatch_block}STEP 1 - DISPATCH:
{guidance}

Based on the above guidance and the work item details, select the best agent and thinking mode.

Dispatch metadata: command="{formatted_command}" args="{args}" project="{project}" subfolder="{subfolder}"

telec sessions run --command "{formatted_command}" --args "{args}" --project "{project}" --agent "<your selection>" --mode "<your selection>" --subfolder "{subfolder}"
Legacy dispatch marker: command="{formatted_command}" subfolder="{subfolder}"
Save the returned session_id.
Command metadata: command="{formatted_command}" args="{args}" subfolder="{subfolder}".

STEP 2 - START BACKGROUND TIMER:
Bash(command="sleep 300", run_in_background=true)
Save the returned task_id.

STEP 3 - WAIT:
Tell the user: "Dispatched session <session_id>. Waiting for completion."
Do NOT call any more tools UNTIL one of the events below fires.
When an event fires, you MUST immediately act on it — do NOT wait for user input.

WHAT HAPPENS NEXT (one of these will occur):

A) NOTIFICATION ARRIVES (worker completed):
   - The timer is now irrelevant (let it expire or ignore it)
   - Follow WHEN WORKER COMPLETES below

B) TIMER COMPLETES (no notification after 5 minutes):
   THIS IS YOUR ACTIVATION TRIGGER. You MUST act immediately:
   - Check on the session: telec sessions tail <session_id> --tools --thinking
   - If still running: reset timer (sleep 300, run_in_background=true) and WAIT again
   - If completed/idle: follow WHEN WORKER COMPLETES below
   - If stuck/errored: intervene or escalate to user
   Do NOT stop after checking — either reset the timer or execute completion steps.

C) YOU SEND ANOTHER MESSAGE TO THE AGENT BECAUSE IT NEEDS FEEDBACK OR HELP:
   - Cancel the old timer: KillShell(shell_id=<task_id>)
   - Start a new 5-minute timer: Bash(command="sleep 300", run_in_background=true)
   - Save the new task_id for the reset timer

D) NO-OP SUPPRESSION (NON-CHATTY ORCHESTRATION):
   - Never send no-op follow-ups like "No new input", "No further input", "Remain idle", or "Continue standing by".
   - Only send telec sessions send when there is actionable content:
     1) concrete gate failure details,
     2) a direct answer to an explicit worker question, or
     3) a user-directed change in plan.
   - If none apply, do not send another worker message; continue the state-machine loop.

{post_completion}

ORCHESTRATION PRINCIPLE: Guide process, don't dictate implementation.
You are an orchestrator, not a micromanager. Workers have full autonomy.
- NEVER run tests, lint, or make in/targeting worktrees
- NEVER edit or commit files in worktrees
- NEVER cd into worktrees — stay in the main repo root
- ALWAYS end the worker session when its step completes — no exceptions
- NEVER send no-op acknowledgements/keepalive chatter to workers
- Trust the process gates (pre-commit hooks, mark_phase clerical checks)
- If mark_phase rejects, the state machine routes to the fix — do NOT fix it yourself"""
    if note:
        result += f"\n\nNOTE: {note}"
    return result


def format_error(code: str, message: str, next_call: str = "") -> str:
    """Format an error message with optional next step."""
    result = f"ERROR: {code}\n{message}"
    if next_call:
        result += f"\n\nNEXT: {next_call}"
    return result


def format_prepared(slug: str) -> str:
    """Format a 'prepared' message indicating work item is ready."""
    return f"""PREPARED: todos/{slug} is ready for work.

DECISION REQUIRED: Continue preparation work, or start the build/review cycle with telec todo work {slug}."""


def format_uncommitted_changes(slug: str) -> str:
    """Format instruction for orchestrator to resolve worktree uncommitted changes."""
    return f"""UNCOMMITTED CHANGES in {WORKTREE_DIR}/{slug}

NEXT: Resolve these changes according to the commit policy, then call telec todo work {slug} to continue."""


def format_finalize_handoff_complete(slug: str, next_call: str, child_session_ids: list[str] | None = None) -> str:
    """Format the slug-scoped handoff step after finalize readiness is recorded."""
    steps: list[str] = []
    steps.append(
        f'1. Report: "Candidate {slug} handed off to the integration event chain. '
        f'The integrator will spawn automatically when the projection reports READY."'
    )

    step = 2
    if child_session_ids:
        end_cmds = "\n   ".join(f"telec sessions end {sid}" for sid in child_session_ids)
        steps.append(f"{step}. End child sessions:\n   {end_cmds}")
        step += 1

    steps.append(f"{step}. Call {next_call}")

    instructions = "\n".join(steps)
    return f"""FINALIZE HANDOFF COMPLETE: {slug}

INSTRUCTIONS FOR ORCHESTRATOR:
{instructions}"""


def format_stash_debt(slug: str, count: int) -> str:
    """Format instruction when repository stash is non-empty."""
    noun = "entry" if count == 1 else "entries"
    return format_error(
        "STASH_DEBT",
        f"Repository has {count} git stash {noun}. Stash workflows are forbidden for AI orchestration.",
        next_call=(
            "Clear all repository stash entries with maintainer-approved workflow, "
            f"then call telec todo work {slug} to continue."
        ),
    )


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

    # Gate 2: Demo structure validation
    if is_bug_todo(worktree_cwd, slug):
        results.append("GATE SKIPPED: demo validate (bug workflow)")
    else:
        try:
            demo_result = subprocess.run(
                ["telec", "todo", "demo", "validate", slug],
                cwd=worktree_cwd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if demo_result.returncode != 0:
                all_passed = False
                results.append(f"GATE FAILED: demo validate (exit {demo_result.returncode})\n{demo_result.stdout}")
            elif "no-demo marker found" in demo_result.stdout.lower():
                results.append(
                    f"GATE WARNING: demo validate — no-demo marker used, reviewer must verify\n{demo_result.stdout.strip()}"
                )
            else:
                results.append(f"GATE PASSED: demo validate\n{demo_result.stdout.strip()}")
        except subprocess.TimeoutExpired:
            all_passed = False
            results.append("GATE FAILED: demo validate (timed out)")
        except OSError as exc:
            all_passed = False
            results.append(f"GATE FAILED: demo validate (error: {exc})")

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


def _find_next_prepare_slug(cwd: str) -> str | None:
    """Find the next active slug that still needs preparation work.

    Scans roadmap.yaml for slugs, then checks state.yaml phase for each.
    Active slugs have phase pending, ready, or in_progress.
    Returns the first slug that still needs action:
    - requirements.md missing
    - implementation-plan.md missing
    - phase still pending (needs promotion to ready)
    """
    for slug in load_roadmap_slugs(cwd):
        phase = get_item_phase(cwd, slug)

        # Skip done items
        if phase == ItemPhase.DONE.value:
            continue

        has_requirements = check_file_has_content(cwd, f"todos/{slug}/requirements.md")
        has_impl_plan = check_file_has_content(cwd, f"todos/{slug}/implementation-plan.md")
        if not has_requirements or not has_impl_plan:
            return slug

        if phase == ItemPhase.PENDING.value:
            return slug

    return None


# =============================================================================
# Shared Helper Functions
# =============================================================================


# Valid phases and statuses for state.yaml
DEFAULT_STATE: dict[str, StateValue] = {
    "phase": ItemPhase.PENDING.value,
    PhaseName.BUILD.value: PhaseStatus.PENDING.value,
    PhaseName.REVIEW.value: PhaseStatus.PENDING.value,
    "deferrals_processed": False,
    "finalize": {"status": "pending"},
    "breakdown": {"assessed": False, "todos": []},
    "review_round": 0,
    "max_review_rounds": DEFAULT_MAX_REVIEW_ROUNDS,
    "review_baseline_commit": "",
    "unresolved_findings": [],
    "resolved_findings": [],
    "prepare_phase": "",
    "grounding": {
        "valid": False,
        "base_sha": "",
        "input_digest": "",
        "referenced_paths": [],
        "last_grounded_at": "",
        "invalidated_at": "",
        "invalidation_reason": "",
    },
    "requirements_review": {
        "verdict": "",
        "reviewed_at": "",
        "findings_count": 0,
        "rounds": 0,
    },
    "plan_review": {
        "verdict": "",
        "reviewed_at": "",
        "findings_count": 0,
        "rounds": 0,
    },
}


def get_state_path(cwd: str, slug: str) -> Path:
    """Get path to state.yaml in worktree."""
    return Path(cwd) / "todos" / slug / "state.yaml"


def read_phase_state(cwd: str, slug: str) -> dict[str, StateValue]:
    """Read state.yaml from worktree (falls back to state.json for backward compat).

    Returns default state if file doesn't exist.
    Migrates missing 'phase' field from existing build/dor state.
    """
    state_path = get_state_path(cwd, slug)
    # Backward compat: try state.json if state.yaml doesn't exist
    if not state_path.exists():
        legacy_path = state_path.with_name("state.json")
        if legacy_path.exists():
            state_path = legacy_path

    if not state_path.exists():
        return copy.deepcopy(DEFAULT_STATE)

    content = read_text_sync(state_path)
    raw_state = yaml.safe_load(content)
    if raw_state is None:
        state: dict[str, StateValue] = {}
    elif isinstance(raw_state, dict):
        state = raw_state
    else:
        logger.warning("Ignoring non-mapping phase state for %s/%s", cwd, slug)
        state = {}
    # Merge with defaults for any missing keys
    merged = copy.deepcopy(DEFAULT_STATE)
    merged.update(state)
    merged["finalize"] = _normalize_finalize_state(state.get("finalize"))

    # Migration: derive phase from existing fields when missing from persisted state
    if "phase" not in state:
        build = state.get(PhaseName.BUILD.value)
        if isinstance(build, str) and build != PhaseStatus.PENDING.value:
            merged["phase"] = ItemPhase.IN_PROGRESS.value
        else:
            merged["phase"] = ItemPhase.PENDING.value
    elif state.get("phase") == "ready":
        # Migration: normalize persisted "ready" phase to "pending" (readiness is now derived from dor.score)
        merged["phase"] = ItemPhase.PENDING.value

    return merged


def _normalize_finalize_state(raw: object) -> FinalizeState:
    finalize: FinalizeState = {"status": "pending"}
    if not isinstance(raw, dict):
        return finalize

    status = raw.get("status")
    if isinstance(status, str) and status in {"pending", "ready", "handed_off"}:
        finalize["status"] = status

    for key in ("branch", "sha", "ready_at", "worker_session_id", "handed_off_at", "handoff_session_id"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            finalize[key] = value.strip()
    return finalize


def _get_finalize_state(state: dict[str, StateValue]) -> FinalizeState:
    return _normalize_finalize_state(state.get("finalize"))


def write_phase_state(cwd: str, slug: str, state: dict[str, StateValue]) -> None:
    """Write state.yaml."""
    state_path = get_state_path(cwd, slug)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(state, default_flow_style=False, sort_keys=False)
    write_text_sync(state_path, content)


def mark_phase(cwd: str, slug: str, phase: str, status: str) -> dict[str, StateValue]:
    """Mark a phase with a status.

    Args:
        cwd: Worktree directory (not main repo)
        slug: Work item slug
        phase: Phase to update (build, review)
        status: New status (pending, complete, approved, changes_requested)

    Returns:
        Updated state dict
    """
    state = read_phase_state(cwd, slug)
    state[phase] = status
    if phase == PhaseName.REVIEW.value:
        review_round = state.get("review_round")
        current_round = review_round if isinstance(review_round, int) else 0
        unresolved = state.get("unresolved_findings")
        unresolved_ids = list(unresolved) if isinstance(unresolved, list) else []
        resolved = state.get("resolved_findings")
        resolved_ids = list(resolved) if isinstance(resolved, list) else []

        if status in (PhaseStatus.CHANGES_REQUESTED.value, PhaseStatus.APPROVED.value):
            state["review_round"] = current_round + 1
            head_sha = _get_head_commit(cwd)
            if head_sha:
                state["review_baseline_commit"] = head_sha

        if status == PhaseStatus.CHANGES_REQUESTED.value:
            findings_ids = _extract_finding_ids(cwd, slug)
            state["unresolved_findings"] = findings_ids
            # Keep resolved IDs stable and de-duplicated
            state["resolved_findings"] = list(dict.fromkeys(str(i) for i in resolved_ids))
        elif status == PhaseStatus.APPROVED.value:
            merged = list(dict.fromkeys([*(str(i) for i in resolved_ids), *(str(i) for i in unresolved_ids)]))
            state["resolved_findings"] = merged
            state["unresolved_findings"] = []
    write_phase_state(cwd, slug, state)
    return state


# Valid prepare sub-phases that accept verdicts via mark-phase
_PREPARE_VERDICT_PHASES = ("requirements_review", "plan_review")
_PREPARE_VERDICT_VALUES = ("approve", "needs_work")

# Valid prepare_phase values for direct phase advancement
_PREPARE_PHASE_VALUES = tuple(p.value for p in PreparePhase)


def mark_prepare_verdict(cwd: str, slug: str, phase: str, verdict: str) -> dict[str, StateValue]:
    """Mark a prepare sub-phase verdict in state.yaml.

    Args:
        cwd: Project root directory (not worktree)
        slug: Work item slug
        phase: Prepare sub-phase (requirements_review, plan_review)
        verdict: Verdict value (approve, needs_work)

    Returns:
        Updated state dict
    """
    if phase not in _PREPARE_VERDICT_PHASES:
        raise ValueError(f"invalid prepare phase '{phase}': must be one of {', '.join(_PREPARE_VERDICT_PHASES)}")
    if verdict not in _PREPARE_VERDICT_VALUES:
        raise ValueError(f"invalid verdict '{verdict}': must be one of {', '.join(_PREPARE_VERDICT_VALUES)}")

    state = read_phase_state(cwd, slug)
    review_dict = state.get(phase)
    if not isinstance(review_dict, dict):
        review_dict = {}
    review_dict["verdict"] = verdict
    state[phase] = review_dict  # type: ignore[assignment]
    write_phase_state(cwd, slug, state)
    return state


def mark_prepare_phase(cwd: str, slug: str, status: str) -> dict[str, StateValue]:
    """Set prepare_phase directly in state.yaml.

    When advancing to 'prepared', also stamps grounding as valid with the
    current HEAD sha and input digest so the work state machine accepts it.

    Args:
        cwd: Project root directory (not worktree)
        slug: Work item slug
        status: PreparePhase value (e.g. prepared, gate, plan_review)

    Returns:
        Updated state dict
    """
    if status not in _PREPARE_PHASE_VALUES:
        raise ValueError(f"invalid prepare_phase '{status}': must be one of {', '.join(_PREPARE_PHASE_VALUES)}")

    state = read_phase_state(cwd, slug)
    state["prepare_phase"] = status

    if status == PreparePhase.PREPARED.value:
        grounding = state.get("grounding", {})
        grounding_dict = {**DEFAULT_STATE["grounding"], **(grounding if isinstance(grounding, dict) else {})}  # type: ignore[arg-type]
        rc, current_sha, _ = _run_git_prepare(["rev-parse", "HEAD"], cwd=cwd)
        if rc == 0 and current_sha.strip():
            grounding_dict["base_sha"] = current_sha.strip()
        input_path = Path(cwd) / "todos" / slug / "input.md"
        if input_path.exists():
            grounding_dict["input_digest"] = hashlib.sha256(input_path.read_bytes()).hexdigest()
        grounding_dict["valid"] = True
        grounding_dict["last_grounded_at"] = datetime.now(UTC).isoformat()
        grounding_dict["invalidation_reason"] = ""
        grounding_dict["changed_paths"] = []
        state["grounding"] = grounding_dict  # type: ignore[assignment]

    write_phase_state(cwd, slug, state)
    return state


def mark_finalize_ready(cwd: str, slug: str, worker_session_id: str = "") -> dict[str, StateValue]:
    """Record durable finalize readiness after finalizer prepare succeeds.

    The orchestrator owns this write after verifying the worker reported
    FINALIZE_READY. The record becomes the single source of truth consumed by
    the subsequent slug-specific `telec todo work {slug}` handoff step.
    """
    worktree_cwd = str(Path(cwd) / WORKTREE_DIR / slug)
    if not Path(worktree_cwd).exists():
        raise ValueError(f"worktree not found at {worktree_cwd}")
    if has_uncommitted_changes(cwd, slug):
        raise ValueError(f"worktree {WORKTREE_DIR}/{slug} has uncommitted changes")

    worktree_head = _get_head_commit(worktree_cwd)
    branch_head = _get_ref_commit(cwd, slug)
    if not worktree_head or not branch_head:
        raise ValueError(f"unable to resolve finalized branch head for {slug}")
    if worktree_head != branch_head:
        raise ValueError(
            f"branch {slug} does not match worktree HEAD after finalize prepare "
            f"(branch={branch_head or '<missing>'}, worktree={worktree_head or '<missing>'})"
        )

    remote_head = _get_remote_branch_head(cwd, slug)
    if not remote_head:
        raise ValueError(f"origin/{slug} is missing — push the finalized branch before marking ready")
    if remote_head != branch_head:
        raise ValueError(
            f"origin/{slug} is at {remote_head}, expected finalized head {branch_head}; "
            "push the latest branch head before marking ready"
        )

    state = read_phase_state(worktree_cwd, slug)
    finalize = _get_finalize_state(state)
    if finalize.get("status") == "handed_off" and finalize.get("sha") == branch_head:
        return state
    if finalize.get("status") == "ready" and finalize.get("sha") == branch_head:
        return state

    state["finalize"] = {
        "status": "ready",
        "branch": slug,
        "sha": branch_head,
        "ready_at": datetime.now(UTC).isoformat(),
        "worker_session_id": worker_session_id.strip(),
    }
    write_phase_state(worktree_cwd, slug, state)
    return state


def _mark_finalize_handed_off(
    worktree_cwd: str,
    slug: str,
    *,
    handoff_session_id: str,
) -> dict[str, StateValue]:
    state = read_phase_state(worktree_cwd, slug)
    finalize = _get_finalize_state(state)
    if finalize.get("status") != "ready":
        raise ValueError(f"finalize state for {slug} is not ready")

    state["finalize"] = {
        **finalize,
        "status": "handed_off",
        "handoff_session_id": handoff_session_id,
        "handed_off_at": datetime.now(UTC).isoformat(),
    }
    write_phase_state(worktree_cwd, slug, state)
    return state


def _extract_finding_ids(cwd: str, slug: str) -> list[str]:
    """Extract stable finding IDs (e.g. R1-F1) from review-findings.md."""
    review_path = Path(cwd) / "todos" / slug / "review-findings.md"
    if not review_path.exists():
        return []
    content = read_text_sync(review_path)
    seen: list[str] = []
    for match in FINDING_ID_PATTERN.findall(content):
        if match not in seen:
            seen.append(match)
    return seen


def _get_head_commit(cwd: str) -> str:
    """Return HEAD commit hash for cwd, or empty string when unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return ""
    return result.stdout.strip()


def _get_ref_commit(cwd: str, ref: str) -> str:
    """Return commit hash for a git ref in cwd, or empty string when unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", ref],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return ""
    return result.stdout.strip()


def _get_remote_branch_head(cwd: str, branch: str) -> str:
    """Return origin/<branch> HEAD commit, or empty string when unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "ls-remote", "origin", f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return ""
    parts = result.stdout.strip().split()
    return parts[0] if parts else ""


def _merge_origin_main_into_worktree(worktree_cwd: str, slug: str) -> str:
    """Fetch and merge origin/main into the worktree branch.

    Returns empty string on success (including when fetch is unavailable),
    or an error message only when merge conflicts occur.
    """
    fetch_result = subprocess.run(
        ["git", "-C", worktree_cwd, "fetch", "origin", "main"],
        capture_output=True,
        text=True,
    )
    if fetch_result.returncode != 0:
        # Fetch failure is non-fatal (no remote, offline, test env)
        logger.info("Skipping origin/main merge for %s — fetch failed: %s", slug, fetch_result.stderr.strip())
        return ""

    merge_result = subprocess.run(
        ["git", "-C", worktree_cwd, "merge", "origin/main", "--no-edit"],
        capture_output=True,
        text=True,
    )
    if merge_result.returncode != 0:
        # Abort the failed merge so the worktree stays clean
        subprocess.run(
            ["git", "-C", worktree_cwd, "merge", "--abort"],
            capture_output=True,
            text=True,
        )
        return (
            f"Merge origin/main into worktree {slug} failed with conflicts. "
            f"The merge was aborted. Resolve manually or rebase.\n{merge_result.stderr.strip()}"
        )

    logger.info("Merged origin/main into worktree %s", slug)
    return ""


def _has_meaningful_diff(cwd: str, baseline: str, head: str) -> bool:
    """Return True if non-infrastructure commits exist between baseline and head.

    Filters out:
    - Files under todos/ and .teleclaude/
    - Files changed exclusively by merge commits

    Computes files changed by non-merge commits directly (via --no-merges) rather than
    subtracting merge-commit files from the total diff. This avoids the over-subtraction
    bug where a file touched by both a merge commit and a regular commit would be
    incorrectly excluded, producing a false negative and allowing a stale approval through.

    Returns True on subprocess errors (fail-safe: assume meaningful diff, invalidate).
    """
    infra_prefixes = ("todos/", ".teleclaude/")
    try:
        log_result = subprocess.run(
            [
                "git",
                "-C",
                cwd,
                "log",
                "--no-merges",
                "--name-only",
                "--pretty=format:",
                f"{baseline}..{head}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        meaningful_files = {
            f for f in log_result.stdout.splitlines() if f.strip() and not any(f.startswith(p) for p in infra_prefixes)
        }
        return bool(meaningful_files)
    except (subprocess.CalledProcessError, OSError) as exc:
        logger.warning(
            "has_meaningful_diff: subprocess error; assuming meaningful diff (fail-safe)",
            extra={"cwd": cwd, "baseline": baseline, "head": head, "error": str(exc)},
        )
        return True  # Fail-safe: assume meaningful diff, invalidate approval


def _review_scope_note(cwd: str, slug: str) -> str:
    """Build an iterative review scope note from state.yaml metadata."""
    state = read_phase_state(cwd, slug)
    review_round_raw = state.get("review_round")
    max_rounds_raw = state.get("max_review_rounds")
    review_round = review_round_raw if isinstance(review_round_raw, int) else 0
    max_rounds = max_rounds_raw if isinstance(max_rounds_raw, int) else DEFAULT_MAX_REVIEW_ROUNDS
    next_round = review_round + 1
    baseline = state.get("review_baseline_commit")
    baseline_sha = baseline if isinstance(baseline, str) else ""
    unresolved = state.get("unresolved_findings")
    unresolved_ids = unresolved if isinstance(unresolved, list) else []

    unresolved_text = ", ".join(str(x) for x in unresolved_ids) if unresolved_ids else "none"
    baseline_text = baseline_sha if baseline_sha else "unset (initial full review)"
    return (
        f"Review iteration: round {next_round}/{max_rounds}. "
        "Round 1 is full-scope. Round 2+ must be incremental: review only commits since "
        f"{baseline_text} plus unresolved IDs [{unresolved_text}]."
    )


def _is_review_round_limit_reached(cwd: str, slug: str) -> tuple[bool, int, int]:
    """Return whether next review round would exceed configured max."""
    state = read_phase_state(cwd, slug)
    review_round_raw = state.get("review_round")
    max_rounds_raw = state.get("max_review_rounds")
    review_round = review_round_raw if isinstance(review_round_raw, int) else 0
    max_rounds = max_rounds_raw if isinstance(max_rounds_raw, int) else DEFAULT_MAX_REVIEW_ROUNDS
    return (review_round + 1) > max_rounds, review_round, max_rounds


def read_breakdown_state(cwd: str, slug: str) -> dict[str, bool | list[str]] | None:
    """Read breakdown state from todos/{slug}/state.yaml.

    Returns:
        Breakdown state dict with 'assessed' and 'todos' keys, or None if not present.
    """
    state = read_phase_state(cwd, slug)
    breakdown = state.get("breakdown")
    if breakdown is None or not isinstance(breakdown, dict):
        return None
    # At this point breakdown is dict with bool/list values from json
    return dict(breakdown)  # type: ignore[return-value]


def write_breakdown_state(cwd: str, slug: str, assessed: bool, todos: list[str]) -> None:
    """Write breakdown state.

    Args:
        cwd: Project root directory
        slug: Work item slug
        assessed: Whether breakdown assessment has been performed
        todos: List of todo slugs created from split (empty if no breakdown)
    """
    state = read_phase_state(cwd, slug)
    state["breakdown"] = {"assessed": assessed, "todos": todos}
    write_phase_state(cwd, slug, state)


def is_build_complete(cwd: str, slug: str) -> bool:
    """Check if build phase is complete."""
    state = read_phase_state(cwd, slug)
    build = state.get(PhaseName.BUILD.value)
    return isinstance(build, str) and build == PhaseStatus.COMPLETE.value


def is_review_approved(cwd: str, slug: str) -> bool:
    """Check if review phase is approved."""
    state = read_phase_state(cwd, slug)
    review = state.get(PhaseName.REVIEW.value)
    return isinstance(review, str) and review == PhaseStatus.APPROVED.value


def is_review_changes_requested(cwd: str, slug: str) -> bool:
    """Check if review requested changes."""
    state = read_phase_state(cwd, slug)
    review = state.get(PhaseName.REVIEW.value)
    return isinstance(review, str) and review == PhaseStatus.CHANGES_REQUESTED.value


def has_pending_deferrals(cwd: str, slug: str) -> bool:
    """Check if there are pending deferrals.

    Returns true if deferrals.md exists AND state.yaml.deferrals_processed is NOT true.
    """
    deferrals_path = Path(cwd) / "todos" / slug / "deferrals.md"
    if not deferrals_path.exists():
        return False

    state = read_phase_state(cwd, slug)
    return state.get("deferrals_processed") is not True


def resolve_holder_children(cwd: str, holder_slug: str) -> list[str]:
    """Resolve container/holder child slugs in deterministic order.

    Resolution sources:
    - roadmap group mapping (`group == holder_slug`)
    - holder breakdown state (`state.yaml.breakdown.todos`)

    Roadmap order is authoritative when present. Breakdown-only children are
    appended in their declared order.
    """
    entries = load_roadmap(cwd)
    grouped_children = [entry.slug for entry in entries if entry.group == holder_slug]

    breakdown_state = read_breakdown_state(cwd, holder_slug)
    breakdown_children: list[str] = []
    if breakdown_state:
        raw_children = breakdown_state.get("todos")
        if isinstance(raw_children, list):
            breakdown_children = [child for child in raw_children if child]

    if not grouped_children and not breakdown_children:
        return []

    ordered_children = list(grouped_children)
    seen = set(ordered_children)
    for child in breakdown_children:
        if child not in seen:
            ordered_children.append(child)
            seen.add(child)
    return ordered_children


def resolve_first_runnable_holder_child(
    cwd: str,
    holder_slug: str,
    dependencies: dict[str, list[str]],
) -> tuple[str | None, str]:
    """Resolve first runnable child for a holder slug.

    Returns:
        (child_slug, reason)
        - reason == "ok" when child_slug is selected
        - reason in {"not_holder", "children_not_in_roadmap", "complete",
          "deps_unsatisfied", "item_not_ready"} otherwise
    """
    children = resolve_holder_children(cwd, holder_slug)
    if not children:
        return None, "not_holder"

    has_children_in_roadmap = False
    has_incomplete_children = False
    has_deps_blocked = False
    has_not_ready = False

    for child in children:
        if not slug_in_roadmap(cwd, child):
            continue

        has_children_in_roadmap = True
        phase = get_item_phase(cwd, child)
        if phase == ItemPhase.DONE.value:
            continue

        has_incomplete_children = True
        is_ready = phase == ItemPhase.IN_PROGRESS.value or is_ready_for_work(cwd, child)
        if not is_ready:
            has_not_ready = True
            continue

        if not check_dependencies_satisfied(cwd, child, dependencies):
            has_deps_blocked = True
            continue

        return child, "ok"

    if not has_children_in_roadmap:
        return None, "children_not_in_roadmap"
    if not has_incomplete_children:
        return None, "complete"
    if has_deps_blocked:
        return None, "deps_unsatisfied"
    if has_not_ready:
        return None, "item_not_ready"
    return None, "item_not_ready"


def resolve_slug(
    cwd: str,
    slug: str | None,
    ready_only: bool = False,
    dependencies: dict[str, list[str]] | None = None,
) -> tuple[str | None, bool, str]:
    """Resolve slug from argument or roadmap.

    Phase is derived from state.yaml for each slug.

    Args:
        cwd: Current working directory (project root)
        slug: Optional explicit slug
        ready_only: If True, only match items with phase "ready" (for next_work)
        dependencies: Optional dependency graph for dependency gating (R6).
                     If provided with ready_only=True, only returns slugs with satisfied dependencies.

    Returns:
        Tuple of (slug, is_ready_or_in_progress, description).
        If slug provided, returns (slug, True, "").
        If found in roadmap, returns (slug, True if ready/in_progress, False if pending, description).
        If nothing found, returns (None, False, "").
    """
    if slug:
        return slug, True, ""

    entries = load_roadmap(cwd)
    if not entries:
        return None, False, ""

    for entry in entries:
        found_slug = entry.slug
        phase = get_item_phase(cwd, found_slug)

        if ready_only:
            if not is_ready_for_work(cwd, found_slug):
                continue
        else:
            # Skip done items for next_prepare
            if phase == ItemPhase.DONE.value:
                continue

        is_ready = phase == ItemPhase.IN_PROGRESS.value or is_ready_for_work(cwd, found_slug)

        # R6: Enforce dependency gating when ready_only=True and dependencies provided
        if ready_only and dependencies is not None:
            if not check_dependencies_satisfied(cwd, found_slug, dependencies):
                continue  # Skip items with unsatisfied dependencies

        description = entry.description or ""
        return found_slug, is_ready, description

    return None, False, ""


async def resolve_slug_async(
    cwd: str,
    slug: str | None,
    ready_only: bool = False,
    dependencies: dict[str, list[str]] | None = None,
) -> tuple[str | None, bool, str]:
    """Async wrapper for resolve_slug using a thread to avoid blocking."""
    return await asyncio.to_thread(resolve_slug, cwd, slug, ready_only, dependencies)


def check_file_exists(cwd: str, relative_path: str) -> bool:
    """Check if a file exists relative to cwd."""
    return (Path(cwd) / relative_path).exists()


def resolve_canonical_project_root(cwd: str) -> str:
    """Resolve canonical repository root from cwd.

    Accepts either the project root or a path inside a git worktree. Falls back
    to the provided cwd when git metadata is unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return cwd

    raw_common_dir = result.stdout.strip()
    if not raw_common_dir:
        return cwd

    common_dir = Path(raw_common_dir)
    if not common_dir.is_absolute():
        common_dir = (Path(cwd) / common_dir).resolve()
    else:
        common_dir = common_dir.resolve()

    return str((common_dir / "..").resolve())


def slug_in_roadmap(cwd: str, slug: str) -> bool:
    """Check if a slug exists in todos/roadmap.yaml."""
    return slug in load_roadmap_slugs(cwd)


def is_bug_todo(cwd: str, slug: str) -> bool:
    """Check if a todo is a bug (kind='bug' in state.yaml)."""
    state = read_phase_state(cwd, slug)
    return state.get("kind") == "bug"


# =============================================================================
# Item Phase Management (state.yaml is the single source of truth)
# =============================================================================


def get_item_phase(cwd: str, slug: str) -> str:
    """Get current phase for a work item from state.yaml.

    Args:
        cwd: Project root directory
        slug: Work item slug to query

    Returns:
        One of "pending", "in_progress", "done"
    """
    state = read_phase_state(cwd, slug)
    phase = state.get("phase")
    return phase if isinstance(phase, str) else ItemPhase.PENDING.value


def is_ready_for_work(cwd: str, slug: str) -> bool:
    """Check if item is ready for work: pending phase + DOR score >= threshold."""
    state = read_phase_state(cwd, slug)
    phase = state.get("phase")
    if phase != ItemPhase.PENDING.value:
        return False
    build = state.get(PhaseName.BUILD.value)
    if build != PhaseStatus.PENDING.value:
        return False
    dor = state.get("dor")
    if not isinstance(dor, dict):
        return False
    score = dor.get("score")
    return isinstance(score, int) and score >= DOR_READY_THRESHOLD


def set_item_phase(cwd: str, slug: str, phase: str) -> None:
    """Set phase for a work item in state.yaml.

    Args:
        cwd: Project root directory
        slug: Work item slug to update
        phase: One of "pending", "in_progress", "done"
    """
    state = read_phase_state(cwd, slug)
    state["phase"] = phase
    write_phase_state(cwd, slug, state)


# =============================================================================
# Roadmap Management (roadmap.yaml)
# =============================================================================


@dataclass
class RoadmapEntry:
    slug: str
    group: str | None = None
    after: list[str] = field(default_factory=list)
    description: str | None = None


class RoadmapDict(TypedDict, total=False):
    slug: str
    group: str
    after: list[str]
    description: str


def _roadmap_path(cwd: str) -> Path:
    return Path(cwd) / "todos" / "roadmap.yaml"


def load_roadmap(cwd: str) -> list[RoadmapEntry]:
    """Parse todos/roadmap.yaml and return ordered list of entries."""
    path = _roadmap_path(cwd)
    if not path.exists():
        return []

    content = read_text_sync(path)
    raw = yaml.safe_load(content)
    if not isinstance(raw, list):
        return []

    entries: list[RoadmapEntry] = []
    for item in raw:
        if not isinstance(item, dict) or "slug" not in item:
            continue
        after = item.get("after")
        entries.append(
            RoadmapEntry(
                slug=item["slug"],
                group=item.get("group"),
                after=list(after) if isinstance(after, list) else [],
                description=item.get("description"),
            )
        )
    return entries


def save_roadmap(cwd: str, entries: list[RoadmapEntry]) -> None:
    """Write entries back to todos/roadmap.yaml."""
    path = _roadmap_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)

    data: list[RoadmapDict] = []
    for entry in entries:
        item: RoadmapDict = {"slug": entry.slug}
        if entry.group:
            item["group"] = entry.group
        if entry.after:
            item["after"] = entry.after
        if entry.description:
            item["description"] = entry.description
        data.append(item)

    header = "# Priority order (first = highest). Per-item state in {slug}/state.yaml.\n\n"
    body = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    write_text_sync(path, header + body)


def load_roadmap_slugs(cwd: str) -> list[str]:
    """Return slug strings in roadmap order."""
    return [e.slug for e in load_roadmap(cwd)]


def load_roadmap_deps(cwd: str) -> dict[str, list[str]]:
    """Return dependency graph dict from roadmap (replaces read_dependencies)."""
    return {e.slug: e.after for e in load_roadmap(cwd) if e.after}


def add_to_roadmap(
    cwd: str,
    slug: str,
    *,
    group: str | None = None,
    after: list[str] | None = None,
    description: str | None = None,
    before: str | None = None,
) -> bool:
    """Add entry to roadmap.yaml at specified position (default: append).

    Returns True if the entry was added, False if it already existed.
    """
    entries = load_roadmap(cwd)
    # Avoid duplicates
    if any(e.slug == slug for e in entries):
        return False

    entry = RoadmapEntry(slug=slug, group=group, after=after or [], description=description)

    if before:
        for i, e in enumerate(entries):
            if e.slug == before:
                entries.insert(i, entry)
                save_roadmap(cwd, entries)
                return True

    entries.append(entry)
    save_roadmap(cwd, entries)
    return True


def remove_from_roadmap(cwd: str, slug: str) -> bool:
    """Remove entry from roadmap.yaml. Returns True if found and removed."""
    entries = load_roadmap(cwd)
    original_len = len(entries)
    entries = [e for e in entries if e.slug != slug]
    if len(entries) < original_len:
        save_roadmap(cwd, entries)
        return True
    return False


def move_in_roadmap(cwd: str, slug: str, *, before: str | None = None, after: str | None = None) -> bool:
    """Reorder entry in roadmap.yaml. Returns True if moved successfully."""
    entries = load_roadmap(cwd)
    source_idx = None
    for i, e in enumerate(entries):
        if e.slug == slug:
            source_idx = i
            break
    if source_idx is None:
        return False

    entry = entries.pop(source_idx)

    target: str | None = before or after
    target_idx = None
    for i, e in enumerate(entries):
        if e.slug == target:
            target_idx = i
            break

    if target_idx is None:
        entries.insert(source_idx, entry)
        return False

    if before:
        entries.insert(target_idx, entry)
    else:
        entries.insert(target_idx + 1, entry)
    save_roadmap(cwd, entries)
    return True


def check_dependencies_satisfied(cwd: str, slug: str, deps: dict[str, list[str]]) -> bool:
    """Check if all dependencies for a slug are satisfied.

    A dependency is satisfied if:
    - Its phase is "done" in state.yaml, OR
    - It is not present in roadmap.yaml (assumed completed/removed)

    Args:
        cwd: Project root directory
        slug: Work item to check
        deps: Dependency graph

    Returns:
        True if all dependencies are satisfied (or no dependencies)
    """
    item_deps = deps.get(slug, [])
    if not item_deps:
        return True

    for dep in item_deps:
        if not slug_in_roadmap(cwd, dep):
            # Not in roadmap - treat as satisfied (completed and cleaned up)
            continue

        dep_state = read_phase_state(cwd, dep)
        dep_phase = dep_state.get("phase")
        if dep_phase == ItemPhase.DONE.value:
            continue

        dep_review = dep_state.get(PhaseName.REVIEW.value)
        if dep_review == PhaseStatus.APPROVED.value:
            continue

        # Backward compatibility with older state where only build/review fields
        # were used and "phase" was derived later.
        if (
            dep_state.get(PhaseName.BUILD.value) == PhaseStatus.COMPLETE.value
            and dep_state.get(PhaseName.REVIEW.value) == PhaseStatus.APPROVED.value
        ):
            continue

        return False

    return True


# =============================================================================
# Icebox Management (icebox.yaml)
# =============================================================================


def _icebox_dir(cwd: str) -> Path:
    """Return the _icebox/ directory path (todos/_icebox)."""
    return Path(cwd) / "todos" / "_icebox"


def _icebox_path(cwd: str) -> Path:
    return _icebox_dir(cwd) / "icebox.yaml"


def load_icebox(cwd: str) -> list[RoadmapEntry]:
    """Parse todos/icebox.yaml and return ordered list of entries."""
    path = _icebox_path(cwd)
    if not path.exists():
        return []

    content = read_text_sync(path)
    raw = yaml.safe_load(content)
    if not isinstance(raw, list):
        return []

    entries: list[RoadmapEntry] = []
    for item in raw:
        if not isinstance(item, dict) or "slug" not in item:
            continue
        after = item.get("after")
        entries.append(
            RoadmapEntry(
                slug=item["slug"],
                group=item.get("group"),
                after=list(after) if isinstance(after, list) else [],
                description=item.get("description"),
            )
        )
    return entries


def save_icebox(cwd: str, entries: list[RoadmapEntry]) -> None:
    """Write entries back to todos/icebox.yaml."""
    path = _icebox_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)

    data: list[RoadmapDict] = []
    for entry in entries:
        item: RoadmapDict = {"slug": entry.slug}
        if entry.group:
            item["group"] = entry.group
        if entry.after:
            item["after"] = entry.after
        if entry.description:
            item["description"] = entry.description
        data.append(item)

    header = "# Parked work items. Promote back to roadmap.yaml when priority changes.\n\n"
    body = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    write_text_sync(path, header + body)


def load_icebox_slugs(cwd: str) -> list[str]:
    """Return slug strings in icebox order."""
    return [e.slug for e in load_icebox(cwd)]


def remove_from_icebox(cwd: str, slug: str) -> bool:
    """Remove entry from icebox.yaml. Returns True if found and removed."""
    entries = load_icebox(cwd)
    original_len = len(entries)
    entries = [e for e in entries if e.slug != slug]
    if len(entries) < original_len:
        save_icebox(cwd, entries)
        return True
    return False


def clean_dependency_references(cwd: str, slug: str) -> None:
    """Remove a slug from all `after` dependency lists in roadmap and icebox.

    Args:
        cwd: Project root directory
        slug: Slug to remove from dependency lists
    """
    # Clean roadmap
    roadmap_entries = load_roadmap(cwd)
    roadmap_changed = False
    for entry in roadmap_entries:
        if slug in entry.after:
            entry.after.remove(slug)
            roadmap_changed = True
    if roadmap_changed:
        save_roadmap(cwd, roadmap_entries)

    # Clean icebox
    icebox_entries = load_icebox(cwd)
    icebox_changed = False
    for entry in icebox_entries:
        if slug in entry.after:
            entry.after.remove(slug)
            icebox_changed = True
    if icebox_changed:
        save_icebox(cwd, icebox_entries)


def freeze_to_icebox(cwd: str, slug: str) -> bool:
    """Move a slug from roadmap to icebox (prepended). Returns False if not in roadmap."""
    entries = load_roadmap(cwd)
    entry = None
    for i, e in enumerate(entries):
        if e.slug == slug:
            entry = entries.pop(i)
            break
    if entry is None:
        return False

    save_roadmap(cwd, entries)

    icebox = load_icebox(cwd)
    icebox.insert(0, entry)
    save_icebox(cwd, icebox)

    # Move folder if it exists
    src = Path(cwd) / "todos" / slug
    if src.exists():
        dest_dir = _icebox_dir(cwd)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / slug
        if dest.exists():
            raise FileExistsError(f"Cannot freeze: destination already exists at {dest}")
        shutil.move(str(src), str(dest))

    return True


def unfreeze_from_icebox(cwd: str, slug: str) -> bool:
    """Move a slug from icebox back to roadmap (appended). Returns False if not in icebox."""
    icebox = load_icebox(cwd)
    entry = None
    for i, e in enumerate(icebox):
        if e.slug == slug:
            entry = icebox.pop(i)
            break
    if entry is None:
        return False

    save_icebox(cwd, icebox)

    roadmap = load_roadmap(cwd)
    roadmap.append(entry)
    save_roadmap(cwd, roadmap)

    # Move folder back if it exists in _icebox/
    src = _icebox_dir(cwd) / slug
    if src.exists():
        dest = Path(cwd) / "todos" / slug
        if dest.exists():
            raise FileExistsError(f"Cannot unfreeze: destination already exists at {dest}")
        shutil.move(str(src), str(dest))

    return True


def migrate_icebox_to_subfolder(cwd: str) -> int:
    """One-time migration: move icebox folders from todos/ to todos/_icebox/.

    Idempotent: if todos/icebox.yaml is absent but todos/_icebox/icebox.yaml
    exists, the migration is considered done and 0 is returned.

    Returns count of items moved.
    """
    todos_root = Path(cwd) / "todos"
    old_manifest = todos_root / "icebox.yaml"
    new_dir = todos_root / "_icebox"
    new_manifest = new_dir / "icebox.yaml"

    if not old_manifest.exists():
        # Already migrated (or nothing to migrate)
        return 0

    new_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    raw = yaml.safe_load(old_manifest.read_text()) or []
    if isinstance(raw, list):
        entries = raw

    moved = 0
    for item in entries:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug") or item.get("group")
        if not slug:
            continue
        src = todos_root / slug
        dest = new_dir / slug
        if src.exists() and not dest.exists():
            shutil.move(str(src), str(dest))
            moved += 1

    # Relocate manifest
    shutil.move(str(old_manifest), str(new_manifest))
    return moved


# =============================================================================
# Delivered Management (delivered.yaml)
# =============================================================================


@dataclass
class DeliveredEntry:
    slug: str
    date: str
    commit: str | None = None
    children: list[str] | None = None


class DeliveredDict(TypedDict, total=False):
    slug: str
    date: str
    commit: str
    children: list[str]


def _delivered_path(cwd: str) -> Path:
    return Path(cwd) / "todos" / "delivered.yaml"


def load_delivered_slugs(cwd: str) -> set[str]:
    """Return set of delivered slugs for fast lookup."""
    return {e.slug for e in load_delivered(cwd)}


def load_delivered(cwd: str) -> list[DeliveredEntry]:
    """Parse todos/delivered.yaml and return ordered list of entries."""
    path = _delivered_path(cwd)
    if not path.exists():
        return []

    content = read_text_sync(path)
    raw = yaml.safe_load(content)
    if not isinstance(raw, list):
        return []

    entries: list[DeliveredEntry] = []
    for item in raw:
        if not isinstance(item, dict) or "slug" not in item:
            continue
        children_raw = item.get("children")
        children = list(children_raw) if isinstance(children_raw, list) else None
        entries.append(
            DeliveredEntry(
                slug=item["slug"],
                date=str(item.get("date", "")),
                commit=item.get("commit"),
                children=children,
            )
        )
    return entries


def save_delivered(cwd: str, entries: list[DeliveredEntry]) -> None:
    """Write entries back to todos/delivered.yaml."""
    path = _delivered_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)

    data: list[DeliveredDict] = []
    for entry in entries:
        item: DeliveredDict = {"slug": entry.slug, "date": entry.date}
        if entry.commit:
            item["commit"] = entry.commit
        if entry.children:
            item["children"] = entry.children
        data.append(item)

    header = "# Delivered work items. Newest first.\n\n"
    body = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    write_text_sync(path, header + body)


def deliver_to_delivered(
    cwd: str,
    slug: str,
    *,
    commit: str | None = None,
) -> bool:
    """Move a slug from roadmap to delivered (prepended). Returns False only if slug is unknown.

    Idempotent: returns True if the slug is already in delivered.yaml.
    If no commit SHA is provided, auto-detects HEAD of the repository.
    """
    entries = load_roadmap(cwd)
    entry = None
    for i, e in enumerate(entries):
        if e.slug == slug:
            entry = entries.pop(i)
            break
    if entry is None:
        # Not in roadmap — check if already delivered (idempotent success)
        if slug in load_delivered_slugs(cwd):
            return True
        # Bugs intentionally skip the roadmap; accept any slug with a todo directory
        if not (Path(cwd) / "todos" / slug).exists():
            return False
    else:
        save_roadmap(cwd, entries)

    if commit is None:
        try:
            repo = Repo(cwd, search_parent_directories=True)
            commit = repo.head.commit.hexsha[:12]
        except (InvalidGitRepositoryError, NoSuchPathError, ValueError):
            pass

    delivered = load_delivered(cwd)
    delivered.insert(
        0,
        DeliveredEntry(
            slug=slug,
            date=date.today().isoformat(),
            commit=commit,
        ),
    )
    save_delivered(cwd, delivered)
    return True


def _run_git_cmd(
    args: list[str], *, cwd: str, timeout: float = 30
) -> tuple[int, str, str]:
    """Run a git command; return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.warning("git %s timed out after %.0fs", " ".join(args[:2]), timeout)
        return 1, "", f"timeout after {timeout}s"


def cleanup_delivered_slug(
    cwd: str,
    slug: str,
    *,
    branch: str | None = None,
    remove_remote_branch: bool = True,
) -> None:
    """Idempotent cleanup of all physical artifacts for a delivered slug.

    Each step is a no-op if the artifact is already gone.

    Args:
        cwd: Project root directory.
        slug: Work item slug.
        branch: Git branch name (defaults to slug).
        remove_remote_branch: Whether to delete the remote tracking branch.
    """
    branch = branch or slug

    # 1. Remove worktree
    worktree_path = Path(cwd) / WORKTREE_DIR / slug
    if worktree_path.exists():
        rc, _, stderr = _run_git_cmd(["worktree", "remove", "--force", str(worktree_path)], cwd=cwd, timeout=10)
        if rc != 0:
            logger.warning("worktree remove failed for %s: %s", slug, stderr.strip())

    # 2. Delete local branch
    _run_git_cmd(["branch", "-D", branch], cwd=cwd)

    # 3. Delete remote branch (non-fatal, tight timeout)
    if remove_remote_branch:
        _run_git_cmd(["push", "origin", "--delete", branch], cwd=cwd, timeout=5)

    # 4. Remove todo directory
    todo_dir = Path(cwd) / "todos" / slug
    if todo_dir.exists():
        shutil.rmtree(str(todo_dir), ignore_errors=True)

    # 5. Clean dependency references
    clean_dependency_references(cwd, slug)


def sweep_completed_groups(cwd: str) -> list[str]:
    """Auto-deliver group parents whose children are all delivered.

    A group parent is any todo with a non-empty breakdown.todos list.
    When every child slug appears in delivered.yaml, the parent is
    delivered and its todo directory removed.

    Returns list of swept group slugs.
    """
    todos_dir = Path(cwd) / "todos"
    if not todos_dir.is_dir():
        return []

    delivered_slugs = load_delivered_slugs(cwd)
    swept: list[str] = []

    for entry in sorted(todos_dir.iterdir()):
        if not entry.is_dir():
            continue
        state_path = entry / "state.yaml"
        # Backward compat: fall back to state.json
        if not state_path.exists():
            legacy_path = entry / "state.json"
            if legacy_path.exists():
                state_path = legacy_path
        if not state_path.exists():
            continue

        try:
            state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            continue

        breakdown = state.get("breakdown")
        if not isinstance(breakdown, dict):
            continue
        children = breakdown.get("todos")
        if not isinstance(children, list) or not children:
            continue

        # Check if ALL children have been delivered
        if not all(child in delivered_slugs for child in children):
            continue

        group_slug = entry.name

        delivered = deliver_to_delivered(cwd, group_slug)

        if delivered:
            # deliver_to_delivered added entry without children — patch it in
            entries = load_delivered(cwd)
            for d_entry in entries:
                if d_entry.slug == group_slug and d_entry.children is None:
                    d_entry.children = list(children)
                    break
            save_delivered(cwd, entries)
        else:
            # Not in roadmap — add directly to delivered.yaml with children
            try:
                repo = Repo(cwd, search_parent_directories=True)
                head_sha: str | None = repo.head.commit.hexsha[:12]
            except (InvalidGitRepositoryError, NoSuchPathError, ValueError):
                head_sha = None
            entries = load_delivered(cwd)
            entries.insert(
                0,
                DeliveredEntry(
                    slug=group_slug,
                    date=date.today().isoformat(),
                    commit=head_sha,
                    children=list(children),
                ),
            )
            save_delivered(cwd, entries)

        # Clean up physical artifacts (worktree/branch no-op for group parents)
        cleanup_delivered_slug(cwd, group_slug, remove_remote_branch=False)
        swept.append(group_slug)
        logger.info("Group sweep: delivered %s (all %d children complete)", group_slug, len(children))

    return swept


# =============================================================================
# Dependency Management
# =============================================================================


def detect_circular_dependency(deps: dict[str, list[str]], slug: str, new_deps: list[str]) -> list[str] | None:
    """Detect if adding new_deps to slug would create a cycle.

    Args:
        deps: Current dependency graph
        slug: Item we're updating
        new_deps: New dependencies for slug

    Returns:
        List representing the cycle path if cycle detected, None otherwise
    """
    # Build graph with proposed change
    graph: dict[str, set[str]] = {k: set(v) for k, v in deps.items()}
    graph[slug] = set(new_deps)

    # DFS to detect cycle
    visited: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> list[str] | None:
        if node in path:
            # Found cycle - return path from cycle start
            cycle_start = path.index(node)
            return path[cycle_start:] + [node]

        if node in visited:
            return None

        visited.add(node)
        path.append(node)

        for dep in graph.get(node, set()):
            result = dfs(dep)
            if result:
                return result

        path.pop()
        return None

    # Check from the slug we're modifying
    for dep in new_deps:
        path = [slug]
        visited = {slug}
        result = dfs(dep)
        if result:
            return [slug] + result

    return None


def check_review_status(cwd: str, slug: str) -> str:
    """Check review status for a work item.

    Returns:
        - "missing" if review-findings.md doesn't exist
        - "approved" if contains "[x] APPROVE"
        - "changes_requested" otherwise
    """
    review_path = Path(cwd) / "todos" / slug / "review-findings.md"
    if not review_path.exists():
        return "missing"

    content = read_text_sync(review_path)
    if REVIEW_APPROVE_MARKER in content:
        return PhaseStatus.APPROVED.value
    return PhaseStatus.CHANGES_REQUESTED.value


# =============================================================================
# Agent Availability
# =============================================================================


async def compose_agent_guidance(db: Db) -> str:
    """Compose runtime availability guidance for agent selection.

    Agent characteristics (strengths, cognitive profiles) are documented in the
    baseline concept snippet 'general/concept/agent-characteristics' and loaded
    into every agent's context. This function only adds runtime availability
    information (enabled/disabled, degraded status).
    """
    lines = ["AGENT SELECTION GUIDANCE:"]
    lines.append("")
    lines.append("Agent characteristics are in your baseline context (Agent Characteristics concept).")
    lines.append("Runtime availability:")

    # Clear expired availability first
    await db.clear_expired_agent_availability()

    listed_count = 0

    for agent_name in AgentName:
        name = agent_name.value
        cfg = app_config.agents.get(name)
        if not cfg or not cfg.enabled:
            continue

        # Check runtime status
        availability_raw = await db.get_agent_availability(name)
        availability = availability_raw if isinstance(availability_raw, dict) else None
        status_note = ""
        if availability:
            status = availability.get("status")
            if status == "unavailable":
                continue  # Skip completely
            if status == "degraded":
                reason = availability.get("reason", "unknown reason")
                status_note = f" [DEGRADED: {reason}]"

        listed_count += 1
        if status_note:
            lines.append(f"- {name.upper()}{status_note}")
        else:
            lines.append(f"- {name.upper()}: available")

    if listed_count == 0:
        raise RuntimeError("No agents are currently enabled and available.")

    lines.append("")
    lines.append("THINKING MODES:")
    lines.append("- fast: simple tasks, text editing, quick logic")
    lines.append("- med: standard coding, refactoring, review")
    lines.append("- slow: complex reasoning, architecture, planning, root cause analysis")

    return "\n".join(lines)


def read_text_sync(path: Path) -> str:
    """Read text from a file in a typed sync wrapper."""
    return path.read_text(encoding="utf-8")


def write_text_sync(path: Path, content: str) -> None:
    """Write text to a file in a typed sync wrapper."""
    path.write_text(content, encoding="utf-8")


async def read_text_async(path: Path) -> str:
    """Read text from a file without blocking the event loop."""
    return await asyncio.to_thread(read_text_sync, path)


async def write_text_async(path: Path, content: str) -> None:
    """Write text to a file without blocking the event loop."""
    await asyncio.to_thread(write_text_sync, path, content)


def _sync_file(src_root: Path, dst_root: Path, relative_path: str) -> bool:
    """Copy one file from src root to dst root if source exists.

    Returns True when a copy happened, False when source is missing or unchanged.
    """
    src = src_root / relative_path
    dst = dst_root / relative_path
    if not src.exists():
        return False
    if dst.exists() and _file_contents_match(src, dst):
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _file_sha256(path: Path) -> str:
    """Return sha256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_contents_match(src: Path, dst: Path) -> bool:
    """Return True when src and dst bytes are identical."""
    try:
        src_stat = src.stat()
        dst_stat = dst.stat()
    except OSError:
        return False
    if src_stat.st_size != dst_stat.st_size:
        return False
    try:
        return _file_sha256(src) == _file_sha256(dst)
    except OSError:
        return False


def sync_main_to_worktree(cwd: str, slug: str, extra_files: list[str] | None = None) -> int:
    """Copy orchestrator-owned planning files from main repo into a slug worktree."""
    main_root = Path(cwd)
    worktree_root = Path(cwd) / WORKTREE_DIR / slug
    if not worktree_root.exists():
        return 0
    files = ["todos/roadmap.yaml"]
    if extra_files:
        files.extend(extra_files)
    copied = 0
    for rel in files:
        if _sync_file(main_root, worktree_root, rel):
            copied += 1
    return copied


def sync_main_planning_to_all_worktrees(cwd: str) -> None:
    """Propagate main planning files to every existing worktree."""
    trees_root = Path(cwd) / WORKTREE_DIR
    if not trees_root.exists():
        return
    for entry in trees_root.iterdir():
        if entry.is_dir():
            sync_main_to_worktree(cwd, entry.name)


def _dirty_paths(repo: Repo) -> list[str]:
    """Return dirty paths from porcelain status output."""
    lines = repo.git.status("--porcelain").splitlines()
    paths: list[str] = []
    for line in lines:
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            paths.append(path)
    return paths


def build_git_hook_env(project_root: str, base_env: dict[str, str]) -> dict[str, str]:
    """Build environment variables for git hooks, ensuring venv/bin is in PATH."""
    env = base_env.copy()
    venv_bin = str(Path(project_root) / ".venv" / "bin")
    path = env.get("PATH", "")
    parts = path.split(os.pathsep)
    if venv_bin not in parts:
        parts.insert(0, venv_bin)
    else:
        # Move to front if already present
        parts.remove(venv_bin)
        parts.insert(0, venv_bin)
    env["PATH"] = os.pathsep.join(parts)
    env["VIRTUAL_ENV"] = str(Path(project_root) / ".venv")
    return env


def has_uncommitted_changes(cwd: str, slug: str) -> bool:
    """Check if worktree has uncommitted changes.

    Args:
        cwd: Project root directory
        slug: Work item slug (worktree is at trees/{slug})

    Returns:
        True if there are non-orchestrator uncommitted changes (staged or unstaged)
    """
    worktree_path = Path(cwd) / WORKTREE_DIR / slug
    if not worktree_path.exists():
        return False

    try:
        repo = Repo(worktree_path)
        dirty_paths = _dirty_paths(repo)
        if not dirty_paths:
            return False

        # Orchestrator control files are expected to drift while mirroring main
        # planning state into worktrees. The slug todo subtree can also appear
        # as untracked on older worktree branches before the first commit.
        ignored = {
            ".teleclaude",
            ".teleclaude/",
            _WORKTREE_PREP_STATE_REL,
            "todos/roadmap.yaml",
            f"todos/{slug}",
            f"todos/{slug}/",
        }
        for path in dirty_paths:
            normalized = path.replace("\\", "/")
            if normalized.startswith(".teleclaude/"):
                continue
            if normalized in ignored or normalized.startswith(f"todos/{slug}/"):
                continue
            if normalized not in ignored:
                return True
        return False
    except InvalidGitRepositoryError:
        logger.warning("Invalid git repository at %s", worktree_path)
        return False


def get_stash_entries(cwd: str) -> list[str]:
    """Return git stash entries for the repository at cwd.

    Stash state is repository-wide (shared by all worktrees), so this check is
    intentionally evaluated at repo scope.
    """
    try:
        repo = Repo(cwd)
        raw = cast(str, repo.git.stash("list"))
        return [line.strip() for line in raw.splitlines() if line.strip()]
    except (InvalidGitRepositoryError, NoSuchPathError):
        logger.warning("Invalid git repository path for stash lookup: %s", cwd)
        return []
    except GitCommandError as exc:
        logger.warning("Unable to read git stash list at %s: %s", cwd, exc)
        return []


def has_git_stash_entries(cwd: str) -> bool:
    """Return True when repository stash contains one or more entries."""
    return bool(get_stash_entries(cwd))


# ---------------------------------------------------------------------------
def _worktree_prep_state_path(cwd: str, slug: str) -> Path:
    """Get prep-state marker path inside worktree."""
    return Path(cwd) / WORKTREE_DIR / slug / _WORKTREE_PREP_STATE_REL


def _compute_prep_inputs_digest(cwd: str, slug: str) -> str:
    """Compute hash of dependency-installation inputs that impact prep."""
    project_root = Path(cwd)
    worktree_root = project_root / WORKTREE_DIR / slug
    digest = hashlib.sha256()

    candidates: list[tuple[str, Path]] = []
    for rel in _PREP_ROOT_INPUT_FILES:
        candidates.append((f"root:{rel}", project_root / rel))
    for rel in _PREP_INPUT_FILES:
        candidates.append((f"worktree:{rel}", worktree_root / rel))

    for label, path in sorted(candidates, key=lambda item: item[0]):
        digest.update(label.encode("utf-8"))
        exists = path.exists()
        digest.update(b"1" if exists else b"0")
        if not exists:
            continue
        is_executable = os.access(path, os.X_OK)
        digest.update(b"1" if is_executable else b"0")
        if path.is_file():
            digest.update(_file_sha256(path).encode("utf-8"))
    return digest.hexdigest()


def _read_worktree_prep_state(cwd: str, slug: str) -> dict[str, str] | None:
    """Read prep-state marker written after successful prep."""
    state_path = _worktree_prep_state_path(cwd, slug)
    if not state_path.exists():
        return None
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    version = raw.get("version")
    digest = raw.get("inputs_digest")
    if not isinstance(version, int) or version != _PREP_STATE_VERSION:
        return None
    if not isinstance(digest, str) or not digest:
        return None
    return {"inputs_digest": digest}


def _write_worktree_prep_state(cwd: str, slug: str, inputs_digest: str) -> None:
    """Persist prep-state marker after successful preparation."""
    state_path = _worktree_prep_state_path(cwd, slug)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _PREP_STATE_VERSION,
        "inputs_digest": inputs_digest,
        "prepared_at": datetime.now(UTC).isoformat(),
    }
    state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _decide_worktree_prep(cwd: str, slug: str, created: bool) -> WorktreePrepDecision:
    """Decide whether prep is required for a slug worktree."""
    inputs_digest = _compute_prep_inputs_digest(cwd, slug)
    if created:
        return WorktreePrepDecision(should_prepare=True, reason="worktree_created", inputs_digest=inputs_digest)
    state = _read_worktree_prep_state(cwd, slug)
    if state is None:
        return WorktreePrepDecision(should_prepare=True, reason="prep_state_missing", inputs_digest=inputs_digest)
    if state.get("inputs_digest") != inputs_digest:
        return WorktreePrepDecision(should_prepare=True, reason="prep_inputs_changed", inputs_digest=inputs_digest)
    return WorktreePrepDecision(should_prepare=False, reason="unchanged_known_good", inputs_digest=inputs_digest)


def _create_or_attach_worktree(cwd: str, slug: str) -> bool:
    """Ensure the slug worktree path exists by creating or reattaching its branch."""
    worktree_path = Path(cwd) / WORKTREE_DIR / slug
    if worktree_path.exists():
        return False

    try:
        repo = Repo(cwd)
    except InvalidGitRepositoryError:
        logger.error("Cannot create worktree: %s is not a git repository", cwd)
        raise

    trees_dir = Path(cwd) / WORKTREE_DIR
    trees_dir.mkdir(exist_ok=True)

    try:
        # Fetch latest main and branch from origin/main (not local HEAD)
        repo.git.fetch("origin", "main")
        repo.git.worktree("add", str(worktree_path), "-b", slug, "origin/main")
    except GitCommandError as exc:
        branch_exists = any(head.name == slug for head in repo.heads)
        if not branch_exists:
            logger.error(
                "Failed to create worktree for slug=%s cwd=%s worktree_path=%s branch_exists=%s: %s",
                slug,
                cwd,
                worktree_path,
                branch_exists,
                exc,
                exc_info=True,
            )
            raise
        try:
            repo.git.worktree("add", str(worktree_path), slug)
        except GitCommandError as attach_exc:
            logger.error(
                "Failed to create worktree for slug=%s cwd=%s worktree_path=%s branch_exists=%s: %s",
                slug,
                cwd,
                worktree_path,
                branch_exists,
                attach_exc,
                exc_info=True,
            )
            raise

    logger.info("Created worktree at %s", worktree_path)
    return True


def ensure_worktree_with_policy(cwd: str, slug: str) -> EnsureWorktreeResult:
    """Ensure worktree exists and run prep only when policy says it's stale."""
    created = _create_or_attach_worktree(cwd, slug)
    prep_decision = _decide_worktree_prep(cwd, slug, created=created)
    if prep_decision.should_prepare:
        _prepare_worktree(cwd, slug)
        _write_worktree_prep_state(cwd, slug, prep_decision.inputs_digest)
        return EnsureWorktreeResult(created=created, prepared=True, prep_reason=prep_decision.reason)
    return EnsureWorktreeResult(created=created, prepared=False, prep_reason=prep_decision.reason)


async def ensure_worktree_with_policy_async(cwd: str, slug: str) -> EnsureWorktreeResult:
    """Async wrapper to ensure worktree with prep decision policy."""
    return await asyncio.to_thread(ensure_worktree_with_policy, cwd, slug)


def _prepare_worktree(cwd: str, slug: str) -> None:
    """Prepare a worktree using repo conventions.

    Conventions:
    - If `scripts.worktree:prepare` is defined in teleclaude.yml, run it.
    - Else if tools/worktree-prepare.sh exists and is executable, run it with the slug.
    - If Makefile has `install`, run `make install`.
    - Else if package.json exists, run `pnpm install` if available, otherwise `npm install`.
    - If neither applies, do nothing.
    """
    worktree_path = Path(cwd) / WORKTREE_DIR / slug
    worktree_prepare_script = Path(cwd) / "tools" / "worktree-prepare.sh"
    makefile = worktree_path / "Makefile"
    package_json = worktree_path / "package.json"

    def _has_make_target(target: str) -> bool:
        try:
            content = makefile.read_text(encoding="utf-8")
        except OSError:
            return False
        return re.search(rf"^{re.escape(target)}\s*:", content, re.MULTILINE) is not None

    if worktree_prepare_script.exists() and os.access(worktree_prepare_script, os.X_OK):
        cmd = [str(worktree_prepare_script), slug]
        logger.info("Preparing worktree with: %s", " ".join(cmd))
        try:
            subprocess.run(
                cmd,
                cwd=str(Path(cwd)),
                check=True,
                capture_output=True,
                text=True,
            )
            return
        except subprocess.CalledProcessError as e:
            msg = (
                f"Worktree preparation failed for {slug}:\n"
                f"Command: {' '.join(cmd)}\n"
                f"Exit code: {e.returncode}\n"
                f"stdout: {e.stdout or ''}\n"
                f"stderr: {e.stderr or ''}"
            )
            logger.error(msg)
            raise RuntimeError(msg) from e

    if makefile.exists() and _has_make_target("install"):
        logger.info("Preparing worktree with: make install")
        try:
            subprocess.run(
                ["make", "install"],
                cwd=str(worktree_path),
                check=True,
                capture_output=True,
                text=True,
            )
            return
        except subprocess.CalledProcessError as e:
            msg = (
                f"Worktree preparation failed for {slug}:\n"
                f"Command: make install\n"
                f"Exit code: {e.returncode}\n"
                f"stdout: {e.stdout or ''}\n"
                f"stderr: {e.stderr or ''}"
            )
            logger.error(msg)
            raise RuntimeError(msg) from e

    if package_json.exists():
        use_pnpm = False
        if (worktree_path / "pnpm-lock.yaml").exists():
            use_pnpm = True
        else:
            use_pnpm = shutil.which("pnpm") is not None
        cmd = ["pnpm", "install"] if use_pnpm else ["npm", "install"]
        logger.info("Preparing worktree with: %s", " ".join(cmd))
        try:
            subprocess.run(
                cmd,
                cwd=str(worktree_path),
                check=True,
                capture_output=True,
                text=True,
            )
            return
        except subprocess.CalledProcessError as e:
            msg = (
                f"Worktree preparation failed for {slug}:\n"
                f"Command: {' '.join(cmd)}\n"
                f"Exit code: {e.returncode}\n"
                f"stdout: {e.stdout or ''}\n"
                f"stderr: {e.stderr or ''}"
            )
            logger.error(msg)
            raise RuntimeError(msg) from e

    logger.info("No worktree preparation targets found for %s", slug)


# =============================================================================
# Main Functions
# =============================================================================


# =============================================================================
# Prepare State Machine — event emission
# =============================================================================


def _emit_prepare_event(event_type: str, payload: dict[str, str | list[str]]) -> None:
    """Fire-and-forget lifecycle event emission for prepare state machine."""
    from teleclaude.events.envelope import EventLevel
    from teleclaude.events.producer import emit_event

    async def _emit() -> None:
        try:
            slug = str(payload.get("slug", ""))
            description = f"prepare.{event_type.split('.')[-1]}: {slug}"
            await emit_event(
                event=event_type,
                source=f"orchestrator/{os.environ.get('TELECLAUDE_SESSION_ID', 'unknown')}",
                level=EventLevel.WORKFLOW,
                domain="software-development",
                description=description,
                entity=slug,
                payload=dict(payload),
            )
        except Exception:
            pass  # Never block prepare on event emission failure

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_emit())
    except RuntimeError:
        # No running loop (thread or sync CLI context) — fire-and-forget via new event loop
        try:
            asyncio.run(_emit())
        except Exception:
            pass  # Never block prepare on event emission failure


# =============================================================================
# Prepare State Machine — phase derivation
# =============================================================================


def _derive_prepare_phase(slug: str, cwd: str, state: dict[str, StateValue]) -> PreparePhase:
    """Derive the initial prepare phase from artifact existence when no durable phase is set."""
    has_input = check_file_exists(cwd, f"todos/{slug}/input.md")
    has_requirements = check_file_has_content(cwd, f"todos/{slug}/requirements.md")

    if has_input and not has_requirements:
        return PreparePhase.INPUT_ASSESSMENT
    if not has_requirements:
        return PreparePhase.TRIANGULATION

    req_review = state.get("requirements_review", {})
    req_verdict = (isinstance(req_review, dict) and req_review.get("verdict")) or ""
    if not req_verdict or req_verdict == "needs_work":
        return PreparePhase.REQUIREMENTS_REVIEW

    has_plan = check_file_has_content(cwd, f"todos/{slug}/implementation-plan.md")
    if not has_plan:
        return PreparePhase.PLAN_DRAFTING

    plan_review = state.get("plan_review", {})
    plan_verdict = (isinstance(plan_review, dict) and plan_review.get("verdict")) or ""
    if not plan_verdict or plan_verdict == "needs_work":
        return PreparePhase.PLAN_REVIEW

    dor = state.get("dor", {})
    dor_score = dor.get("score") if isinstance(dor, dict) else None
    if not (isinstance(dor_score, int) and dor_score >= DOR_READY_THRESHOLD):
        return PreparePhase.GATE

    return PreparePhase.GROUNDING_CHECK


# =============================================================================
# Prepare State Machine — phase handlers
# =============================================================================


async def _prepare_step_input_assessment(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """INPUT_ASSESSMENT: choose requirements strategy and produce requirements."""
    if check_file_has_content(cwd, f"todos/{slug}/requirements.md"):
        state["prepare_phase"] = PreparePhase.REQUIREMENTS_REVIEW.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        return True, ""  # loop

    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        command=SlashCommand.NEXT_PREPARE_DISCOVERY,
        args=slug,
        project=cwd,
        guidance=guidance,
        subfolder="",
        note=(
            f"Assess todos/{slug}/input.md and produce todos/{slug}/requirements.md. "
            "Work solo if the input is already concrete enough. If important intent, "
            "constraints, or code grounding still need another perspective, run "
            "triangulated discovery with a complementary partner."
        ),
        next_call=f"telec todo prepare {slug}",
    )


async def _prepare_step_triangulation(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """TRIANGULATION: requirements.md still needs discovery or revision."""
    if check_file_has_content(cwd, f"todos/{slug}/requirements.md"):
        # Transition to REQUIREMENTS_REVIEW
        state["prepare_phase"] = PreparePhase.REQUIREMENTS_REVIEW.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.requirements_drafted", {"slug": slug})
        return True, ""  # loop

    _emit_prepare_event("domain.software-development.prepare.triangulation_started", {"slug": slug})
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        command=SlashCommand.NEXT_PREPARE_DISCOVERY,
        args=slug,
        project=cwd,
        guidance=guidance,
        subfolder="",
        note=(
            f"Produce todos/{slug}/requirements.md. Use solo discovery if you already have "
            "enough grounding; otherwise triangulate with a complementary partner before writing."
        ),
        next_call=f"telec todo prepare {slug}",
    )


async def _prepare_step_requirements_review(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """REQUIREMENTS_REVIEW: awaiting review verdict."""
    req_review = state.get("requirements_review", {})
    verdict = (isinstance(req_review, dict) and req_review.get("verdict")) or ""

    if verdict == "approve":
        state["prepare_phase"] = PreparePhase.PLAN_DRAFTING.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.requirements_approved", {"slug": slug})
        return True, ""  # loop

    if verdict == "needs_work":
        if isinstance(req_review, dict):
            rounds = int(req_review.get("rounds", 0)) + 1
            req_review["rounds"] = rounds
            req_review["verdict"] = ""
        else:
            rounds = 1
        # I3: block after exceeding max review rounds to prevent infinite cycles
        if rounds > DEFAULT_MAX_REVIEW_ROUNDS:
            state["requirements_review"] = req_review  # type: ignore[assignment]
            state["prepare_phase"] = PreparePhase.BLOCKED.value
            await asyncio.to_thread(write_phase_state, cwd, slug, state)
            return False, (
                f"BLOCKED: {slug} requirements review exceeded {DEFAULT_MAX_REVIEW_ROUNDS} rounds. "
                f"Manual resolution required.\n\n"
                f"Before acting, load the relevant worker role:\n"
                f"  telec docs index\n"
                f"Then use telec docs get to load the procedure for the role you are assuming."
            )
        # Loop back to TRIANGULATION with findings
        state["prepare_phase"] = PreparePhase.TRIANGULATION.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        # Attach findings if present
        findings_path = Path(cwd) / "todos" / slug / "requirements-review-findings.md"
        findings_note = ""
        if findings_path.exists():
            findings_note = f"\n\nReview findings:\n{read_text_sync(findings_path)}"
        guidance = await compose_agent_guidance(db)
        return False, format_tool_call(
            command=SlashCommand.NEXT_PREPARE_DISCOVERY,
            args=slug,
            project=cwd,
            guidance=guidance,
            subfolder="",
            note=f"Requirements need revision based on review feedback.{findings_note}",
            next_call=f"telec todo prepare {slug}",
        )

    # No verdict yet — dispatch reviewer
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        command=SlashCommand.NEXT_REVIEW_REQUIREMENTS,
        args=slug,
        project=cwd,
        guidance=guidance,
        subfolder="",
        note=f"Review todos/{slug}/requirements.md and write verdict to state.yaml requirements_review.verdict.",
        next_call=f"telec todo prepare {slug}",
    )


async def _prepare_step_plan_drafting(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """PLAN_DRAFTING: implementation-plan.md needed."""
    if check_file_has_content(cwd, f"todos/{slug}/implementation-plan.md"):
        state["prepare_phase"] = PreparePhase.PLAN_REVIEW.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.plan_drafted", {"slug": slug})
        return True, ""  # loop

    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        command=SlashCommand.NEXT_PREPARE_DRAFT,
        args=slug,
        project=cwd,
        guidance=guidance,
        subfolder="",
        note=(
            f"Ground the approved requirements for todos/{slug}. If the work is atomic, "
            f"write todos/{slug}/implementation-plan.md and demo.md. If planning shows the "
            "parent is too large, split it into child todos and update the holder breakdown."
        ),
        next_call=f"telec todo prepare {slug}",
    )


async def _prepare_step_plan_review(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """PLAN_REVIEW: awaiting plan review verdict."""
    plan_review = state.get("plan_review", {})
    verdict = (isinstance(plan_review, dict) and plan_review.get("verdict")) or ""

    if verdict == "approve":
        state["prepare_phase"] = PreparePhase.GATE.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.plan_approved", {"slug": slug})
        return True, ""  # loop

    if verdict == "needs_work":
        if isinstance(plan_review, dict):
            rounds = int(plan_review.get("rounds", 0)) + 1
            plan_review["rounds"] = rounds
            plan_review["verdict"] = ""
        else:
            rounds = 1
        # I3: block after exceeding max review rounds to prevent infinite cycles
        if rounds > DEFAULT_MAX_REVIEW_ROUNDS:
            state["plan_review"] = plan_review  # type: ignore[assignment]
            state["prepare_phase"] = PreparePhase.BLOCKED.value
            await asyncio.to_thread(write_phase_state, cwd, slug, state)
            return False, (
                f"BLOCKED: {slug} plan review exceeded {DEFAULT_MAX_REVIEW_ROUNDS} rounds. "
                f"Manual resolution required.\n\n"
                f"Before acting, load the relevant worker role:\n"
                f"  telec docs index\n"
                f"Then use telec docs get to load the procedure for the role you are assuming."
            )
        # Loop back to PLAN_DRAFTING with findings
        state["prepare_phase"] = PreparePhase.PLAN_DRAFTING.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        findings_path = Path(cwd) / "todos" / slug / "plan-review-findings.md"
        findings_note = ""
        if findings_path.exists():
            findings_note = f"\n\nReview findings:\n{read_text_sync(findings_path)}"
        guidance = await compose_agent_guidance(db)
        return False, format_tool_call(
            command=SlashCommand.NEXT_PREPARE_DRAFT,
            args=slug,
            project=cwd,
            guidance=guidance,
            subfolder="",
            note=f"Implementation plan needs revision based on review feedback.{findings_note}",
            next_call=f"telec todo prepare {slug}",
        )

    # No verdict yet — dispatch reviewer
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        command=SlashCommand.NEXT_REVIEW_PLAN,
        args=slug,
        project=cwd,
        guidance=guidance,
        subfolder="",
        note=f"Review todos/{slug}/implementation-plan.md and write verdict to state.yaml plan_review.verdict.",
        next_call=f"telec todo prepare {slug}",
    )


async def _prepare_step_gate(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """GATE: DOR formal validation."""
    dor = state.get("dor", {})
    dor_score = dor.get("score") if isinstance(dor, dict) else None

    if isinstance(dor_score, int) and dor_score >= DOR_READY_THRESHOLD:
        # I4: sync before writing phase — sync failure won't leave state pointing at unsynced worktree
        await asyncio.to_thread(sync_main_to_worktree, cwd, slug)
        state["prepare_phase"] = PreparePhase.GROUNDING_CHECK.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        return True, ""  # loop

    # Dispatch gate worker to run DOR assessment
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        command=SlashCommand.NEXT_PREPARE_GATE,
        args=slug,
        project=cwd,
        guidance=guidance,
        subfolder="",
        note=(
            f"Requirements/plan exist for {slug}, but DOR score is below threshold. "
            f"Complete DOR assessment and set state.yaml.dor.score >= {DOR_READY_THRESHOLD}."
        ),
        next_call=f"telec todo prepare {slug}",
    )


def _prepare_step_grounding_check(
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """GROUNDING_CHECK: mechanical freshness check (no agent dispatch)."""
    grounding = state.get("grounding", {})
    grounding_dict = {**DEFAULT_STATE["grounding"], **(grounding if isinstance(grounding, dict) else {})}  # type: ignore[arg-type]

    base_sha = str(grounding_dict.get("base_sha", ""))
    stored_input_digest = str(grounding_dict.get("input_digest", ""))
    referenced_paths = grounding_dict.get("referenced_paths", [])
    if not isinstance(referenced_paths, list):
        referenced_paths = []

    # Get current HEAD
    rc, current_sha, _ = _run_git_prepare(["rev-parse", "HEAD"], cwd=cwd)
    current_sha = current_sha.strip() if rc == 0 else ""

    # Get current input digest
    input_path = Path(cwd) / "todos" / slug / "input.md"
    current_input_digest = ""
    if input_path.exists():
        current_input_digest = hashlib.sha256(input_path.read_bytes()).hexdigest()

    now = datetime.now(UTC).isoformat()

    # First grounding: capture state and transition to PREPARED
    if not base_sha:
        grounding_dict["base_sha"] = current_sha
        grounding_dict["input_digest"] = current_input_digest
        grounding_dict["last_grounded_at"] = now
        grounding_dict["valid"] = True
        state["grounding"] = grounding_dict  # type: ignore[assignment]
        state["prepare_phase"] = PreparePhase.PREPARED.value
        write_phase_state(cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.completed", {"slug": slug})
        return True, ""  # loop to PREPARED terminal

    # I2: git failure is fail-closed — treat missing sha as stale if we have a stored base
    if not current_sha and base_sha:
        logger.warning("GROUNDING_CHECK: git rev-parse HEAD failed for %s, treating as stale", slug)
        reason = "files_changed"
        grounding_dict["valid"] = False
        grounding_dict["invalidated_at"] = now
        grounding_dict["invalidation_reason"] = reason
        grounding_dict["changed_paths"] = []
        state["grounding"] = grounding_dict  # type: ignore[assignment]
        state["prepare_phase"] = PreparePhase.RE_GROUNDING.value
        write_phase_state(cwd, slug, state)
        _emit_prepare_event(
            "domain.software-development.prepare.grounding_invalidated",
            {"slug": slug, "reason": reason, "changed_paths": []},
        )
        return True, ""  # loop to RE_GROUNDING

    # Check for staleness
    sha_changed = bool(current_sha and current_sha != base_sha)
    # Backward compatibility: empty stored digest means "not yet recorded", not "changed".
    # Also treat wrong-length digests (e.g. MD5 written by agents) as unrecorded.
    digest_changed = bool(
        stored_input_digest
        and current_input_digest
        and len(stored_input_digest) == len(current_input_digest)
        and current_input_digest != stored_input_digest
    )

    # Check if referenced paths changed between base_sha and HEAD
    changed_paths: list[str] = []
    if sha_changed and referenced_paths and base_sha and current_sha:
        rc2, diff_output, _ = _run_git_prepare(["diff", "--name-only", f"{base_sha}..{current_sha}"], cwd=cwd)
        if rc2 == 0:
            changed_files = {line.strip() for line in diff_output.splitlines() if line.strip()}
            changed_paths = [p for p in referenced_paths if p in changed_files]

    # Grounding staleness semantics:
    # - Always stale when input digest changed.
    # - If referenced paths are known, only stale when those paths changed.
    # - Fall back to sha-level staleness only when referenced paths are unavailable.
    references_known = bool(referenced_paths)
    paths_stale = bool(changed_paths)
    sha_fallback_stale = sha_changed and not references_known
    is_stale = bool(digest_changed) or paths_stale or sha_fallback_stale

    if is_stale:
        reason = "input_updated" if digest_changed else "files_changed"
        grounding_dict["valid"] = False
        grounding_dict["invalidated_at"] = now
        grounding_dict["invalidation_reason"] = reason
        grounding_dict["changed_paths"] = changed_paths  # I1: persist actual changed paths
        state["grounding"] = grounding_dict  # type: ignore[assignment]
        state["prepare_phase"] = PreparePhase.RE_GROUNDING.value
        write_phase_state(cwd, slug, state)
        _emit_prepare_event(
            "domain.software-development.prepare.grounding_invalidated",
            {"slug": slug, "reason": reason, "changed_paths": changed_paths},
        )
        return True, ""  # loop to RE_GROUNDING

    # Fresh — transition to PREPARED
    grounding_dict["base_sha"] = current_sha
    grounding_dict["input_digest"] = current_input_digest
    grounding_dict["last_grounded_at"] = now
    grounding_dict["valid"] = True
    state["grounding"] = grounding_dict  # type: ignore[assignment]
    state["prepare_phase"] = PreparePhase.PREPARED.value
    write_phase_state(cwd, slug, state)
    _emit_prepare_event("domain.software-development.prepare.completed", {"slug": slug})
    return True, ""  # loop to PREPARED terminal


async def _prepare_step_re_grounding(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """RE_GROUNDING: dispatch plan update against changed files."""
    grounding = state.get("grounding", {})
    grounding_dict = {**DEFAULT_STATE["grounding"], **(grounding if isinstance(grounding, dict) else {})}  # type: ignore[arg-type]
    changed_paths = grounding_dict.get("changed_paths", [])  # I1: actual changed paths, not all referenced
    if not isinstance(changed_paths, list):
        changed_paths = []
    else:
        changed_paths = [path for path in changed_paths if isinstance(path, str)]

    # Set next phase to PLAN_REVIEW so re-grounded plan gets reviewed
    state["prepare_phase"] = PreparePhase.PLAN_REVIEW.value
    # Reset plan review verdict so fresh review runs
    plan_review = state.get("plan_review", {})
    if isinstance(plan_review, dict):
        plan_review["verdict"] = ""
    state["plan_review"] = plan_review  # type: ignore[assignment]
    await asyncio.to_thread(write_phase_state, cwd, slug, state)

    changed_note = f"Changed files: {', '.join(changed_paths)}" if changed_paths else "Codebase has evolved."
    guidance = await compose_agent_guidance(db)
    result = format_tool_call(
        command=SlashCommand.NEXT_PREPARE_DRAFT,
        args=slug,
        project=cwd,
        guidance=guidance,
        subfolder="",
        note=f"Update todos/{slug}/implementation-plan.md against current codebase. {changed_note}",
        next_call=f"telec todo prepare {slug}",
    )
    _emit_prepare_event("domain.software-development.prepare.regrounded", {"slug": slug})
    return False, result


def _prepare_step_prepared(slug: str) -> tuple[bool, str]:
    """PREPARED: terminal success state."""
    return False, format_prepared(slug)


def _prepare_step_blocked(slug: str, state: dict[str, StateValue]) -> tuple[bool, str]:
    """BLOCKED: terminal failure state."""
    grounding = state.get("grounding", {})
    blocker = str(grounding.get("invalidation_reason", "unknown")) if isinstance(grounding, dict) else "unknown"
    _emit_prepare_event(
        "domain.software-development.prepare.blocked",
        {"slug": slug, "blocker": blocker},
    )
    return False, (
        f"BLOCKED: {slug} requires human decision. "
        f"Reason: {blocker}. "
        f"Inspect todos/{slug}/state.yaml and resolve the blocker manually."
    )


# =============================================================================
# Prepare State Machine — step dispatcher
# =============================================================================


async def _prepare_dispatch(
    *,
    db: Db,
    slug: str,
    cwd: str,
    phase: PreparePhase,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """Dispatch to the appropriate phase handler. Returns (continue_loop, instruction)."""
    if phase == PreparePhase.INPUT_ASSESSMENT:
        return await _prepare_step_input_assessment(db, slug, cwd, state)
    if phase == PreparePhase.TRIANGULATION:
        return await _prepare_step_triangulation(db, slug, cwd, state)
    if phase == PreparePhase.REQUIREMENTS_REVIEW:
        return await _prepare_step_requirements_review(db, slug, cwd, state)
    if phase == PreparePhase.PLAN_DRAFTING:
        return await _prepare_step_plan_drafting(db, slug, cwd, state)
    if phase == PreparePhase.PLAN_REVIEW:
        return await _prepare_step_plan_review(db, slug, cwd, state)
    if phase == PreparePhase.GATE:
        return await _prepare_step_gate(db, slug, cwd, state)
    if phase == PreparePhase.GROUNDING_CHECK:
        return await asyncio.to_thread(_prepare_step_grounding_check, slug, cwd, state)
    if phase == PreparePhase.RE_GROUNDING:
        return await _prepare_step_re_grounding(db, slug, cwd, state)
    if phase == PreparePhase.PREPARED:
        return _prepare_step_prepared(slug)
    if phase == PreparePhase.BLOCKED:
        return _prepare_step_blocked(slug, state)
    return False, f"UNHANDLED_PHASE: No handler for prepare phase: {phase.value}"


def _run_git_prepare(args: list[str], cwd: str) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


# =============================================================================
# Prepare State Machine — CLI invalidation check
# =============================================================================


def invalidate_stale_preparations(cwd: str, changed_paths: list[str]) -> dict[str, list[str]]:
    """Scan all active todos and invalidate those with overlapping referenced paths.

    Designed for post-commit hooks or CI to invalidate stale preparations.
    Returns {"invalidated": ["slug-a", ...]} for each invalidated slug.
    """
    invalidated: list[str] = []
    now = datetime.now(UTC).isoformat()
    changed_set = set(changed_paths)

    for slug in load_roadmap_slugs(cwd):
        state = read_phase_state(cwd, slug)
        grounding = state.get("grounding", {})
        if not isinstance(grounding, dict):
            continue
        referenced = grounding.get("referenced_paths", [])
        if not isinstance(referenced, list):
            continue
        overlap = [p for p in referenced if p in changed_set]
        if overlap:
            grounding_dict: dict[str, bool | str | list[str] | int] = {
                **DEFAULT_STATE["grounding"],  # type: ignore[arg-type]
                **grounding,
            }
            grounding_dict["valid"] = False
            grounding_dict["invalidated_at"] = now
            grounding_dict["invalidation_reason"] = "files_changed"
            state["grounding"] = grounding_dict  # type: ignore[assignment]
            state["prepare_phase"] = PreparePhase.GROUNDING_CHECK.value
            write_phase_state(cwd, slug, state)
            _emit_prepare_event(
                "domain.software-development.prepare.grounding_invalidated",
                {"slug": slug, "reason": "files_changed", "changed_paths": overlap},
            )
            invalidated.append(slug)

    return {"invalidated": invalidated}


# =============================================================================
# Main Functions
# =============================================================================


async def next_prepare(db: Db, slug: str | None, cwd: str) -> str:
    """Phase A state machine for collaborative architect work.

    Reads durable state from state.yaml, determines the current prepare phase,
    executes the next step, and returns structured tool-call instructions for
    the orchestrator.

    Args:
        db: Database instance
        slug: Optional explicit slug (resolved from roadmap if not provided)
        cwd: Current working directory (project root)

    Returns:
        Plain text instructions for the orchestrator to execute
    """
    try:
        # Pre-dispatch preconditions: slug resolution, roadmap validation, container detection
        resolved_slug = slug
        if not resolved_slug:
            resolved_slug = await asyncio.to_thread(_find_next_prepare_slug, cwd)

        if not resolved_slug:
            guidance = await compose_agent_guidance(db)
            return format_tool_call(
                command=SlashCommand.NEXT_PREPARE_DRAFT,
                args="",
                project=cwd,
                guidance=guidance,
                subfolder="",
                note="No active preparation work found.",
                next_call="telec todo prepare",
            )

        holder_children = await asyncio.to_thread(resolve_holder_children, cwd, resolved_slug)
        if holder_children:
            return f"CONTAINER: {resolved_slug} was split into: {', '.join(holder_children)}. Work on those first."

        if not await asyncio.to_thread(slug_in_roadmap, cwd, resolved_slug):
            await asyncio.to_thread(add_to_roadmap, cwd, resolved_slug)
            logger.info("AUTO_ROADMAP_ADD slug=%s machine=prepare", resolved_slug)

        # Dispatch loop
        for _iter in range(_PREPARE_LOOP_LIMIT):
            state = await asyncio.to_thread(read_phase_state, cwd, resolved_slug)
            # Resolve current phase
            raw_phase = str(state.get("prepare_phase", "")).strip()
            try:
                phase = PreparePhase(raw_phase)
            except ValueError:
                # Derive phase from artifact existence for legacy todos
                phase = await asyncio.to_thread(_derive_prepare_phase, resolved_slug, cwd, state)

            logger.info(
                "NEXT_PREPARE_PHASE slug=%s phase=%s iter=%d",
                resolved_slug,
                phase.value,
                _iter,
            )

            keep_going, instruction = await _prepare_dispatch(
                db=db, slug=resolved_slug, cwd=cwd, phase=phase, state=state
            )
            if not keep_going:
                return instruction

        return (
            f"LOOP_LIMIT: prepare state machine for {resolved_slug} exceeded "
            f"{_PREPARE_LOOP_LIMIT} internal transitions. "
            f"Inspect todos/{resolved_slug}/state.yaml prepare_phase for stuck state."
        )
    except RuntimeError:
        raise


async def next_work(db: Db, slug: str | None, cwd: str) -> str:
    """Phase B state machine for deterministic builder work.

    Executes the build/review/fix/finalize cycle on prepared work items.
    Only considers items with phase "ready" and satisfied dependencies.

    Args:
        db: Database instance
        slug: Optional explicit slug (resolved from roadmap if not provided)
        cwd: Current working directory (project root)

    Returns:
        Plain text instructions for the orchestrator to execute
    """
    canonical_cwd = await asyncio.to_thread(resolve_canonical_project_root, cwd)
    if canonical_cwd != cwd:
        logger.debug(
            "next_work normalized cwd to canonical project root", requested_cwd=cwd, canonical_cwd=canonical_cwd
        )
        cwd = canonical_cwd

    # Sweep completed group parents before resolving next slug
    await asyncio.to_thread(sweep_completed_groups, cwd)

    phase_slug = slug or "<auto>"
    slug_resolution_started = perf_counter()

    # 1. Resolve slug - only ready items when no explicit slug
    # Prefer worktree-local planning state when explicit slug worktree exists.
    deps_cwd = cwd
    if slug:
        maybe_worktree = Path(cwd) / WORKTREE_DIR / slug
        if (maybe_worktree / "todos" / "roadmap.yaml").exists():
            deps_cwd = str(maybe_worktree)
    deps = await asyncio.to_thread(load_roadmap_deps, deps_cwd)

    resolved_slug: str
    if slug:
        # Explicit slug provided - verify it's in roadmap, ready, and dependencies satisfied
        # Bugs bypass the roadmap check (they're not in the roadmap)
        is_bug = await asyncio.to_thread(is_bug_todo, cwd, slug)
        if not is_bug and not await asyncio.to_thread(slug_in_roadmap, cwd, slug):
            # Auto-add to roadmap — user intent is clear
            await asyncio.to_thread(add_to_roadmap, cwd, slug)
            logger.info("AUTO_ROADMAP_ADD slug=%s machine=work", slug)
            # Reload deps after roadmap change
            deps = await asyncio.to_thread(load_roadmap_deps, deps_cwd)

        # Holder resolution: if slug is a container with children, route to first runnable child
        if not is_bug:
            holder_child, holder_reason = await asyncio.to_thread(resolve_first_runnable_holder_child, cwd, slug, deps)
            if holder_child:
                slug = holder_child
            elif holder_reason == "complete":
                _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "skip", "holder_complete")
                return f"COMPLETE: Holder '{slug}' has no remaining child work."
            elif holder_reason == "deps_unsatisfied":
                _log_next_work_phase(
                    phase_slug, "slug_resolution", slug_resolution_started, "error", "holder_deps_unsatisfied"
                )
                return format_error(
                    "DEPS_UNSATISFIED",
                    f"Holder '{slug}' has children, but none are currently runnable due to unsatisfied dependencies.",
                    next_call="Complete dependency items first.",
                )
            elif holder_reason == "item_not_ready":
                _log_next_work_phase(
                    phase_slug, "slug_resolution", slug_resolution_started, "error", "holder_not_ready"
                )
                return format_error(
                    "ITEM_NOT_READY",
                    f"Holder '{slug}' has children, but none are ready to start work.",
                    next_call=f"Call telec todo prepare on the child items for '{slug}' first.",
                )
            elif holder_reason == "children_not_in_roadmap":
                _log_next_work_phase(
                    phase_slug, "slug_resolution", slug_resolution_started, "error", "holder_children_missing"
                )
                return format_error(
                    "NOT_PREPARED",
                    f"Holder '{slug}' has child todos, but none are in roadmap.",
                    next_call="Add child items to roadmap or call telec todo prepare.",
                )

        phase = await asyncio.to_thread(get_item_phase, cwd, slug)
        if (
            not is_bug
            and phase == ItemPhase.PENDING.value
            and not await asyncio.to_thread(is_ready_for_work, cwd, slug)
        ):
            _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "error", "item_not_ready")
            return format_error(
                "ITEM_NOT_READY",
                f"Item '{slug}' is pending and DOR score is below threshold. Must be ready to start work.",
                next_call=f"Call telec todo prepare {slug} to prepare it first.",
            )
        if phase == ItemPhase.DONE.value:
            _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "skip", "item_done")
            return f"COMPLETE: Item '{slug}' is already done."

        # Item is ready or in_progress - check dependencies
        if not await asyncio.to_thread(check_dependencies_satisfied, cwd, slug, deps):
            _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "error", "deps_unsatisfied")
            return format_error(
                "DEPS_UNSATISFIED",
                f"Item '{slug}' has unsatisfied dependencies.",
                next_call="Complete dependency items first, or check todos/roadmap.yaml.",
            )
        resolved_slug = slug
    else:
        # R6: Use resolve_slug with dependency gating
        found_slug, _, _ = await resolve_slug_async(cwd, None, True, deps)

        if not found_slug:
            # Check if there are ready items (without dependency gating) to provide better error
            has_ready_items, _, _ = await resolve_slug_async(cwd, None, True)

            if has_ready_items:
                _log_next_work_phase(
                    phase_slug, "slug_resolution", slug_resolution_started, "error", "ready_but_deps_unsatisfied"
                )
                return format_error(
                    "DEPS_UNSATISFIED",
                    "Ready items exist but all have unsatisfied dependencies.",
                    next_call="Complete dependency items first, or check todos/roadmap.yaml.",
                )
            _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "skip", "no_ready_items")
            return format_error(
                "NO_READY_ITEMS",
                "No ready items found in roadmap.",
                next_call="Call telec todo prepare to prepare items first.",
            )
        resolved_slug = found_slug

    phase_slug = resolved_slug
    _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "run", "resolved")

    preconditions_started = perf_counter()

    # 2. Guardrail: stash debt is forbidden for AI orchestration
    stash_entries = await asyncio.to_thread(get_stash_entries, cwd)
    if stash_entries:
        _log_next_work_phase(phase_slug, "preconditions", preconditions_started, "error", "stash_debt")
        return format_stash_debt(resolved_slug, len(stash_entries))

    # 3. Validate preconditions
    # Bugs use bug.md; regular todos use requirements.md + implementation-plan.md
    precondition_root = cwd
    worktree_path = Path(cwd) / WORKTREE_DIR / resolved_slug
    is_bug = await asyncio.to_thread(is_bug_todo, cwd, resolved_slug)
    if worktree_path.exists():
        if is_bug:
            if check_file_has_content(str(worktree_path), f"todos/{resolved_slug}/bug.md"):
                precondition_root = str(worktree_path)
        elif (
            check_file_has_content(str(worktree_path), f"todos/{resolved_slug}/requirements.md")
            and check_file_has_content(str(worktree_path), f"todos/{resolved_slug}/implementation-plan.md")
        ):
            precondition_root = str(worktree_path)

    if not is_bug:
        has_requirements = check_file_has_content(precondition_root, f"todos/{resolved_slug}/requirements.md")
        has_impl_plan = check_file_has_content(precondition_root, f"todos/{resolved_slug}/implementation-plan.md")
        if not (has_requirements and has_impl_plan):
            _log_next_work_phase(phase_slug, "preconditions", preconditions_started, "error", "not_prepared")
            return format_error(
                "NOT_PREPARED",
                f"todos/{resolved_slug} is missing requirements or implementation plan.",
                next_call=f"Call telec todo prepare {resolved_slug} to complete preparation.",
            )
    else:
        has_bug_md = check_file_has_content(precondition_root, f"todos/{resolved_slug}/bug.md")
        if not has_bug_md:
            _log_next_work_phase(phase_slug, "preconditions", preconditions_started, "error", "invalid_bug")
            return format_error(
                "INVALID_BUG",
                f"todos/{resolved_slug} has kind='bug' but bug.md is missing or empty.",
                next_call=f"Recreate with: telec bugs create {resolved_slug}",
            )
    _log_next_work_phase(phase_slug, "preconditions", preconditions_started, "run", "validated")

    # 3b. Pre-build freshness gate: verify preparation is still valid
    if not is_bug:
        prep_state = await asyncio.to_thread(read_phase_state, cwd, resolved_slug)
        prepare_phase_val = str(prep_state.get("prepare_phase", "")).strip()
        grounding = prep_state.get("grounding", {})
        grounding_valid = isinstance(grounding, dict) and grounding.get("valid") is True
        # Only block if prepare_phase is explicitly set and not "prepared",
        # or grounding is explicitly invalidated. Legacy todos (no prepare_phase) pass through.
        if prepare_phase_val and prepare_phase_val != PreparePhase.PREPARED.value:
            _log_next_work_phase(phase_slug, "preconditions", preconditions_started, "error", "stale_preparation")
            return format_error(
                "STALE",
                f"{resolved_slug} preparation is not complete (phase: {prepare_phase_val}).",
                next_call=f"Run telec todo prepare {resolved_slug} to re-ground.",
            )
        if prepare_phase_val == PreparePhase.PREPARED.value and not grounding_valid:
            _log_next_work_phase(phase_slug, "preconditions", preconditions_started, "error", "stale_grounding")
            return format_error(
                "STALE",
                f"{resolved_slug} preparation is invalidated (grounding.valid=false).",
                next_call=f"Run telec todo prepare {resolved_slug} to re-ground.",
            )

    worktree_cwd = str(Path(cwd) / WORKTREE_DIR / resolved_slug)
    ensure_started = perf_counter()
    slug_lock = await _get_slug_single_flight_lock(cwd, resolved_slug)
    if slug_lock.locked():
        logger.info(
            "%s slug=%s phase=ensure_prepare decision=wait reason=single_flight_in_progress duration_ms=0",
            NEXT_WORK_PHASE_LOG,
            phase_slug,
        )

    # 4. Ensure worktree exists + conditional prep + conditional sync in single-flight window.
    try:
        async with slug_lock:
            logger.info(
                "next_work entering ensure/sync boundary slug=%s cwd=%s worktree_path=%s",
                resolved_slug,
                cwd,
                worktree_cwd,
            )
            ensure_result = await ensure_worktree_with_policy_async(cwd, resolved_slug)
            if ensure_result.created:
                logger.info("Created new worktree for %s", resolved_slug)
            ensure_decision = "run" if ensure_result.prepared else "skip"
            _log_next_work_phase(
                phase_slug, "ensure_prepare", ensure_started, ensure_decision, ensure_result.prep_reason
            )

            sync_started = perf_counter()
            logger.info(
                "next_work entering sync boundary slug=%s cwd=%s worktree_path=%s",
                resolved_slug,
                cwd,
                worktree_cwd,
            )
            main_sync_copied = await asyncio.to_thread(sync_main_to_worktree, cwd, resolved_slug)
            sync_decision = "run" if main_sync_copied > 0 else "skip"
            sync_reason = f"copied main={main_sync_copied}" if main_sync_copied > 0 else "unchanged_inputs"
            _log_next_work_phase(phase_slug, "sync", sync_started, sync_decision, sync_reason)
    except RuntimeError as exc:
        logger.error(
            "next_work worktree preparation failed for slug=%s cwd=%s worktree_path=%s: %s",
            resolved_slug,
            cwd,
            worktree_cwd,
            exc,
            exc_info=True,
        )
        _log_next_work_phase(phase_slug, "ensure_prepare", ensure_started, "error", "prep_failed")
        return format_error(
            "WORKTREE_PREP_FAILED",
            str(exc),
            next_call="Add tools/worktree-prepare.sh or fix its execution, then retry.",
        )
    except Exception as exc:
        logger.error(
            "next_work worktree setup failed for slug=%s cwd=%s worktree_path=%s: %s",
            resolved_slug,
            cwd,
            worktree_cwd,
            exc,
            exc_info=True,
        )
        _log_next_work_phase(phase_slug, "ensure_prepare", ensure_started, "error", f"unexpected_{type(exc).__name__}")
        return format_error(
            "WORKTREE_SETUP_FAILED",
            f"Unexpected error while ensuring worktree for {resolved_slug}: {type(exc).__name__}: {exc}",
            next_call="Inspect daemon logs for worktree setup failure, fix the repository or branch state, then retry.",
        )

    dispatch_started = perf_counter()

    # 5. Check uncommitted changes
    if has_uncommitted_changes(cwd, resolved_slug):
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "uncommitted_changes")
        return format_uncommitted_changes(resolved_slug)

    # 6. Claim the item (pending → in_progress) — safe to do here since it's
    # just a "someone is looking at this" marker. Even if the orchestrator doesn't
    # dispatch, the next next_work() call picks it up again.
    current_phase = await asyncio.to_thread(get_item_phase, worktree_cwd, resolved_slug)
    if current_phase == ItemPhase.PENDING.value:
        await asyncio.to_thread(set_item_phase, worktree_cwd, resolved_slug, ItemPhase.IN_PROGRESS.value)

    # 7. Route from worktree-owned build/review state.
    # Review is authoritative: once approved, never regress back to build because
    # of clerical build-state drift.
    state = await asyncio.to_thread(read_phase_state, worktree_cwd, resolved_slug)
    build_value = state.get(PhaseName.BUILD.value)
    build_status = build_value if isinstance(build_value, str) else PhaseStatus.PENDING.value
    review_value = state.get(PhaseName.REVIEW.value)
    review_status = review_value if isinstance(review_value, str) else PhaseStatus.PENDING.value

    # Repair contradictory state: review approved implies build complete.
    if review_status == PhaseStatus.APPROVED.value and build_status != PhaseStatus.COMPLETE.value:
        repair_started = perf_counter()
        await asyncio.to_thread(
            mark_phase, worktree_cwd, resolved_slug, PhaseName.BUILD.value, PhaseStatus.COMPLETE.value
        )
        build_status = PhaseStatus.COMPLETE.value
        _log_next_work_phase(
            phase_slug,
            "state_repair",
            repair_started,
            "run",
            "approved_review_implies_build_complete",
        )

    # Guard stale review approvals: if new commits landed after approval baseline,
    # route back through review instead of proceeding to finalize.
    if review_status == PhaseStatus.APPROVED.value:
        baseline_raw = state.get("review_baseline_commit")
        baseline = baseline_raw if isinstance(baseline_raw, str) else ""
        head_sha = await asyncio.to_thread(_get_head_commit, worktree_cwd)
        if (
            baseline
            and head_sha
            and baseline != head_sha
            and await asyncio.to_thread(_has_meaningful_diff, worktree_cwd, baseline, head_sha)
        ):
            repair_started = perf_counter()
            await asyncio.to_thread(
                mark_phase, worktree_cwd, resolved_slug, PhaseName.REVIEW.value, PhaseStatus.PENDING.value
            )
            review_status = PhaseStatus.PENDING.value
            _log_next_work_phase(
                phase_slug,
                "state_repair",
                repair_started,
                "run",
                "review_approval_stale_baseline",
            )

    finalize_state = _get_finalize_state(state)

    # Finalize handoff is a slug-scoped follow-up step after FINALIZE_READY.
    # Once ready is recorded, the next `telec todo work {slug}` must consume
    # that durable state and emit integration events exactly once before the
    # queue is allowed to advance.
    if review_status == PhaseStatus.APPROVED.value and finalize_state.get("status") == "handed_off":
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "skip", "finalize_already_handed_off")
        return format_error(
            "FINALIZE_ALREADY_HANDED_OFF",
            f"{resolved_slug} has already been handed off to integration. Continue the queue without a slug.",
            next_call="telec todo work",
        )

    if review_status == PhaseStatus.APPROVED.value and finalize_state.get("status") == "ready":
        branch = finalize_state.get("branch", "").strip()
        sha = finalize_state.get("sha", "").strip()
        worker_session_id = finalize_state.get("worker_session_id", "").strip()
        if not branch or not sha:
            _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "finalize_state_invalid")
            return format_error(
                "FINALIZE_STATE_INVALID",
                f"{resolved_slug} finalize state is missing branch or sha; re-run finalize prepare.",
                next_call=f"telec todo work {resolved_slug}",
            )

        session_id = os.environ.get("TELECLAUDE_SESSION_ID", "unknown")
        handoff_started = perf_counter()
        try:
            await emit_branch_pushed(
                branch=branch,
                sha=sha,
                remote="origin",
                pusher=f"finalizer/{worker_session_id}" if worker_session_id else "",
            )
            await emit_deployment_started(
                slug=resolved_slug,
                branch=branch,
                sha=sha,
                worker_session_id=worker_session_id,
                orchestrator_session_id=session_id,
                ready_at=finalize_state.get("ready_at"),
            )
            await asyncio.to_thread(
                _mark_finalize_handed_off,
                worktree_cwd,
                resolved_slug,
                handoff_session_id=session_id,
            )
        except Exception as exc:
            _log_next_work_phase(phase_slug, "dispatch_decision", handoff_started, "error", "finalize_handoff_failed")
            return format_error(
                "FINALIZE_HANDOFF_FAILED",
                f"Failed to emit finalize handoff for {resolved_slug}: {type(exc).__name__}: {exc}",
                next_call=f"telec todo work {resolved_slug}",
            )
        _log_next_work_phase(phase_slug, "dispatch_decision", handoff_started, "run", "finalize_handoff_emitted")

        # Collect active child sessions spawned by this orchestrator for cleanup
        child_session_ids: list[str] = []
        if session_id != "unknown":
            try:
                child_sessions = await db.list_sessions(initiator_session_id=session_id)
                child_session_ids = [s.session_id for s in child_sessions]
            except Exception:
                logger.warning("Failed to query child sessions for cleanup", session_id=session_id)

        return format_finalize_handoff_complete(resolved_slug, "telec todo work", child_session_ids)

    # If review requested changes, continue fix loop regardless of build-state drift.
    if review_status == PhaseStatus.CHANGES_REQUESTED.value:
        try:
            guidance = await compose_agent_guidance(db)
        except RuntimeError as exc:
            _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
            return format_error("NO_AGENTS", str(exc))
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_fix_review")
        return format_tool_call(
            command=SlashCommand.NEXT_FIX_REVIEW,
            args=resolved_slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
            next_call=f"telec todo work {resolved_slug}",
            note=(
                "PEER CONVERSATION NOTE: If you still have the reviewer session alive from the "
                "previous review dispatch, prefer the direct conversation pattern from "
                "POST_COMPLETION[next-review-build] instead of a fresh fix-review dispatch: "
                "send fixer and reviewer session IDs to each other with --direct to let them "
                "iterate without context-destroying churn. This fallback path is for when the "
                "reviewer session has already ended."
            ),
        )

    # Pending review still requires build completion + gates before dispatching review.
    if review_status != PhaseStatus.APPROVED.value:
        # mark_phase(build, started) is deferred to the orchestrator via pre_dispatch
        # to avoid orphaned "build: started" when the orchestrator decides not to dispatch.
        if build_status != PhaseStatus.COMPLETE.value:
            # Merge origin/main into the worktree before build dispatch so the
            # builder starts on a current branch and inherits any test fixes from main.
            merge_main_result = await asyncio.to_thread(_merge_origin_main_into_worktree, worktree_cwd, resolved_slug)
            if merge_main_result:
                _log_next_work_phase(phase_slug, "merge_main", dispatch_started, "error", "merge_main_failed")
                return format_error("MERGE_MAIN_FAILED", merge_main_result)

            try:
                guidance = await compose_agent_guidance(db)
            except RuntimeError as exc:
                _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
                return format_error("NO_AGENTS", str(exc))

            # Build pre-dispatch marking instructions
            pre_dispatch = f"telec todo mark-phase {resolved_slug} --phase build --status started"

            # Bugs use next-bugs-fix instead of next-build
            # Check main repo's todos/ (bug.md lives there, not synced to worktree)
            is_bug = await asyncio.to_thread(is_bug_todo, cwd, resolved_slug)
            if is_bug:
                _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_bugs_fix")
                return format_tool_call(
                    command=SlashCommand.NEXT_BUGS_FIX,
                    args=resolved_slug,
                    project=cwd,
                    guidance=guidance,
                    subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
                    next_call=f"telec todo work {resolved_slug}",
                    pre_dispatch=pre_dispatch,
                )
            _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_build")
            return format_tool_call(
                command=SlashCommand.NEXT_BUILD,
                args=resolved_slug,
                project=cwd,
                guidance=guidance,
                subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
                next_call=f"telec todo work {resolved_slug}",
                pre_dispatch=pre_dispatch,
            )

        # Build gates: verify tests and demo structure before allowing review.
        review_round_raw = state.get("review_round")
        review_round = review_round_raw if isinstance(review_round_raw, int) else 0
        gate_started = perf_counter()
        gates_passed, gate_output = await asyncio.to_thread(run_build_gates, worktree_cwd, resolved_slug)
        if not gates_passed:
            gate_log_detail = "build_gates_failed_post_review" if review_round > 0 else "build_gates_failed"
            _log_next_work_phase(phase_slug, "gate_execution", gate_started, "error", gate_log_detail)
            if review_round == 0:
                # First build: reset to started so the builder retries from scratch
                await asyncio.to_thread(
                    mark_phase, worktree_cwd, resolved_slug, PhaseName.BUILD.value, PhaseStatus.STARTED.value
                )
            # review_round > 0: keep build=complete; builder gets a focused fix instruction
            next_call = f"telec todo work {resolved_slug}"
            return format_build_gate_failure(resolved_slug, gate_output, next_call)
        _log_next_work_phase(phase_slug, "gate_execution", gate_started, "run", "build_gates_passed")

        # Artifact verification: check implementation plan checkboxes, commits, quality checklist.
        verify_started = perf_counter()
        is_bug = await asyncio.to_thread(is_bug_todo, cwd, resolved_slug)
        artifacts_passed, artifacts_output = await asyncio.to_thread(
            verify_artifacts, worktree_cwd, resolved_slug, PhaseName.BUILD.value, is_bug=is_bug
        )
        if not artifacts_passed:
            artifact_log_detail = (
                "artifact_verification_failed_post_review" if review_round > 0 else "artifact_verification_failed"
            )
            _log_next_work_phase(phase_slug, "gate_execution", verify_started, "error", artifact_log_detail)
            if review_round == 0:
                await asyncio.to_thread(
                    mark_phase, worktree_cwd, resolved_slug, PhaseName.BUILD.value, PhaseStatus.STARTED.value
                )
            # review_round > 0: keep build=complete; builder gets a focused fix instruction
            next_call = f"telec todo work {resolved_slug}"
            return format_build_gate_failure(resolved_slug, artifacts_output, next_call)
        _log_next_work_phase(phase_slug, "gate_execution", verify_started, "run", "artifact_verification_passed")

        # Review not started or still pending.
        limit_reached, current_round, max_rounds = _is_review_round_limit_reached(worktree_cwd, resolved_slug)
        if limit_reached:
            _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "review_round_limit")
            return format_error(
                "REVIEW_ROUND_LIMIT",
                (
                    f"Review rounds exceeded for {resolved_slug}: "
                    f"current={current_round}, max={max_rounds}. "
                    f"Manual resolution required.\n\n"
                    f"Before acting, load the relevant worker role:\n"
                    f"  telec docs index\n"
                    f"Then use telec docs get to load the procedure for the role you are assuming."
                ),
                next_call=f"telec todo work {resolved_slug}",
            )
        try:
            guidance = await compose_agent_guidance(db)
        except RuntimeError as exc:
            _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
            return format_error("NO_AGENTS", str(exc))
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_review")
        return format_tool_call(
            command=SlashCommand.NEXT_REVIEW_BUILD,
            args=resolved_slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
            next_call=f"telec todo work {resolved_slug}",
            note=f"{REVIEW_DIFF_NOTE}\n\n{_review_scope_note(worktree_cwd, resolved_slug)}",
        )

    # 8.5 Check pending deferrals (R7)
    if await asyncio.to_thread(has_pending_deferrals, worktree_cwd, resolved_slug):
        try:
            guidance = await compose_agent_guidance(db)
        except RuntimeError as exc:
            _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
            return format_error("NO_AGENTS", str(exc))
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_defer")
        return format_tool_call(
            command="next-defer",  # not a SlashCommand; deferred to runtime resolution
            args=resolved_slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
            next_call=f"telec todo work {resolved_slug}",
        )

    # 9. Review approved - dispatch finalize prepare
    if has_uncommitted_changes(cwd, resolved_slug):
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "uncommitted_changes")
        return format_uncommitted_changes(resolved_slug)
    try:
        guidance = await compose_agent_guidance(db)
    except RuntimeError as exc:
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
        return format_error("NO_AGENTS", str(exc))

    # Emit review.approved event once finalize dispatch begins. The later
    # slug-specific handoff step emits branch/deployment events after the
    # finalizer has actually reported FINALIZE_READY.
    review_round_val = state.get("review_round")
    review_round = review_round_val if isinstance(review_round_val, int) else 1
    session_id = os.environ.get("TELECLAUDE_SESSION_ID", "unknown")
    try:
        await emit_review_approved(
            slug=resolved_slug,
            reviewer_session_id=session_id,
            review_round=review_round,
        )
    except Exception:
        logger.warning("Failed to emit review.approved event for %s", resolved_slug, exc_info=True)

    # Bugs skip delivered.yaml bookkeeping and are removed from todos entirely
    # Check main repo's todos/ (bug.md lives there, not synced to worktree)
    is_bug = await asyncio.to_thread(is_bug_todo, cwd, resolved_slug)
    note = "BUG FIX: Skip delivered.yaml bookkeeping. Delete todo directory after merge." if is_bug else ""
    _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_finalize")
    return format_tool_call(
        command=SlashCommand.NEXT_FINALIZE,
        args=resolved_slug,
        project=cwd,
        guidance=guidance,
        subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
        next_call=f"telec todo work {resolved_slug}",
        note=note,
    )
