"""Next Machine - Deterministic workflow state machine for orchestrating work.

This module provides two main functions:
- next_prepare(): Phase A state machine for collaborative architect work
- next_work(): Phase B state machine for deterministic builder work

Both derive state from files (stateless) and return plain text instructions
for the orchestrator AI to execute literally.
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
from enum import Enum
from pathlib import Path
from typing import cast

from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError
from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.db import Db
from teleclaude.core.models import ThinkingMode

logger = get_logger(__name__)

StateValue = str | bool | int | list[str] | dict[str, bool | list[str]]


class PhaseName(str, Enum):
    BUILD = "build"
    REVIEW = "review"


class PhaseStatus(str, Enum):
    PENDING = "pending"
    COMPLETE = "complete"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


class RoadmapMarker(str, Enum):
    PENDING = " "
    READY = "."
    IN_PROGRESS = ">"
    DONE = "x"


class RoadmapBox(str, Enum):
    PENDING = "[ ]"
    READY = "[.]"
    IN_PROGRESS = "[>]"
    DONE = "[x]"


class WorktreeScript(str, Enum):
    PREPARE = "worktree:prepare"


SCRIPTS_KEY = "scripts"
UNCHECKED_TASK_MARKER = "- [ ]"
REVIEW_APPROVE_MARKER = "[x] APPROVE"
PAREN_OPEN = "("
DEFAULT_MAX_REVIEW_ROUNDS = 3
FINDING_ID_PATTERN = re.compile(r"\bR\d+-F\d+\b")
NO_SELECTABLE_AGENTS_PATTERN = re.compile(r"No selectable agents for task '([^']+)'")

# Fallback matrices: task_type -> [(agent, thinking_mode), ...]
PREPARE_FALLBACK: dict[str, list[tuple[str, str]]] = {
    "prepare": [
        (AgentName.CLAUDE.value, ThinkingMode.SLOW.value),
        (AgentName.CODEX.value, ThinkingMode.SLOW.value),
        (AgentName.GEMINI.value, ThinkingMode.SLOW.value),
    ],
}

WORK_FALLBACK: dict[str, list[tuple[str, str]]] = {
    "build": [
        (AgentName.GEMINI.value, ThinkingMode.MED.value),
        (AgentName.CLAUDE.value, ThinkingMode.MED.value),
        (AgentName.CODEX.value, ThinkingMode.MED.value),
    ],
    "review": [
        (AgentName.CODEX.value, ThinkingMode.SLOW.value),
        (AgentName.CLAUDE.value, ThinkingMode.SLOW.value),
        (AgentName.GEMINI.value, ThinkingMode.SLOW.value),
    ],
    "fix": [
        (AgentName.CLAUDE.value, ThinkingMode.MED.value),
        (AgentName.GEMINI.value, ThinkingMode.MED.value),
        (AgentName.CODEX.value, ThinkingMode.MED.value),
    ],
    "finalize": [
        (AgentName.CLAUDE.value, ThinkingMode.MED.value),
        (AgentName.GEMINI.value, ThinkingMode.MED.value),
        (AgentName.CODEX.value, ThinkingMode.MED.value),
    ],
    "defer": [
        (AgentName.CLAUDE.value, ThinkingMode.MED.value),
        (AgentName.GEMINI.value, ThinkingMode.MED.value),
        (AgentName.CODEX.value, ThinkingMode.MED.value),
    ],
    "docs": [
        (AgentName.CODEX.value, ThinkingMode.MED.value),
        (AgentName.CLAUDE.value, ThinkingMode.MED.value),
        (AgentName.GEMINI.value, ThinkingMode.MED.value),
    ],
}

# Post-completion instructions for each command (used in format_tool_call)
# These tell the orchestrator what to do AFTER a worker completes
POST_COMPLETION: dict[str, str] = {
    "next-build": """WHEN WORKER COMPLETES:
1. MANDATORY VERIFICATION - Never trust worker self-reports, so FROM WITHIN WORKTREE:
     - Run linter
     - Run tests
     - Commits with --no-verify indicate incomplete work
     - If checks fail, work is NOT done
2a. If verification FAILS:
    - Keep session alive and guide worker to resolution
    - Only mark phase when YOUR verification passes    
2b. If success:
   - teleclaude__mark_phase(slug="{args}", phase="build", status="complete")
   - teleclaude__end_session(computer="local", session_id="<session_id>")
   - Call {next_call}
""",
    "next-review": """WHEN WORKER COMPLETES:
1. Read trees/{args}/todos/{args}/review-findings.md
2. Relay verdict to state:
   - If "[x] APPROVE": teleclaude__mark_phase(slug="{args}", phase="review", status="approved")
   - If "[x] REQUEST CHANGES": teleclaude__mark_phase(slug="{args}", phase="review", status="changes_requested")
3. teleclaude__end_session(computer="local", session_id="<session_id>")
4. Call {next_call}
""",
    "next-fix-review": """WHEN WORKER COMPLETES:
1. Verify fixes applied and tests pass
2. If fixes complete:
   - teleclaude__mark_phase(slug="{args}", phase="review", status="pending")
   - teleclaude__end_session(computer="local", session_id="<session_id>")
   - Call {next_call}
3. If fixes incomplete:
   - Keep session alive and guide worker to finish
""",
    "next-defer": """WHEN WORKER COMPLETES:
1. Verify state.json.deferrals_processed is true
2. teleclaude__end_session(computer="local", session_id="<session_id>")
3. Call {next_call}
""",
    "next-finalize": """WHEN WORKER COMPLETES:
1. Verify merge succeeded and delivery log updated
2. If success:
   - teleclaude__end_session(computer="local", session_id="<session_id>")
   - Call {next_call}
3. If failed:
   - Keep session alive and help resolve""",
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
    agent: str,
    thinking_mode: str,
    subfolder: str,
    note: str = "",
    next_call: str = "",
    completion_args: str | None = None,
) -> str:
    """Format a literal tool call for the orchestrator to execute."""
    raw_command = command.lstrip("/")
    formatted_command = f"/{raw_command}"

    # Get post-completion instructions for this command
    post_completion = POST_COMPLETION.get(command, "")
    if post_completion:
        next_call_display = next_call.strip()
        if next_call_display and PAREN_OPEN not in next_call_display:
            next_call_display = f"{next_call_display}()"
        completion_value = completion_args if completion_args is not None else args
        # Substitute {args} and {next_call} placeholders
        post_completion = post_completion.format(args=completion_value, next_call=next_call_display)

    result = f"""Before running the command below, read ~/.agents/commands/{command}.md if you haven't already.

IMPORTANT: This output is an execution script. Follow it verbatim. If you've already read that command file, do not re-read it.

Execute these steps in order (FOLLOW TO THE LETTER!):

STEP 1 - DISPATCH:
teleclaude__run_agent_command(
  computer="local",
  command="{formatted_command}",
  args="{args}",
  project="{project}",
  agent="{agent}",
  thinking_mode="{thinking_mode}",
  subfolder="{subfolder}"
)
Save the returned session_id.

STEP 2 - START BACKGROUND TIMER:
Bash(command="sleep 300", run_in_background=true)
Save the returned task_id.

STEP 3 - STOP:
Tell the user: "Dispatched session <session_id>. Waiting for completion."
STOP responding. Do NOT call any more tools.

WHAT HAPPENS NEXT (one of these will occur):

A) NOTIFICATION ARRIVES (worker completed):
   - The timer is now irrelevant (let it expire or ignore it)
   - Follow WHEN WORKER COMPLETES below

B) TIMER COMPLETES (no notification after 5 minutes):
   - Use TaskOutput(task_id=<task_id>) to confirm timer finished
   - Check on the session: teleclaude__get_session_data(computer="local", session_id="<session_id>", tail_chars=2000)
   - Based on session status, decide next action

C) YOU SEND ANOTHER MESSAGE TO THE AGENT BECAUSE IT NEEDS FEEDBACK OR HELP:
   - Cancel the old timer: KillShell(shell_id=<task_id>)
   - Start a new 5-minute timer: Bash(command="sleep 300", run_in_background=true)
   - Save the new task_id for the reset timer

{post_completion}

ORCHESTRATION PRINCIPLE: Guide process, don't dictate implementation.
You are an orchestrator, not a micromanager. If a worker is stuck, point them
to requirements or docs - never tell them specific commands to run or how to
implement something. They have full autonomy within their context."""
    if note:
        result += f"\n\nNOTE: {note}"
    return result


def format_error(code: str, message: str, next_call: str = "") -> str:
    """Format an error message with optional next step."""
    result = f"ERROR: {code}\n{message}"
    if next_call:
        result += f"\n\nNEXT: {next_call}"
    return result


def _extract_no_selectable_task_type(message: str) -> str | None:
    match = NO_SELECTABLE_AGENTS_PATTERN.search(message)
    return match.group(1) if match else None


def format_agent_selection_error(task_type: str, retry_call: str) -> str:
    return format_error(
        "NO_SELECTABLE_AGENTS",
        (f"No selectable agents for task '{task_type}'. Fallback candidates are currently degraded or unavailable."),
        next_call=(
            "As orchestrator, set provider state with teleclaude__mark_agent_status("
            'agent="<claude|gemini|codex>", status="<degraded|unavailable|available>", reason="<why>"), '
            f"then call {retry_call}"
        ),
    )


def format_prepared(slug: str) -> str:
    """Format a 'prepared' message indicating work item is ready."""
    return f"""PREPARED: todos/{slug} is ready for work.

ASK USER: Do you want to continue with more preparation work, or start the build/review cycle with teleclaude__next_work(slug="{slug}")?"""


def format_uncommitted_changes(slug: str) -> str:
    """Format instruction for orchestrator to resolve worktree uncommitted changes."""
    return f"""UNCOMMITTED CHANGES in trees/{slug}

NEXT: Resolve these changes according to the commit policy, then call teleclaude__next_work(slug="{slug}") to continue."""


def format_hitl_guidance(context: str) -> str:
    """Format guidance for the calling AI to work interactively with the user.

    Used when HITL=True.
    """
    return f"""Before proceeding, read docs/global/general/procedure/maintenance/next-prepare.md if you haven't already.

{context}"""


def _find_next_prepare_slug(cwd: str) -> str | None:
    """Find the next active slug that still needs preparation work.

    Active slugs are roadmap entries with [ ], [.], or [>] state.
    Returns the first slug that still needs action:
    - breakdown assessment pending for input.md
    - requirements.md missing
    - implementation-plan.md missing
    - roadmap state still pending [ ] (needs promotion to [.])
    """
    roadmap_path = Path(cwd) / "todos" / "roadmap.md"
    if not roadmap_path.exists():
        return None

    content = read_text_sync(roadmap_path)
    pattern = re.compile(r"^-\s+\[([ .>])\]\s+(\S+)", re.MULTILINE)

    for match in pattern.finditer(content):
        state = match.group(1)
        slug = match.group(2)

        has_input = check_file_exists(cwd, f"todos/{slug}/input.md")
        if has_input:
            breakdown_state = read_breakdown_state(cwd, slug)
            if breakdown_state is None or not breakdown_state.get("assessed"):
                return slug

        has_requirements = check_file_exists(cwd, f"todos/{slug}/requirements.md")
        has_impl_plan = check_file_exists(cwd, f"todos/{slug}/implementation-plan.md")
        if not has_requirements or not has_impl_plan:
            return slug

        if state == RoadmapMarker.PENDING.value:
            return slug

    return None


# =============================================================================
# Shared Helper Functions
# =============================================================================


# Valid phases and statuses for state.json
DEFAULT_STATE: dict[str, StateValue] = {
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
    """Get path to state.json in worktree."""
    return Path(cwd) / "todos" / slug / "state.json"


def read_phase_state(cwd: str, slug: str) -> dict[str, StateValue]:
    """Read state.json from worktree.

    Returns default state if file doesn't exist.
    """
    state_path = get_state_path(cwd, slug)
    if not state_path.exists():
        return DEFAULT_STATE.copy()

    content = read_text_sync(state_path)
    state: dict[str, StateValue] = json.loads(content)
    # Merge with defaults for any missing keys
    return {**DEFAULT_STATE, **state}


def write_phase_state(cwd: str, slug: str, state: dict[str, StateValue]) -> None:
    """Write state.json."""
    state_path = get_state_path(cwd, slug)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_sync(state_path, json.dumps(state, indent=2) + "\n")


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
    """Build an iterative review scope note from state.json metadata."""
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
    """Read breakdown state from todos/{slug}/state.json.

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

    Returns true if deferrals.md exists AND state.json.deferrals_processed is NOT true.
    """
    deferrals_path = Path(cwd) / "todos" / slug / "deferrals.md"
    if not deferrals_path.exists():
        return False

    state = read_phase_state(cwd, slug)
    return state.get("deferrals_processed") is not True


def resolve_slug(
    cwd: str,
    slug: str | None,
    ready_only: bool = False,
    dependencies: dict[str, list[str]] | None = None,
) -> tuple[str | None, bool, str]:
    """Resolve slug from argument or roadmap.

    Roadmap format expected:
        - [ ] my-slug   (pending - not prepared)
        - [.] my-slug   (ready - prepared, available for work)
        - [>] my-slug   (in progress - claimed by worker)
        Description of the work item.

    Args:
        cwd: Current working directory (project root)
        slug: Optional explicit slug
        ready_only: If True, only match [.] items (for next_work)
        dependencies: Optional dependency graph for dependency gating (R6).
                     If provided with ready_only=True, only returns slugs with satisfied dependencies.

    Returns:
        Tuple of (slug, is_ready_or_in_progress, description).
        If slug provided, returns (slug, True, "").
        If found in roadmap, returns (slug, True if [.] or [>], False if [ ], description).
        If nothing found, returns (None, False, "").
    """
    if slug:
        return slug, True, ""

    roadmap_path = Path(cwd) / "todos" / "roadmap.md"
    if not roadmap_path.exists():
        return None, False, ""

    content = read_text_sync(roadmap_path)

    if ready_only:
        # Only match [.] items for next_work
        pattern = re.compile(r"^-\s+\[\.]\s+(\S+)", re.MULTILINE)
    else:
        # Match [ ], [.], or [>] for next_prepare
        pattern = re.compile(r"^-\s+\[([ .>])\]\s+(\S+)", re.MULTILINE)

    for match in pattern.finditer(content):
        if ready_only:
            found_slug = match.group(1)
            # For ready_only, we know it's [.] so it's "ready"
            is_ready = True
        else:
            status = match.group(1)
            found_slug = match.group(2)
            is_ready = status in (".", ">")

        # R6: Enforce dependency gating when ready_only=True and dependencies provided
        if ready_only and dependencies is not None:
            if not check_dependencies_satisfied(cwd, found_slug, dependencies):
                continue  # Skip items with unsatisfied dependencies

        # Extract description: everything after the slug line until next item or section
        start_pos = match.end()
        next_item = re.search(r"^-\s+\[", content[start_pos:], re.MULTILINE)
        next_section = re.search(r"^##", content[start_pos:], re.MULTILINE)

        end_pos = len(content)
        if next_item:
            end_pos = min(end_pos, start_pos + next_item.start())
        if next_section:
            end_pos = min(end_pos, start_pos + next_section.start())

        description = content[start_pos:end_pos].strip()
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


def slug_in_roadmap(cwd: str, slug: str) -> bool:
    """Check if a slug exists in todos/roadmap.md."""
    roadmap_path = Path(cwd) / "todos" / "roadmap.md"
    if not roadmap_path.exists():
        return False

    content = read_text_sync(roadmap_path)
    pattern = re.compile(rf"^-\s+\[[ .>x]\]\s+{re.escape(slug)}(\s|$)", re.MULTILINE)
    return bool(pattern.search(content))


# =============================================================================
# Roadmap State Management (R3, R7)
# =============================================================================


def get_roadmap_state(cwd: str, slug: str) -> str | None:
    """Get current checkbox state for slug in roadmap.md.

    Args:
        cwd: Project root directory
        slug: Work item slug to query

    Returns:
        One of " " (pending), "." (ready), ">" (in-progress), "x" (done)
        or None if slug not found in roadmap
    """
    roadmap_path = Path(cwd) / "todos" / "roadmap.md"
    if not roadmap_path.exists():
        return None

    content = read_text_sync(roadmap_path)

    # Pattern: - [STATE] slug where STATE is space, ., >, or x
    pattern = re.compile(rf"^- \[([ .>x])\] {re.escape(slug)}(\s|$)", re.MULTILINE)
    match = pattern.search(content)

    return match.group(1) if match else None


def update_roadmap_state(cwd: str, slug: str, new_state: str) -> bool:
    """Update checkbox state for slug in roadmap.md.

    Args:
        cwd: Project root directory
        slug: Work item slug to update
        new_state: One of " " (space), ".", ">", "x"

    Returns:
        True if slug found and updated, False if slug not found

    Side effects:
        - Modifies todos/roadmap.md in place
    """
    roadmap_path = Path(cwd) / "todos" / "roadmap.md"
    if not roadmap_path.exists():
        return False

    content = read_text_sync(roadmap_path)

    # Pattern: - [STATE] slug where STATE is space, ., >, or x
    pattern = re.compile(rf"^(- \[)[ .>x](\] {re.escape(slug)})(\s|$)", re.MULTILINE)
    new_content, count = pattern.subn(rf"\g<1>{new_state}\g<2>\g<3>", content)

    if count == 0:
        return False

    write_text_sync(roadmap_path, new_content)

    return True


# =============================================================================
# Dependency Management (R4, R5, R6)
# =============================================================================


def read_dependencies(cwd: str) -> dict[str, list[str]]:
    """Read dependency graph from todos/dependencies.json.

    Returns:
        Dict mapping slug to list of slugs it depends on.
        Empty dict if file doesn't exist.
    """
    deps_path = Path(cwd) / "todos" / "dependencies.json"
    if not deps_path.exists():
        return {}

    content = read_text_sync(deps_path)
    result: dict[str, list[str]] = json.loads(content)
    return result


def write_dependencies(cwd: str, deps: dict[str, list[str]]) -> None:
    """Write dependency graph to todos/dependencies.json.

    Args:
        cwd: Project root directory
        deps: Dependency graph to write
    """
    deps_path = Path(cwd) / "todos" / "dependencies.json"

    # Remove empty lists to keep file clean
    deps = {k: v for k, v in deps.items() if v}

    if not deps:
        # If no dependencies, remove file if it exists
        if deps_path.exists():
            deps_path.unlink()
        return

    deps_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_sync(deps_path, json.dumps(deps, indent=2, sort_keys=True) + "\n")


def check_dependencies_satisfied(cwd: str, slug: str, deps: dict[str, list[str]]) -> bool:
    """Check if all dependencies for a slug are satisfied.

    A dependency is satisfied if:
    - It is marked [x] in roadmap.md, OR
    - It is not present in roadmap.md (assumed completed/removed)

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

    # Get all slugs currently in roadmap with their states
    roadmap_path = Path(cwd) / "todos" / "roadmap.md"
    if not roadmap_path.exists():
        return True  # No roadmap = no blocking

    content = read_text_sync(roadmap_path)
    pattern = re.compile(r"^- \[([x.> ])\] ([a-z0-9-]+)", re.MULTILINE)

    roadmap_items: dict[str, str] = {}
    for match in pattern.finditer(content):
        state, item_slug = match.groups()
        roadmap_items[item_slug] = state

    for dep in item_deps:
        if dep not in roadmap_items:
            # Not in roadmap - treat as satisfied (completed and cleaned up)
            continue

        dep_state = roadmap_items[dep]
        if dep_state != RoadmapMarker.DONE.value:
            # Dependency exists but not completed
            return False

    return True


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


def parse_impl_plan_done(cwd: str, slug: str) -> bool:
    """Check if implementation plan tasks are all done.

    Reads todos/{slug}/implementation-plan.md and checks for unchecked items.

    Supports two formats:
    1. Group-based: `## Group N` headers - only checks Groups 1-4
    2. Any other format - checks for ANY unchecked `- [ ]` items

    Returns:
        True if NO unchecked items found, False otherwise.
    """
    impl_plan_path = Path(cwd) / "todos" / slug / "implementation-plan.md"
    if not impl_plan_path.exists():
        return False

    content = read_text_sync(impl_plan_path)

    # Check if file uses Group-based format
    group_pattern = re.compile(r"^##\s+Group\s+(\d+)", re.MULTILINE)
    has_groups = bool(group_pattern.search(content))

    if has_groups:
        # Group-based format: only check Groups 1-4
        in_target_group = False
        for line in content.split("\n"):
            group_match = group_pattern.match(line)
            if group_match:
                group_num = int(group_match.group(1))
                in_target_group = 1 <= group_num <= 4

            if in_target_group and line.strip().startswith(UNCHECKED_TASK_MARKER):
                return False
    else:
        # Any other format: check for ANY unchecked items
        if UNCHECKED_TASK_MARKER in content:
            return False

    return True


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


async def get_available_agent(
    db: Db,
    task_type: str,
    fallback_matrix: dict[str, list[tuple[str, str]]],
) -> tuple[str, str]:
    """Get an available agent for the given task type.

    Checks agent availability and returns the first available agent from
    the fallback list. If all are unavailable, returns the one with the
    soonest unavailable_until time.

    Args:
        db: Database instance
        task_type: Type of task (e.g., "build", "review", "prepare")
        fallback_matrix: Mapping of task types to agent preference lists

    Returns:
        Tuple of (agent, thinking_mode)
    """
    # Clear expired availability first
    await db.clear_expired_agent_availability()

    fallback_list = fallback_matrix.get(task_type, [(AgentName.CLAUDE.value, ThinkingMode.MED.value)])
    soonest_unavailable: tuple[str, str, str | None] | None = None
    degraded_count = 0

    for agent, thinking_mode in fallback_list:
        availability = await db.get_agent_availability(agent)
        if availability is None:
            return agent, thinking_mode
        status = availability.get("status")
        if status == "degraded":
            degraded_count += 1
            continue
        if availability["available"]:
            return agent, thinking_mode

        # Track the soonest unavailable_until
        until = availability.get("unavailable_until")
        until_str = until if isinstance(until, str) else None
        if soonest_unavailable is None or (until_str and until_str < (soonest_unavailable[2] or "")):
            soonest_unavailable = (agent, thinking_mode, until_str)

    # All unavailable - return the one with soonest expiry
    if soonest_unavailable:
        return soonest_unavailable[0], soonest_unavailable[1]

    if degraded_count == len(fallback_list):
        raise RuntimeError(f"No selectable agents for task '{task_type}': all fallback candidates are degraded")

    # Fallback to first in list
    return fallback_list[0]


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

    Returns True when a copy happened, False when source was missing.
    """
    src = src_root / relative_path
    dst = dst_root / relative_path
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _sync_file_if_missing(src_root: Path, dst_root: Path, relative_path: str) -> bool:
    """Copy one file only when destination does not already exist."""
    src = src_root / relative_path
    dst = dst_root / relative_path
    if not src.exists() or dst.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def sync_main_to_worktree(cwd: str, slug: str, extra_files: list[str] | None = None) -> None:
    """Copy orchestrator-owned planning files from main repo into a slug worktree."""
    main_root = Path(cwd)
    worktree_root = Path(cwd) / "trees" / slug
    if not worktree_root.exists():
        return
    files = ["todos/roadmap.md", "todos/dependencies.json"]
    if extra_files:
        files.extend(extra_files)
    for rel in files:
        _sync_file(main_root, worktree_root, rel)


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
            f"{todo_base}/requirements.md",
            f"{todo_base}/implementation-plan.md",
            f"{todo_base}/state.json",
            f"{todo_base}/review-findings.md",
            f"{todo_base}/deferrals.md",
            f"{todo_base}/breakdown.md",
            f"{todo_base}/dor-report.md",
        ],
    )


def sync_slug_todo_from_main_to_worktree(cwd: str, slug: str) -> None:
    """Copy canonical todo artifacts for a slug from main into worktree."""
    todo_base = f"todos/{slug}"
    main_root = Path(cwd)
    worktree_root = Path(cwd) / "trees" / slug
    if not worktree_root.exists():
        return
    for rel in [
        f"{todo_base}/input.md",
        f"{todo_base}/requirements.md",
        f"{todo_base}/implementation-plan.md",
        f"{todo_base}/quality-checklist.md",
        f"{todo_base}/state.json",
        f"{todo_base}/review-findings.md",
        f"{todo_base}/deferrals.md",
        f"{todo_base}/breakdown.md",
        f"{todo_base}/dor-report.md",
    ]:
        _sync_file_if_missing(main_root, worktree_root, rel)


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
            "todos/roadmap.md",
            "todos/dependencies.json",
            f"todos/{slug}",
            f"todos/{slug}/",
        }
        for path in dirty_paths:
            normalized = path.replace("\\", "/")
            if normalized in ignored or normalized.startswith(f"todos/{slug}/"):
                continue
            if normalized not in ignored:
                return True
        return False
    except InvalidGitRepositoryError:
        logger.warning("Invalid git repository at %s", worktree_path)
        return False


def ensure_worktree(cwd: str, slug: str) -> bool:
    """Ensure worktree exists and is prepared, creating/preparing as needed.

    Creates: git worktree add trees/{slug} -b {slug}
    Then calls project-owned preparation hook to make worktree ready for work.

    Always runs preparation when worktree exists - this is safe because:
    - uv sync / pip install are idempotent (fast no-op if deps are current)
    - Catches any drift, new dependencies added mid-work, or partial installations
    - config.yml and .env symlink are also idempotent

    Args:
        cwd: Project root directory
        slug: Work item slug

    Returns:
        True if a new worktree was created, False if it already existed

    Raises:
        RuntimeError: If preparation hook not found or fails
    """
    worktree_path = Path(cwd) / "trees" / slug
    if worktree_path.exists():
        # Always run preparation - it's idempotent and catches any drift
        logger.info("Worktree %s exists, ensuring preparation is current", slug)
        _prepare_worktree(cwd, slug)
        return False

    try:
        repo = Repo(cwd)
        # Ensure trees directory exists
        trees_dir = Path(cwd) / "trees"
        trees_dir.mkdir(exist_ok=True)

        # Create worktree with new branch
        repo.git.worktree("add", str(worktree_path), "-b", slug)
        logger.info("Created worktree at %s", worktree_path)

        # Call preparation hook to make worktree ready for work
        _prepare_worktree(cwd, slug)

        return True
    except InvalidGitRepositoryError:
        logger.error("Cannot create worktree: %s is not a git repository", cwd)
        raise


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


def is_main_ahead(cwd: str, slug: str) -> bool:
    """Check if local main has commits not in the worktree branch.

    Args:
        cwd: Project root directory
        slug: Work item slug (worktree is at trees/{slug})

    Returns:
        True if main is ahead of HEAD for the worktree, False otherwise.
    """
    worktree_path = Path(cwd) / "trees" / slug
    if not worktree_path.exists():
        return False

    try:
        repo = Repo(worktree_path)
        ahead_count_raw = repo.git.rev_list("--count", "HEAD..main")  # type: ignore[misc]
        ahead_count = cast(str, ahead_count_raw).strip()
        return int(ahead_count) > 0
    except (InvalidGitRepositoryError, GitCommandError, ValueError):
        logger.warning("Cannot determine main ahead status for %s", worktree_path)
        return False


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
    retry_call = f'teleclaude__next_prepare(slug="{slug}")' if slug else "teleclaude__next_prepare()"
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
            agent, mode = await get_available_agent(db, "prepare", PREPARE_FALLBACK)
            return format_tool_call(
                command="next-prepare-draft",
                args="",
                project=cwd,
                agent=agent,
                thinking_mode=mode,
                subfolder="",
                note="No active preparation work found.",
                next_call="teleclaude__next_prepare",
            )

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
            note = f"Preparing: {resolved_slug}. This slug is not in todos/roadmap.md. {next_step}"
            if hitl:
                return format_hitl_guidance(note)

            agent, mode = await get_available_agent(db, "prepare", PREPARE_FALLBACK)
            return format_tool_call(
                command="next-prepare-draft",
                args=resolved_slug,
                project=cwd,
                agent=agent,
                thinking_mode=mode,
                subfolder="",
                note=note,
                next_call="teleclaude__next_prepare",
            )

        # 1.6. Check for breakdown assessment
        has_input = check_file_exists(cwd, f"todos/{resolved_slug}/input.md")
        breakdown_state = await asyncio.to_thread(read_breakdown_state, cwd, resolved_slug)

        if has_input and (breakdown_state is None or not breakdown_state.get("assessed")):
            # Breakdown assessment needed
            if hitl:
                return format_hitl_guidance(
                    f"Preparing: {resolved_slug}. Read todos/{resolved_slug}/input.md and assess "
                    "Definition of Ready. If complex, split into smaller todos. Then update state.json "
                    "and create breakdown.md."
                )
            # Non-HITL: dispatch architect to assess
            agent, mode = await get_available_agent(db, "prepare", PREPARE_FALLBACK)
            return format_tool_call(
                command="next-prepare-draft",
                args=resolved_slug,
                project=cwd,
                agent=agent,
                thinking_mode=mode,
                subfolder="",
                note=f"Assess todos/{resolved_slug}/input.md for complexity. Split if needed.",
                next_call="teleclaude__next_prepare",
            )

        # If breakdown assessed and has dependent todos, this one is a container
        if breakdown_state and breakdown_state.get("todos"):
            dep_todos = breakdown_state["todos"]
            if isinstance(dep_todos, list):
                return f"CONTAINER: {resolved_slug} was split into: {', '.join(dep_todos)}. Work on those first."
            return f"CONTAINER: {resolved_slug} was split. Check state.json for dependent todos."

        # 2. Check requirements
        if not check_file_exists(cwd, f"todos/{resolved_slug}/requirements.md"):
            if hitl:
                return format_hitl_guidance(
                    f"Preparing: {resolved_slug}. Write todos/{resolved_slug}/requirements.md "
                    f"and todos/{resolved_slug}/implementation-plan.md yourself."
                )

            agent, mode = await get_available_agent(db, "prepare", PREPARE_FALLBACK)
            return format_tool_call(
                command="next-prepare-draft",
                args=resolved_slug,
                project=cwd,
                agent=agent,
                thinking_mode=mode,
                subfolder="",
                note=f"Discuss until you have enough input. Write todos/{resolved_slug}/requirements.md yourself.",
                next_call="teleclaude__next_prepare",
            )

        # 3. Check implementation plan
        if not check_file_exists(cwd, f"todos/{resolved_slug}/implementation-plan.md"):
            if hitl:
                return format_hitl_guidance(
                    f"Preparing: {resolved_slug}. Write todos/{resolved_slug}/implementation-plan.md yourself."
                )

            agent, mode = await get_available_agent(db, "prepare", PREPARE_FALLBACK)
            return format_tool_call(
                command="next-prepare-draft",
                args=resolved_slug,
                project=cwd,
                agent=agent,
                thinking_mode=mode,
                subfolder="",
                note=f"Discuss until you have enough input. Write todos/{resolved_slug}/implementation-plan.md yourself.",
                next_call="teleclaude__next_prepare",
            )

        # 4. Both exist - mark as ready only after DOR pass (avoid downgrading [>] or [x])
        current_state = await asyncio.to_thread(get_roadmap_state, cwd, resolved_slug)
        if current_state == RoadmapMarker.PENDING.value:  # Only transition pending -> ready
            phase_state = await asyncio.to_thread(read_phase_state, cwd, resolved_slug)
            dor = phase_state.get("dor")
            dor_status = dor.get("status") if isinstance(dor, dict) else None
            dor_status_str = dor_status if isinstance(dor_status, str) else None
            if dor_status_str == "pass":
                await asyncio.to_thread(update_roadmap_state, cwd, resolved_slug, RoadmapMarker.READY.value)
                await asyncio.to_thread(sync_main_to_worktree, cwd, resolved_slug)
            else:
                if hitl:
                    return format_hitl_guidance(
                        f"Preparing: {resolved_slug}. Requirements and implementation plan exist, "
                        "but DOR is not pass yet. Complete DOR assessment, update "
                        f"todos/{resolved_slug}/dor-report.md and todos/{resolved_slug}/state.json.dor "
                        'with status "pass". Then run /next-prepare-gate (separate worker) and call teleclaude__next_prepare again.'
                    )

                agent, mode = await get_available_agent(db, "prepare", PREPARE_FALLBACK)
                return format_tool_call(
                    command="next-prepare-gate",
                    args=resolved_slug,
                    project=cwd,
                    agent=agent,
                    thinking_mode=mode,
                    subfolder="",
                    note=(
                        f"Requirements/plan exist for {resolved_slug}, but DOR status is not pass. "
                        "Complete DOR assessment and set state.json.dor.status to pass."
                    ),
                    next_call="teleclaude__next_prepare",
                )
        # else: already [.], [>], or [x] - no state change needed
        return format_prepared(resolved_slug)
    except RuntimeError as exc:
        task_type = _extract_no_selectable_task_type(str(exc))
        if task_type:
            return format_agent_selection_error(task_type, retry_call)
        raise


async def next_work(db: Db, slug: str | None, cwd: str) -> str:
    """Phase B state machine for deterministic builder work.

    Executes the build/review/fix/finalize cycle on prepared work items.
    Only considers [.] items (ready) with satisfied dependencies.

    Args:
        db: Database instance
        slug: Optional explicit slug (resolved from roadmap if not provided)
        cwd: Current working directory (project root)

    Returns:
        Plain text instructions for the orchestrator to execute
    """
    retry_call = f'teleclaude__next_work(slug="{slug}")' if slug else "teleclaude__next_work()"

    async def _pick_agent(task_type: str) -> tuple[str, str] | str:
        try:
            return await get_available_agent(db, task_type, WORK_FALLBACK)
        except RuntimeError as exc:
            task = _extract_no_selectable_task_type(str(exc))
            if task:
                return format_agent_selection_error(task, retry_call)
            raise

    # 1. Resolve slug - only ready items when no explicit slug
    # Prefer worktree-local planning state when explicit slug worktree exists.
    deps_cwd = cwd
    if slug:
        maybe_worktree = Path(cwd) / "trees" / slug
        if (maybe_worktree / "todos" / "dependencies.json").exists():
            deps_cwd = str(maybe_worktree)
    deps = await asyncio.to_thread(read_dependencies, deps_cwd)

    resolved_slug: str
    if slug:
        # Explicit slug provided - verify it's in ready state and dependencies satisfied
        # Read roadmap to check state
        roadmap_root = Path(cwd)
        maybe_worktree = Path(cwd) / "trees" / slug
        if (maybe_worktree / "todos" / "roadmap.md").exists():
            roadmap_root = maybe_worktree
        roadmap_path = roadmap_root / "todos" / "roadmap.md"
        if not roadmap_path.exists():
            return format_error(
                "NOT_PREPARED",
                f"Item '{slug}' not found: roadmap doesn't exist.",
                next_call="Call teleclaude__next_prepare() to create roadmap first.",
            )

        content = await read_text_async(roadmap_path)
        # Match the slug and extract its state
        pattern = re.compile(rf"^-\s+\[([ .>])\]\s+{re.escape(slug)}\b", re.MULTILINE)
        match = pattern.search(content)

        if not match:
            return format_error(
                "NOT_PREPARED",
                f"Item '{slug}' not found in roadmap.",
                next_call="Check todos/roadmap.md or call teleclaude__next_prepare().",
            )

        state: str = match.group(1)
        if state == RoadmapMarker.PENDING.value:
            # Item is [ ] (pending) - not prepared yet
            return format_error(
                "ITEM_NOT_READY",
                f"Item '{slug}' is [ ] (pending). Must be [.] (ready) to start work.",
                next_call=f"Call teleclaude__next_prepare(slug='{slug}') to prepare it first.",
            )

        # Item is [.] or [>] - check dependencies
        if not await asyncio.to_thread(check_dependencies_satisfied, str(roadmap_root), slug, deps):
            return format_error(
                "DEPS_UNSATISFIED",
                f"Item '{slug}' has unsatisfied dependencies.",
                next_call="Complete dependency items first, or check todos/dependencies.json.",
            )
        resolved_slug = slug
    else:
        # R6: Use resolve_slug with dependency gating
        found_slug, _, _ = await resolve_slug_async(cwd, None, True, deps)

        if not found_slug:
            # Check if there are [.] items (without dependency gating) to provide better error
            has_ready_items, _, _ = await resolve_slug_async(cwd, None, True)

            if has_ready_items:
                return format_error(
                    "DEPS_UNSATISFIED",
                    "Ready items exist but all have unsatisfied dependencies.",
                    next_call="Complete dependency items first, or check todos/dependencies.json.",
                )
            return format_error(
                "NO_READY_ITEMS",
                "No [.] (ready) items found in roadmap.",
                next_call="Call teleclaude__next_prepare() to prepare items first.",
            )
        resolved_slug = found_slug

    # 2. Validate preconditions
    precondition_root = cwd
    worktree_path = Path(cwd) / "trees" / resolved_slug
    if (
        worktree_path.exists()
        and (worktree_path / "todos" / resolved_slug / "requirements.md").exists()
        and (worktree_path / "todos" / resolved_slug / "implementation-plan.md").exists()
    ):
        precondition_root = str(worktree_path)
    has_requirements = check_file_exists(precondition_root, f"todos/{resolved_slug}/requirements.md")
    has_impl_plan = check_file_exists(precondition_root, f"todos/{resolved_slug}/implementation-plan.md")
    if not (has_requirements and has_impl_plan):
        return format_error(
            "NOT_PREPARED",
            f"todos/{resolved_slug} is missing requirements or implementation plan.",
            next_call=f'Call teleclaude__next_prepare(slug="{resolved_slug}") to complete preparation.',
        )

    # 4. Ensure worktree exists
    try:
        worktree_created = await ensure_worktree_async(cwd, resolved_slug)
        if worktree_created:
            logger.info("Created new worktree for %s", resolved_slug)
    except RuntimeError as exc:
        return format_error(
            "WORKTREE_PREP_FAILED",
            str(exc),
            next_call="Add tools/worktree-prepare.sh or fix its execution, then retry.",
        )

    worktree_cwd = str(Path(cwd) / "trees" / resolved_slug)

    # Bootstrap worktree from main only when it is first created.
    if worktree_created:
        await asyncio.to_thread(sync_main_to_worktree, cwd, resolved_slug)
        await asyncio.to_thread(sync_slug_todo_from_main_to_worktree, cwd, resolved_slug)

    # 5. Check uncommitted changes
    if has_uncommitted_changes(cwd, resolved_slug):
        return format_uncommitted_changes(resolved_slug)

    # 6. Mark as in-progress in worktree BEFORE dispatching (claim the item)
    # Only mark if currently [.] (not already [>]) in worktree roadmap.
    roadmap_path = Path(worktree_cwd) / "todos" / "roadmap.md"
    if roadmap_path.exists():
        content = await read_text_async(roadmap_path)
        if f"[.] {resolved_slug}" in content:
            await asyncio.to_thread(update_roadmap_state, worktree_cwd, resolved_slug, ">")

    # 7. Check build status (from state.json in worktree)
    if not await asyncio.to_thread(is_build_complete, worktree_cwd, resolved_slug):
        selection = await _pick_agent(PhaseName.BUILD.value)
        if isinstance(selection, str):
            return selection
        agent, mode = selection
        return format_tool_call(
            command="next-build",
            args=resolved_slug,
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder=f"trees/{resolved_slug}",
            next_call=f'teleclaude__next_work(slug="{resolved_slug}")',
        )

    # 8. Check review status
    if not await asyncio.to_thread(is_review_approved, worktree_cwd, resolved_slug):
        # Check if review hasn't started yet or needs fixes
        if await asyncio.to_thread(is_review_changes_requested, worktree_cwd, resolved_slug):
            selection = await _pick_agent("fix")
            if isinstance(selection, str):
                return selection
            agent, mode = selection
            return format_tool_call(
                command="next-fix-review",
                args=resolved_slug,
                project=cwd,
                agent=agent,
                thinking_mode=mode,
                subfolder=f"trees/{resolved_slug}",
                next_call=f'teleclaude__next_work(slug="{resolved_slug}")',
            )
        # Review not started or still pending
        limit_reached, current_round, max_rounds = _is_review_round_limit_reached(worktree_cwd, resolved_slug)
        if limit_reached:
            return format_error(
                "REVIEW_ROUND_LIMIT",
                (
                    f"Review rounds exceeded for {resolved_slug}: "
                    f"current={current_round}, max={max_rounds}. Human decision required."
                ),
                next_call=f'Resolve findings manually, then call teleclaude__next_work(slug="{resolved_slug}")',
            )
        selection = await _pick_agent(PhaseName.REVIEW.value)
        if isinstance(selection, str):
            return selection
        agent, mode = selection
        return format_tool_call(
            command="next-review",
            args=resolved_slug,
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder=f"trees/{resolved_slug}",
            next_call=f'teleclaude__next_work(slug="{resolved_slug}")',
            note=f"{REVIEW_DIFF_NOTE}\n\n{_review_scope_note(worktree_cwd, resolved_slug)}",
        )

    # 8.5 Check pending deferrals (R7)
    if await asyncio.to_thread(has_pending_deferrals, worktree_cwd, resolved_slug):
        selection = await _pick_agent("defer")
        if isinstance(selection, str):
            return selection
        agent, mode = selection
        return format_tool_call(
            command="next-defer",
            args=resolved_slug,
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder=f"trees/{resolved_slug}",
            next_call=f'teleclaude__next_work(slug="{resolved_slug}")',
        )

    # 9. Review approved - dispatch finalize
    if has_uncommitted_changes(cwd, resolved_slug):
        return format_uncommitted_changes(resolved_slug)
    selection = await _pick_agent("finalize")
    if isinstance(selection, str):
        return selection
    agent, mode = selection
    return format_tool_call(
        command="next-finalize",
        args=resolved_slug,
        project=cwd,
        agent=agent,
        thinking_mode=mode,
        subfolder="",  # Empty = main repo, NOT worktree
        next_call="teleclaude__next_work()",
    )
