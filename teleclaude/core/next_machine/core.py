"""Next Machine - Deterministic workflow state machine for orchestrating work.

This module provides two main functions:
- next_prepare(): Phase A state machine for collaborative architect work
- next_work(): Phase B state machine for deterministic builder work

Both derive state from files (stateless) and return plain text instructions
for the orchestrator AI to execute literally.
"""

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import TypedDict, cast

import yaml
from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError, NoSuchPathError
from instrukt_ai_logging import get_logger

from teleclaude.config import config as app_config
from teleclaude.core.agents import AgentName
from teleclaude.core.db import Db

logger = get_logger(__name__)

StateValue = str | bool | int | list[str] | dict[str, bool | list[str]]


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
2. telec todo mark-phase {args} --phase build --status complete --cwd <project-root>
3. Call {next_call} — this runs build gates (tests + demo validation)
4. If next_work says gates PASSED: telec sessions end <session_id> and continue
5. If next_work says BUILD GATES FAILED:
   a. Send the builder the failure message (do NOT end the session)
   b. Wait for the builder to report completion again
   c. Repeat from step 2
6. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-bugs-fix": """WHEN WORKER COMPLETES:
1. Read worker output via get_session_data
2. telec todo mark-phase {args} --phase build --status complete --cwd <project-root>
3. Call {next_call} — this runs build gates (tests + demo validation)
4. If next_work says gates PASSED: telec sessions end <session_id> and continue
5. If next_work says BUILD GATES FAILED:
   a. Send the builder the failure message (do NOT end the session)
   b. Wait for the builder to report completion again
   c. Repeat from step 2
6. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-review": """WHEN WORKER COMPLETES:
1. Read worker output via get_session_data to extract verdict
2. telec sessions end <session_id>
3. Relay verdict to state:
   - If APPROVE: telec todo mark-phase {args} --phase review --status approved --cwd <project-root>
   - If REQUEST CHANGES: telec todo mark-phase {args} --phase review --status changes_requested --cwd <project-root>
4. Call {next_call}
5. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-fix-review": """WHEN WORKER COMPLETES:
1. Read worker output via get_session_data
2. telec sessions end <session_id>
3. telec todo mark-phase {args} --phase review --status pending --cwd <project-root>
4. Call {next_call}
5. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-defer": """WHEN WORKER COMPLETES:
1. Read worker output. Confirm deferrals_processed in state.yaml
2. telec sessions end <session_id>
3. Call {next_call}
4. Never send no-op acknowledgements/keepalives (e.g., "No new input", "Remain idle", "Continue standing by").
""",
    "next-finalize": """WHEN WORKER COMPLETES:
1. Read worker output via get_session_data.
2. Accept completion only for the dispatched worker session `<session_id>`.
   Ignore notifications from any other session.
3. Verify finalize lock ownership before consuming FINALIZE_READY:
   - Lock file `todos/.finalize-lock` must exist.
   - Lock `slug` must equal `{args}`.
   - Lock `session_id` must equal your orchestrator `TELECLAUDE_SESSION_ID`.
   If any check fails: stop and report FINALIZE_LOCK_MISMATCH (do NOT apply).
4. Confirm worker reported exactly `FINALIZE_READY: {args}` in session `<session_id>` transcript.
   If missing: send worker feedback to report FINALIZE_READY and stop (do NOT apply).
5. telec sessions end <session_id>
6. FINALIZE APPLY SAFETY RE-CHECK (canonical main):
   a. MAIN_REPO="$(git rev-parse --git-common-dir)/.."
   b. Ensure canonical main has no uncommitted changes except `todos/.finalize-lock`.
      If dirty: stop and report `ERROR: FINALIZE_PRECONDITION_DIRTY_CANONICAL_MAIN`.
      Operator action: clean canonical main, then rerun `telec todo work {args}`.
   c. Ensure canonical main is not ahead of `{args}` (`git rev-list --count {args}..main` must be 0).
      If ahead: stop and report `ERROR: FINALIZE_PRECONDITION_MAIN_AHEAD`.
      Operator action: merge/rebase latest main into `{args}`, then rerun `telec todo work {args}`.
   d. If git state cannot be inspected: stop and report `ERROR: FINALIZE_PRECONDITION_GIT_STATE_UNKNOWN`.
      Operator action: restore git access/health, then rerun `telec todo work {args}`.
7. FINALIZE APPLY (orchestrator-owned, canonical root only — NEVER cd into worktree):
   a. git -C "$MAIN_REPO" fetch origin main
   b. git -C "$MAIN_REPO" switch main
   c. git -C "$MAIN_REPO" pull --ff-only origin main
   d. git -C "$MAIN_REPO" merge {args} --no-edit
   e. MERGE_COMMIT="$(git -C "$MAIN_REPO" rev-parse HEAD)"
   f. If "$MAIN_REPO/todos/{args}/bug.md" exists: skip delivery bookkeeping.
      Else: telec roadmap deliver {args} --commit "$MERGE_COMMIT" --project-root "$MAIN_REPO"
            && git -C "$MAIN_REPO" add todos/delivered.yaml todos/roadmap.yaml
            && git -C "$MAIN_REPO" commit -m "chore({args}): record delivery"
8. DEMO SNAPSHOT (orchestrator-owned — stamp delivery metadata while artifacts exist):
   If demos/{args}/demo.md exists (builder created it during build):
   a. Read todos/{args}/requirements.md title and implementation-plan.md metrics
   b. Generate demos/{args}/snapshot.json with: slug, title, version (from pyproject.toml),
      delivered_date (today), merge_commit, metrics, and five acts narrative from the todo artifacts.
   c. git -C "$MAIN_REPO" add demos/{args}/snapshot.json && git -C "$MAIN_REPO" commit -m "chore({args}): add demo snapshot"
   If demos/{args}/demo.md does NOT exist, skip — no demo was created for this delivery.
9. CLEANUP (orchestrator-owned, from main repo root):
   a. git -C "$MAIN_REPO" worktree remove trees/{args} --force
   b. git -C "$MAIN_REPO" branch -d {args}
   c. rm -rf "$MAIN_REPO/todos/{args}"
   d. git -C "$MAIN_REPO" add -A && git -C "$MAIN_REPO" commit -m "chore: cleanup {args}"
10. git -C "$MAIN_REPO" push origin main
11. make restart (daemon picks up merged code before next dispatch)
12. Call {next_call}
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
    return f"""UNCOMMITTED CHANGES in trees/{slug}

NEXT: Resolve these changes according to the commit policy, then call telec todo work {slug} to continue."""


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
            all_passed = False
            output = test_result.stdout[-2000:] if test_result.stdout else ""
            stderr = test_result.stderr[-500:] if test_result.stderr else ""
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
    if check_file_exists(worktree_cwd, f"todos/{slug}/bug.md"):
        results.append("GATE SKIPPED: demo validate (bug workflow)")
    else:
        try:
            demo_result = subprocess.run(
                ["telec", "todo", "demo", "validate", slug, "--project-root", worktree_cwd],
                cwd=worktree_cwd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if demo_result.returncode != 0:
                all_passed = False
                results.append(f"GATE FAILED: demo validate (exit {demo_result.returncode})\n{demo_result.stdout}")
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
   a. telec todo mark-phase {slug} --phase build --status complete --cwd <project-root>
   b. Call {next_call}
   If gates fail again, repeat from step 1."""


def format_hitl_guidance(context: str) -> str:
    """Format guidance for the calling AI to work interactively with the user.

    Used when HITL=True.
    """
    return context


def _find_next_prepare_slug(cwd: str) -> str | None:
    """Find the next active slug that still needs preparation work.

    Scans roadmap.yaml for slugs, then checks state.yaml phase for each.
    Active slugs have phase pending, ready, or in_progress.
    Returns the first slug that still needs action:
    - breakdown assessment pending for input.md
    - requirements.md missing
    - implementation-plan.md missing
    - phase still pending (needs promotion to ready)
    """
    for slug in load_roadmap_slugs(cwd):
        phase = get_item_phase(cwd, slug)

        # Skip done items
        if phase == ItemPhase.DONE.value:
            continue

        has_input = check_file_exists(cwd, f"todos/{slug}/input.md")
        if has_input:
            breakdown_state = read_breakdown_state(cwd, slug)
            if breakdown_state is None or not breakdown_state.get("assessed"):
                return slug

        has_requirements = check_file_exists(cwd, f"todos/{slug}/requirements.md")
        has_impl_plan = check_file_exists(cwd, f"todos/{slug}/implementation-plan.md")
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
    "breakdown": {"assessed": False, "todos": []},
    "review_round": 0,
    "max_review_rounds": DEFAULT_MAX_REVIEW_ROUNDS,
    "review_baseline_commit": "",
    "unresolved_findings": [],
    "resolved_findings": [],
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
        return DEFAULT_STATE.copy()

    content = read_text_sync(state_path)
    state: dict[str, StateValue] = yaml.safe_load(content)
    # Merge with defaults for any missing keys
    merged = {**DEFAULT_STATE, **state}

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
    return dict(breakdown)


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
    """Check if a todo is a bug (has bug.md)."""
    return check_file_exists(cwd, f"todos/{slug}/bug.md")


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


def _icebox_path(cwd: str) -> Path:
    return Path(cwd) / "todos" / "icebox.yaml"


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
    return True


# =============================================================================
# Delivered Management (delivered.yaml)
# =============================================================================


@dataclass
class DeliveredEntry:
    slug: str
    date: str
    title: str | None = None
    commit: str | None = None
    description: str | None = None
    children: list[str] | None = None


class DeliveredDict(TypedDict, total=False):
    slug: str
    date: str
    title: str
    commit: str
    description: str
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
                title=item.get("title"),
                commit=item.get("commit"),
                description=item.get("description"),
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
        if entry.title:
            item["title"] = entry.title
        if entry.commit:
            item["commit"] = entry.commit
        if entry.description:
            item["description"] = entry.description
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
    title: str | None = None,
) -> bool:
    """Move a slug from roadmap to delivered (prepended). Returns False if not in roadmap."""
    entries = load_roadmap(cwd)
    entry = None
    for i, e in enumerate(entries):
        if e.slug == slug:
            entry = entries.pop(i)
            break
    if entry is None:
        return False

    save_roadmap(cwd, entries)

    delivered = load_delivered(cwd)
    delivered.insert(
        0,
        DeliveredEntry(
            slug=slug,
            date=date.today().isoformat(),
            title=title or entry.description,
            commit=commit,
            description=entry.description,
        ),
    )
    save_delivered(cwd, delivered)
    return True


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
        description = None

        # Try deliver_to_delivered (handles roadmap removal + delivered.yaml append)
        # Load description from roadmap before removal
        for rm_entry in load_roadmap(cwd):
            if rm_entry.slug == group_slug:
                description = rm_entry.description
                break

        group_title = description or f"Group: {group_slug} ({len(children)} children delivered)"

        delivered = deliver_to_delivered(
            cwd,
            group_slug,
            title=group_title,
        )

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
            entries = load_delivered(cwd)
            entries.insert(
                0,
                DeliveredEntry(
                    slug=group_slug,
                    date=date.today().isoformat(),
                    title=group_title,
                    children=list(children),
                ),
            )
            save_delivered(cwd, entries)

        # Remove the group todo directory
        shutil.rmtree(entry)
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
    """Compose guidance text for agent selection based on config and availability.

    Returns a string block describing available agents, their strengths,
    and any current degradation status.
    """
    lines = ["AGENT SELECTION GUIDANCE:"]

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
        lines.append(f"- {name.upper()}{status_note}:")
        strengths_text = cfg.strengths.strip() or "Not configured (set config.yml:agents.<name>.strengths)."
        avoid_text = cfg.avoid.strip() or "Not configured (set config.yml:agents.<name>.avoid)."
        lines.append(f"  Strengths: {strengths_text}")
        lines.append(f"  Avoid: {avoid_text}")

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
    worktree_root = Path(cwd) / "trees" / slug
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
    trees_root = Path(cwd) / "trees"
    if not trees_root.exists():
        return
    for entry in trees_root.iterdir():
        if entry.is_dir():
            sync_main_to_worktree(cwd, entry.name)


def sync_worktree_to_main(cwd: str, slug: str, relative_files: list[str]) -> None:
    """Copy slug-specific workflow files from worktree back to main repo."""
    main_root = Path(cwd)
    worktree_root = Path(cwd) / "trees" / slug
    if not worktree_root.exists():
        return
    for rel in relative_files:
        _sync_file(worktree_root, main_root, rel)


def sync_slug_todo_from_worktree_to_main(cwd: str, slug: str) -> None:
    """Copy canonical todo artifacts for a slug from worktree back to main."""
    todo_base = f"todos/{slug}"
    sync_worktree_to_main(
        cwd,
        slug,
        [
            f"{todo_base}/bug.md",
            f"{todo_base}/requirements.md",
            f"{todo_base}/implementation-plan.md",
            f"{todo_base}/state.yaml",
            f"{todo_base}/review-findings.md",
            f"{todo_base}/deferrals.md",
            f"{todo_base}/breakdown.md",
            f"{todo_base}/dor-report.md",
        ],
    )


def sync_slug_todo_from_main_to_worktree(cwd: str, slug: str) -> int:
    """Copy canonical todo artifacts for a slug from main into worktree.

    Planning artifacts are copied from main when changed (main remains source of truth).
    state.yaml is only seeded when missing — the worktree owns build/review
    progress once work begins.
    """
    todo_base = f"todos/{slug}"
    main_root = Path(cwd)
    worktree_root = Path(cwd) / "trees" / slug
    if not worktree_root.exists():
        return 0
    # Planning artifacts: main is source of truth; unchanged files are skipped.
    copied = 0
    for rel in [
        f"{todo_base}/bug.md",
        f"{todo_base}/input.md",
        f"{todo_base}/requirements.md",
        f"{todo_base}/implementation-plan.md",
        f"{todo_base}/quality-checklist.md",
        f"{todo_base}/review-findings.md",
        f"{todo_base}/deferrals.md",
        f"{todo_base}/breakdown.md",
        f"{todo_base}/dor-report.md",
    ]:
        if _sync_file(main_root, worktree_root, rel):
            copied += 1
    # state.yaml: seed only — worktree owns build/review progress.
    state_rel = f"{todo_base}/state.yaml"
    src = main_root / state_rel
    dst = worktree_root / state_rel
    if src.exists() and not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    return copied


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
    worktree_path = Path(cwd) / "trees" / slug
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
# Finalize lock — serializes merges to main across parallel orchestrators
# ---------------------------------------------------------------------------

_FINALIZE_LOCK_NAME = ".finalize-lock"
_FINALIZE_LOCK_STALE_MINUTES = 30


def _finalize_lock_path(cwd: str) -> Path:
    return Path(cwd) / "todos" / _FINALIZE_LOCK_NAME


def acquire_finalize_lock(cwd: str, slug: str, session_id: str) -> str | None:
    """Acquire the finalize lock. Returns None on success, error message on failure."""
    lock_path = _finalize_lock_path(cwd)
    if lock_path.exists():
        try:
            lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupt lock — treat as stale
            lock_path.unlink(missing_ok=True)
        else:
            from datetime import datetime, timezone

            acquired_at = lock_data.get("acquired_at", "")
            holding_session = lock_data.get("session_id", "unknown")
            holding_slug = lock_data.get("slug", "unknown")

            # Check staleness by timestamp
            try:
                lock_time = datetime.fromisoformat(acquired_at)
                age_minutes = (datetime.now(timezone.utc) - lock_time).total_seconds() / 60
                if age_minutes > _FINALIZE_LOCK_STALE_MINUTES:
                    logger.warning(
                        "Breaking stale finalize lock (age=%.0fm, slug=%s, session=%s)",
                        age_minutes,
                        holding_slug,
                        holding_session[:8],
                    )
                    lock_path.unlink(missing_ok=True)
                else:
                    return (
                        f"FINALIZE_LOCKED\n"
                        f"Another finalize is in progress: slug={holding_slug}, "
                        f"session={holding_session[:8]}, age={age_minutes:.0f}m.\n"
                        f"Wait for it to complete or check if the session is still alive."
                    )
            except (ValueError, TypeError):
                # Unparseable timestamp — stale
                lock_path.unlink(missing_ok=True)

    # Acquire
    from datetime import datetime, timezone

    lock_data = {
        "slug": slug,
        "session_id": session_id,
        "acquired_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(json.dumps(lock_data, indent=2), encoding="utf-8")
        logger.info("Finalize lock acquired: slug=%s, session=%s", slug, session_id[:8])
        return None
    except OSError as exc:
        return f"FINALIZE_LOCK_ERROR\nFailed to acquire finalize lock: {exc}"


def release_finalize_lock(cwd: str, session_id: str | None = None) -> bool:
    """Release the finalize lock. If session_id is given, only release if it matches."""
    lock_path = _finalize_lock_path(cwd)
    if not lock_path.exists():
        return True
    if session_id:
        try:
            lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
            if lock_data.get("session_id") != session_id:
                logger.debug(
                    "Finalize lock held by different session (%s), not releasing",
                    lock_data.get("session_id", "unknown")[:8],
                )
                return False
        except (json.JSONDecodeError, OSError):
            pass
    lock_path.unlink(missing_ok=True)
    logger.info("Finalize lock released (session=%s)", (session_id or "any")[:8])
    return True


def get_finalize_lock_holder(cwd: str) -> dict[str, str] | None:
    """Return lock holder info or None if unlocked."""
    lock_path = _finalize_lock_path(cwd)
    if not lock_path.exists():
        return None
    try:
        return json.loads(lock_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _worktree_prep_state_path(cwd: str, slug: str) -> Path:
    """Get prep-state marker path inside worktree."""
    return Path(cwd) / "trees" / slug / _WORKTREE_PREP_STATE_REL


def _compute_prep_inputs_digest(cwd: str, slug: str) -> str:
    """Compute hash of dependency-installation inputs that impact prep."""
    project_root = Path(cwd)
    worktree_root = project_root / "trees" / slug
    digest = hashlib.sha256()

    candidates: list[tuple[str, Path]] = []
    for rel in _PREP_ROOT_INPUT_FILES:
        candidates.append((f"root:{rel}", project_root / rel))
    for rel in _PREP_INPUT_FILES:
        candidates.append((f"worktree:{rel}", worktree_root / rel))

    for label, path in sorted(candidates, key=lambda item: item[0]):
        digest.update(label.encode("utf-8"))
        exists = path.exists()
        digest.update((b"1" if exists else b"0"))
        if not exists:
            continue
        is_executable = os.access(path, os.X_OK)
        digest.update((b"1" if is_executable else b"0"))
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
        "prepared_at": datetime.now(timezone.utc).isoformat(),
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


def ensure_worktree_with_policy(cwd: str, slug: str) -> EnsureWorktreeResult:
    """Ensure worktree exists and run prep only when policy says it's stale."""
    worktree_path = Path(cwd) / "trees" / slug
    created = False
    if not worktree_path.exists():
        try:
            repo = Repo(cwd)
        except InvalidGitRepositoryError:
            logger.error("Cannot create worktree: %s is not a git repository", cwd)
            raise
        trees_dir = Path(cwd) / "trees"
        trees_dir.mkdir(exist_ok=True)
        repo.git.worktree("add", str(worktree_path), "-b", slug)
        logger.info("Created worktree at %s", worktree_path)
        created = True

    prep_decision = _decide_worktree_prep(cwd, slug, created=created)
    if prep_decision.should_prepare:
        _prepare_worktree(cwd, slug)
        _write_worktree_prep_state(cwd, slug, prep_decision.inputs_digest)
        return EnsureWorktreeResult(created=created, prepared=True, prep_reason=prep_decision.reason)
    return EnsureWorktreeResult(created=created, prepared=False, prep_reason=prep_decision.reason)


def ensure_worktree(cwd: str, slug: str) -> bool:
    """Compatibility wrapper returning whether a worktree was newly created."""
    result = ensure_worktree_with_policy(cwd, slug)
    return result.created


async def ensure_worktree_with_policy_async(cwd: str, slug: str) -> EnsureWorktreeResult:
    """Async wrapper to ensure worktree with prep decision policy."""
    return await asyncio.to_thread(ensure_worktree_with_policy, cwd, slug)


async def ensure_worktree_async(cwd: str, slug: str) -> bool:
    """Async wrapper to ensure worktree without blocking the event loop."""
    return await asyncio.to_thread(ensure_worktree, cwd, slug)


def _prepare_worktree(cwd: str, slug: str) -> None:
    """Prepare a worktree using repo conventions.

    Conventions:
    - If `scripts.worktree:prepare` is defined in teleclaude.yml, run it.
    - Else if tools/worktree-prepare.sh exists and is executable, run it with the slug.
    - If Makefile has `install`, run `make install`.
    - Else if package.json exists, run `pnpm install` if available, otherwise `npm install`.
    - If neither applies, do nothing.
    """
    worktree_path = Path(cwd) / "trees" / slug
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


def is_main_ahead(cwd: str, slug: str) -> bool | None:
    """Check if local main has commits not in the worktree branch.

    Args:
        cwd: Project root directory
        slug: Work item slug (worktree is at trees/{slug})

    Returns:
        True if main is ahead of HEAD for the worktree, False if not ahead,
        or None when ahead-state cannot be determined.
    """
    worktree_path = Path(cwd) / "trees" / slug
    if not worktree_path.exists():
        return None

    try:
        repo = Repo(worktree_path)
        ahead_count_raw = repo.git.rev_list("--count", "HEAD..main")  # type: ignore[misc]
        if not isinstance(ahead_count_raw, str):
            return None
        ahead_count = ahead_count_raw.strip()
        if not ahead_count.isdigit():
            return None
        return int(ahead_count) > 0
    except (InvalidGitRepositoryError, GitCommandError, ValueError):
        logger.warning("Cannot determine main ahead status for %s", worktree_path)
        return None


def get_finalize_canonical_dirty_paths(cwd: str) -> list[str] | None:
    """Return canonical dirty paths, or None when git state cannot be inspected."""
    try:
        repo = Repo(cwd)
        return _dirty_paths(repo)
    except (InvalidGitRepositoryError, NoSuchPathError, GitCommandError):
        logger.warning("Cannot inspect canonical dirty state for finalize preconditions at %s", cwd)
        return None


def check_finalize_preconditions(cwd: str, slug: str) -> str | None:
    """Validate canonical main safety before finalize dispatch/apply."""
    allowed_dirty_paths = {f"todos/{_FINALIZE_LOCK_NAME}"}

    dirty_paths = get_finalize_canonical_dirty_paths(cwd)
    if dirty_paths is None:
        return format_error(
            "FINALIZE_PRECONDITION_GIT_STATE_UNKNOWN",
            "Cannot inspect canonical main git state for finalize safety preconditions.",
            next_call=f"Restore git access/health, then call telec todo work {slug} again.",
        )

    blocked_paths: list[str] = []
    for raw_path in dirty_paths:
        normalized = raw_path.replace("\\", "/").lstrip("./")
        if normalized in allowed_dirty_paths:
            continue
        blocked_paths.append(normalized)

    if blocked_paths:
        unique_paths = sorted(dict.fromkeys(blocked_paths))
        preview = ", ".join(unique_paths[:5])
        if len(unique_paths) > 5:
            preview += ", ..."
        return format_error(
            "FINALIZE_PRECONDITION_DIRTY_CANONICAL_MAIN",
            (f"Canonical main has uncommitted changes that make finalize apply unsafe: {preview}."),
            next_call=f"Commit or clean canonical main changes, then call telec todo work {slug} again.",
        )

    main_ahead = is_main_ahead(cwd, slug)
    if main_ahead is None:
        return format_error(
            "FINALIZE_PRECONDITION_GIT_STATE_UNKNOWN",
            "Cannot determine whether canonical main is ahead of the finalize branch.",
            next_call=f"Restore git access/health, then call telec todo work {slug} again.",
        )
    if main_ahead:
        return format_error(
            "FINALIZE_PRECONDITION_MAIN_AHEAD",
            (f"Canonical main has commits not present on branch '{slug}', so deterministic finalize apply is blocked."),
            next_call=f"Update {slug} with latest main (merge/rebase), then call telec todo work {slug} again.",
        )

    return None


# =============================================================================
# Main Functions
# =============================================================================


async def next_prepare(db: Db, slug: str | None, cwd: str, hitl: bool = True) -> str:
    """Phase A state machine for collaborative architect work.

    Checks what's missing (requirements.md, implementation-plan.md) and
    returns instructions to dispatch the appropriate architect session.

    Args:
        db: Database instance
        slug: Optional explicit slug (resolved from roadmap if HITL=False)
        cwd: Current working directory (project root)
        hitl: Human-In-The-Loop mode. If True (default), returns guidance
              for calling AI. If False, dispatches to another AI.

    Returns:
        Plain text instructions for the orchestrator to execute
    """
    try:
        # 1. Resolve slug
        resolved_slug = slug
        if not resolved_slug:
            resolved_slug = await asyncio.to_thread(_find_next_prepare_slug, cwd)

        if not resolved_slug:
            if hitl:
                return format_hitl_guidance(
                    "No active preparation work found. "
                    "All active slugs already have requirements.md and implementation-plan.md "
                    "with breakdown assessed where needed."
                )

            # Dispatch next-prepare-draft (no slug) when hitl=False
            guidance = await compose_agent_guidance(db)
            return format_tool_call(
                command="next-prepare-draft",
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

        # 1.5. Ensure slug exists in roadmap before preparing
        if not await asyncio.to_thread(slug_in_roadmap, cwd, resolved_slug):
            has_requirements = check_file_exists(cwd, f"todos/{resolved_slug}/requirements.md")
            has_impl_plan = check_file_exists(cwd, f"todos/{resolved_slug}/implementation-plan.md")
            missing_docs: list[str] = []
            if not has_requirements:
                missing_docs.append("requirements.md")
            if not has_impl_plan:
                missing_docs.append("implementation-plan.md")
            docs_clause = "."
            if missing_docs:
                docs_list = " and ".join(missing_docs)
                docs_clause = f" before writing {docs_list}."
            next_step = (
                "Discuss with the user where it should appear in the list and get approval, "
                f"then add it to the roadmap{docs_clause}"
            )
            note = f"Preparing: {resolved_slug}. This slug is not in todos/roadmap.yaml. {next_step}"
            if hitl:
                return format_hitl_guidance(note)

            guidance = await compose_agent_guidance(db)
            return format_tool_call(
                command="next-prepare-draft",
                args=resolved_slug,
                project=cwd,
                guidance=guidance,
                subfolder="",
                note=note,
                next_call="telec todo prepare",
            )

        # 1.6. Check for breakdown assessment
        has_input = check_file_exists(cwd, f"todos/{resolved_slug}/input.md")
        breakdown_state = await asyncio.to_thread(read_breakdown_state, cwd, resolved_slug)

        if has_input and (breakdown_state is None or not breakdown_state.get("assessed")):
            # Breakdown assessment needed
            if hitl:
                return format_hitl_guidance(
                    f"Preparing: {resolved_slug}. Read todos/{resolved_slug}/input.md and assess "
                    "Definition of Ready. If complex, split into smaller todos. Then update state.yaml "
                    "and create breakdown.md."
                )
            # Non-HITL: dispatch architect to assess
            guidance = await compose_agent_guidance(db)
            return format_tool_call(
                command="next-prepare-draft",
                args=resolved_slug,
                project=cwd,
                guidance=guidance,
                subfolder="",
                note=f"Assess todos/{resolved_slug}/input.md for complexity. Split if needed.",
                next_call="telec todo prepare",
            )

        # 2. Check requirements
        if not check_file_exists(cwd, f"todos/{resolved_slug}/requirements.md"):
            if hitl:
                return format_hitl_guidance(
                    f"Preparing: {resolved_slug}. Write todos/{resolved_slug}/requirements.md "
                    f"and todos/{resolved_slug}/implementation-plan.md yourself."
                )

            guidance = await compose_agent_guidance(db)
            return format_tool_call(
                command="next-prepare-draft",
                args=resolved_slug,
                project=cwd,
                guidance=guidance,
                subfolder="",
                note=f"Discuss until you have enough input. Write todos/{resolved_slug}/requirements.md yourself.",
                next_call="telec todo prepare",
            )

        # 3. Check implementation plan
        if not check_file_exists(cwd, f"todos/{resolved_slug}/implementation-plan.md"):
            if hitl:
                return format_hitl_guidance(
                    f"Preparing: {resolved_slug}. Write todos/{resolved_slug}/implementation-plan.md yourself."
                )

            guidance = await compose_agent_guidance(db)
            return format_tool_call(
                command="next-prepare-draft",
                args=resolved_slug,
                project=cwd,
                guidance=guidance,
                subfolder="",
                note=f"Discuss until you have enough input. Write todos/{resolved_slug}/implementation-plan.md yourself.",
                next_call="telec todo prepare",
            )

        # 4. Both exist - check DOR readiness (no phase mutation; readiness is derived)
        current_phase = await asyncio.to_thread(get_item_phase, cwd, resolved_slug)
        if current_phase == ItemPhase.PENDING.value:
            phase_state = await asyncio.to_thread(read_phase_state, cwd, resolved_slug)
            dor = phase_state.get("dor")
            dor_score = dor.get("score") if isinstance(dor, dict) else None
            if isinstance(dor_score, int) and dor_score >= DOR_READY_THRESHOLD:
                await asyncio.to_thread(sync_main_to_worktree, cwd, resolved_slug)
            else:
                if hitl:
                    return format_hitl_guidance(
                        f"Preparing: {resolved_slug}. Requirements and implementation plan exist, "
                        f"but DOR score is below threshold ({DOR_READY_THRESHOLD}). Complete DOR assessment, update "
                        f"todos/{resolved_slug}/dor-report.md and todos/{resolved_slug}/state.yaml.dor "
                        f"with score >= {DOR_READY_THRESHOLD}. Then run /next-prepare-gate {resolved_slug} (separate worker) "
                        f"and call telec todo prepare {resolved_slug} again."
                    )

                guidance = await compose_agent_guidance(db)
                return format_tool_call(
                    command="next-prepare-gate",
                    args=resolved_slug,
                    project=cwd,
                    guidance=guidance,
                    subfolder="",
                    note=(
                        f"Requirements/plan exist for {resolved_slug}, but DOR score is below threshold. "
                        f"Complete DOR assessment and set state.yaml.dor.score >= {DOR_READY_THRESHOLD}."
                    ),
                    next_call="telec todo prepare",
                )
        # else: already in_progress or done - no state change needed
        return format_prepared(resolved_slug)
    except RuntimeError:
        raise


async def next_work(db: Db, slug: str | None, cwd: str, caller_session_id: str | None = None) -> str:
    """Phase B state machine for deterministic builder work.

    Executes the build/review/fix/finalize cycle on prepared work items.
    Only considers items with phase "ready" and satisfied dependencies.

    Args:
        db: Database instance
        slug: Optional explicit slug (resolved from roadmap if not provided)
        cwd: Current working directory (project root)
        caller_session_id: Session ID of the calling orchestrator (for finalize lock)

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

    # Release finalize lock ONLY if the locked item's finalize is confirmed complete.
    # Finalize removes the slug from roadmap, so "not in roadmap" is the completion signal.
    if caller_session_id:
        lock_holder = get_finalize_lock_holder(cwd)
        if lock_holder and lock_holder.get("session_id") == caller_session_id:
            locked_slug = lock_holder.get("slug", "")
            if locked_slug:
                finalize_done = get_item_phase(cwd, locked_slug) == ItemPhase.DONE.value or not slug_in_roadmap(
                    cwd, locked_slug
                )
                if finalize_done:
                    release_finalize_lock(cwd, caller_session_id)

    phase_slug = slug or "<auto>"
    slug_resolution_started = perf_counter()

    # 1. Resolve slug - only ready items when no explicit slug
    # Prefer worktree-local planning state when explicit slug worktree exists.
    deps_cwd = cwd
    if slug:
        maybe_worktree = Path(cwd) / "trees" / slug
        if (maybe_worktree / "todos" / "roadmap.yaml").exists():
            deps_cwd = str(maybe_worktree)
    deps = await asyncio.to_thread(load_roadmap_deps, deps_cwd)

    resolved_slug: str
    if slug:
        # Explicit slug provided - verify it's in roadmap, ready, and dependencies satisfied
        # Bugs bypass the roadmap check (they're not in the roadmap)
        is_bug = await asyncio.to_thread(is_bug_todo, cwd, slug)
        if not is_bug and not await asyncio.to_thread(slug_in_roadmap, cwd, slug):
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
                    next_call="Complete dependency items first, or check todos/roadmap.yaml.",
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
                    next_call="Check todos/roadmap.yaml or call telec todo prepare.",
                )
            else:
                _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "error", "slug_missing")
                return format_error(
                    "NOT_PREPARED",
                    f"Item '{slug}' not found in roadmap.",
                    next_call="Check todos/roadmap.yaml or call telec todo prepare.",
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
    # Bugs skip requirements.md and implementation-plan.md checks (they use bug.md instead)
    precondition_root = cwd
    worktree_path = Path(cwd) / "trees" / resolved_slug
    if (
        worktree_path.exists()
        and (worktree_path / "todos" / resolved_slug / "requirements.md").exists()
        and (worktree_path / "todos" / resolved_slug / "implementation-plan.md").exists()
    ):
        precondition_root = str(worktree_path)

    is_bug = await asyncio.to_thread(is_bug_todo, cwd, resolved_slug)
    if not is_bug:
        has_requirements = check_file_exists(precondition_root, f"todos/{resolved_slug}/requirements.md")
        has_impl_plan = check_file_exists(precondition_root, f"todos/{resolved_slug}/implementation-plan.md")
        if not (has_requirements and has_impl_plan):
            _log_next_work_phase(phase_slug, "preconditions", preconditions_started, "error", "not_prepared")
            return format_error(
                "NOT_PREPARED",
                f"todos/{resolved_slug} is missing requirements or implementation plan.",
                next_call=f"Call telec todo prepare {resolved_slug} to complete preparation.",
            )
    _log_next_work_phase(phase_slug, "preconditions", preconditions_started, "run", "validated")

    worktree_cwd = str(Path(cwd) / "trees" / resolved_slug)
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
            ensure_result = await ensure_worktree_with_policy_async(cwd, resolved_slug)
            if ensure_result.created:
                logger.info("Created new worktree for %s", resolved_slug)
            ensure_decision = "run" if ensure_result.prepared else "skip"
            _log_next_work_phase(
                phase_slug, "ensure_prepare", ensure_started, ensure_decision, ensure_result.prep_reason
            )

            sync_started = perf_counter()
            main_sync_copied = await asyncio.to_thread(sync_main_to_worktree, cwd, resolved_slug)
            slug_sync_copied = await asyncio.to_thread(sync_slug_todo_from_main_to_worktree, cwd, resolved_slug)
            total_synced = main_sync_copied + slug_sync_copied
            sync_decision = "run" if total_synced > 0 else "skip"
            sync_reason = (
                f"copied main={main_sync_copied} slug={slug_sync_copied}" if total_synced > 0 else "unchanged_inputs"
            )
            _log_next_work_phase(phase_slug, "sync", sync_started, sync_decision, sync_reason)
    except RuntimeError as exc:
        _log_next_work_phase(phase_slug, "ensure_prepare", ensure_started, "error", "prep_failed")
        return format_error(
            "WORKTREE_PREP_FAILED",
            str(exc),
            next_call="Add tools/worktree-prepare.sh or fix its execution, then retry.",
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
        await asyncio.to_thread(sync_slug_todo_from_worktree_to_main, cwd, resolved_slug)
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
        if baseline and head_sha and baseline != head_sha:
            repair_started = perf_counter()
            await asyncio.to_thread(
                mark_phase, worktree_cwd, resolved_slug, PhaseName.REVIEW.value, PhaseStatus.PENDING.value
            )
            await asyncio.to_thread(sync_slug_todo_from_worktree_to_main, cwd, resolved_slug)
            review_status = PhaseStatus.PENDING.value
            _log_next_work_phase(
                phase_slug,
                "state_repair",
                repair_started,
                "run",
                "review_approval_stale_baseline",
            )

    # If review requested changes, continue fix loop regardless of build-state drift.
    if review_status == PhaseStatus.CHANGES_REQUESTED.value:
        try:
            guidance = await compose_agent_guidance(db)
        except RuntimeError as exc:
            _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
            return format_error("NO_AGENTS", str(exc))
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_fix_review")
        return format_tool_call(
            command="next-fix-review",
            args=resolved_slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"trees/{resolved_slug}",
            next_call=f"telec todo work {resolved_slug}",
        )

    # Pending review still requires build completion + gates before dispatching review.
    if review_status != PhaseStatus.APPROVED.value:
        # mark_phase(build, started) is deferred to the orchestrator via pre_dispatch
        # to avoid orphaned "build: started" when the orchestrator decides not to dispatch.
        if build_status != PhaseStatus.COMPLETE.value:
            try:
                guidance = await compose_agent_guidance(db)
            except RuntimeError as exc:
                _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
                return format_error("NO_AGENTS", str(exc))

            # Build pre-dispatch marking instructions
            pre_dispatch = f"telec todo mark-phase {resolved_slug} --phase build --status started --cwd <project-root>"

            # Bugs use next-bugs-fix instead of next-build
            is_bug = await asyncio.to_thread(is_bug_todo, worktree_cwd, resolved_slug)
            if is_bug:
                _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_bugs_fix")
                return format_tool_call(
                    command="next-bugs-fix",
                    args=resolved_slug,
                    project=cwd,
                    guidance=guidance,
                    subfolder=f"trees/{resolved_slug}",
                    next_call=f"telec todo work {resolved_slug}",
                    pre_dispatch=pre_dispatch,
                )
            _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_build")
            return format_tool_call(
                command="next-build",
                args=resolved_slug,
                project=cwd,
                guidance=guidance,
                subfolder=f"trees/{resolved_slug}",
                next_call=f"telec todo work {resolved_slug}",
                pre_dispatch=pre_dispatch,
            )

        # Build gates: verify tests and demo structure before allowing review.
        gate_started = perf_counter()
        gates_passed, gate_output = await asyncio.to_thread(run_build_gates, worktree_cwd, resolved_slug)
        if not gates_passed:
            _log_next_work_phase(phase_slug, "gate_execution", gate_started, "error", "build_gates_failed")
            # Reset build to started so the builder can fix and try again
            await asyncio.to_thread(
                mark_phase, worktree_cwd, resolved_slug, PhaseName.BUILD.value, PhaseStatus.STARTED.value
            )
            # Sync reset state back to main
            await asyncio.to_thread(sync_slug_todo_from_worktree_to_main, cwd, resolved_slug)
            next_call = f"telec todo work {resolved_slug}"
            return format_build_gate_failure(resolved_slug, gate_output, next_call)
        _log_next_work_phase(phase_slug, "gate_execution", gate_started, "run", "build_gates_passed")

        # Review not started or still pending.
        limit_reached, current_round, max_rounds = _is_review_round_limit_reached(worktree_cwd, resolved_slug)
        if limit_reached:
            _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "review_round_limit")
            return format_error(
                "REVIEW_ROUND_LIMIT",
                (
                    f"Review rounds exceeded for {resolved_slug}: "
                    f"current={current_round}, max={max_rounds}. Decision required."
                ),
                next_call=(
                    f"Apply orchestrator review-round-limit closure for {resolved_slug}, "
                    f"then call telec todo work {resolved_slug}"
                ),
            )
        try:
            guidance = await compose_agent_guidance(db)
        except RuntimeError as exc:
            _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
            return format_error("NO_AGENTS", str(exc))
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_review")
        return format_tool_call(
            command="next-review",
            args=resolved_slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"trees/{resolved_slug}",
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
            command="next-defer",
            args=resolved_slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"trees/{resolved_slug}",
            next_call=f"telec todo work {resolved_slug}",
        )

    # 9. Review approved - dispatch finalize prepare (serialized via finalize lock)
    if has_uncommitted_changes(cwd, resolved_slug):
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "uncommitted_changes")
        return format_uncommitted_changes(resolved_slug)
    if not caller_session_id:
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "caller_session_missing")
        return format_error(
            "CALLER_SESSION_REQUIRED",
            (
                "Finalize dispatch requires caller_session_id so FINALIZE_READY consumption stays "
                "bound to the orchestrator lock owner."
            ),
            next_call=(
                "Call telec todo work from a wrapper-injected orchestrator session so caller_session_id is present."
            ),
        )
    session_id = caller_session_id
    lock_error = acquire_finalize_lock(cwd, resolved_slug, session_id)
    if lock_error:
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "finalize_lock_held")
        return lock_error
    finalize_precondition_error = await asyncio.to_thread(check_finalize_preconditions, cwd, resolved_slug)
    if finalize_precondition_error:
        release_finalize_lock(cwd, session_id)
        return finalize_precondition_error
    try:
        guidance = await compose_agent_guidance(db)
    except RuntimeError as exc:
        release_finalize_lock(cwd, session_id)
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
        return format_error("NO_AGENTS", str(exc))

    # Bugs skip delivered.yaml bookkeeping and are removed from todos entirely
    is_bug = await asyncio.to_thread(is_bug_todo, worktree_cwd, resolved_slug)
    note = "BUG FIX: Skip delivered.yaml bookkeeping. Delete todo directory after merge." if is_bug else ""
    _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_finalize")
    return format_tool_call(
        command="next-finalize",
        args=resolved_slug,
        project=cwd,
        guidance=guidance,
        subfolder=f"trees/{resolved_slug}",
        next_call="telec todo work",
        note=note,
    )
