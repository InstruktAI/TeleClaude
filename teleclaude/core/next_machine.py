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
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal, Mapping, cast

from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError
from instrukt_ai_logging import get_logger

from teleclaude.core.db import Db
from teleclaude.core.session_utils import parse_session_title

logger = get_logger(__name__)

# Fallback matrices: task_type -> [(agent, thinking_mode), ...]
PREPARE_FALLBACK: dict[str, list[tuple[str, str]]] = {
    "prepare": [("claude", "slow"), ("codex", "slow"), ("gemini", "slow")],
}

WORK_FALLBACK: dict[str, list[tuple[str, str]]] = {
    "bugs": [("codex", "med"), ("claude", "med"), ("gemini", "med")],
    "build": [("gemini", "med"), ("claude", "med"), ("codex", "med")],
    "review": [("codex", "slow"), ("claude", "slow"), ("gemini", "slow")],
    "fix": [("claude", "med"), ("gemini", "med"), ("codex", "med")],
    "finalize": [("claude", "med"), ("gemini", "med"), ("codex", "med")],
    "defer": [("claude", "med"), ("gemini", "med"), ("codex", "med")],
}

# Post-completion instructions for each command (used in format_tool_call)
# These tell the orchestrator what to do AFTER a worker completes
POST_COMPLETION: dict[str, str] = {
    "next-bugs": """WHEN WORKER COMPLETES:
1. Verify bugs fixed and tests pass
2. If success:
   - teleclaude__end_session(computer="local", session_id="<session_id>")
   - Call {next_call}
3. If bugs remain or tests fail:
   - Keep session alive and guide worker to resolution
""",
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
1. Verify merge and archive succeeded
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
) -> str:
    """Format a literal tool call for the orchestrator to execute."""
    # Codex requires /prompts: prefix for custom commands
    agent_key = agent.strip().lower()
    formatted_command = f"/prompts:{command}" if agent_key.startswith("codex") else command

    # Get post-completion instructions for this command
    post_completion = POST_COMPLETION.get(command, "")
    if post_completion:
        next_call_display = next_call.strip()
        if next_call_display and "(" not in next_call_display:
            next_call_display = f"{next_call_display}()"
        # Substitute {args} and {next_call} placeholders
        post_completion = post_completion.format(args=args, next_call=next_call_display)

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


def format_prepared(slug: str) -> str:
    """Format a 'prepared' message indicating work item is ready."""
    return f"""PREPARED: todos/{slug} is ready for work.

ASK USER: Do you want to continue with more preparation work, or start the build/review cycle with teleclaude__next_work(slug="{slug}")?"""


def format_complete(slug: str, archive_path: str) -> str:
    """Format a 'complete' message indicating work item is finalized."""
    return f"""COMPLETE: todos/{slug} has been finalized and delivered to {archive_path}/

NEXT: Call teleclaude__next_work() to continue with more work."""


def format_uncommitted_changes(slug: str) -> str:
    """Format instruction for orchestrator to commit uncommitted changes directly."""
    return f"""UNCOMMITTED CHANGES in trees/{slug}

NEXT: Commit these changes intelligently, then call teleclaude__next_work(slug="{slug}") to continue."""


def format_hitl_guidance(context: str) -> str:
    """Format guidance for the calling AI to work interactively with the user.

    Used when HITL=True.
    """
    return f"""Before proceeding, read ~/.agents/commands/next-prepare.md if you haven't already.

{context}"""


def _slugify(value: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return base or "input"


def _ensure_unique_slug(cwd: str, base: str) -> str:
    slug = base
    counter = 2
    while (Path(cwd) / "todos" / slug).exists() or slug_in_roadmap(cwd, slug):
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def _insert_roadmap_item(cwd: str, slug: str) -> None:
    roadmap_path = Path(cwd) / "todos" / "roadmap.md"
    if not roadmap_path.exists():
        return
    content = read_text_sync(roadmap_path)
    if re.search(rf"^- \[[ .>x]\] {re.escape(slug)}(\s|$)", content, re.MULTILINE):
        return
    insert_at = content.find("\n## ")
    if insert_at == -1:
        updated = content.rstrip() + f"\n- [ ] {slug}\n"
    else:
        updated = content[:insert_at] + f"\n- [ ] {slug}\n" + content[insert_at:]
    write_text_sync(roadmap_path, updated)


async def _create_input_todo_from_latest_session(db: Db, cwd: str) -> tuple[str | None, str]:
    sessions = await db.get_active_sessions()
    if not sessions:
        return None, "No active sessions found to capture input."
    session = sessions[0]
    _, description = parse_session_title(session.title or "")
    base = _slugify(description or "input")
    slug = await asyncio.to_thread(_ensure_unique_slug, cwd, base)

    todo_dir = Path(cwd) / "todos" / slug
    todo_dir.mkdir(parents=True, exist_ok=True)

    captured_at = datetime.now().isoformat(timespec="seconds")
    user_text = session.last_message_sent or "No recent user input captured."
    ai_text = session.last_feedback_received or "No recent assistant output captured."

    input_body = (
        f"# Input: {slug}\n\n"
        "## Source\n"
        f"- session_id: {session.session_id}\n"
        f"- title: {session.title}\n"
        f"- captured_at: {captured_at}\n\n"
        "## User Input (latest)\n"
        f"{user_text}\n\n"
        "## Assistant Output (latest)\n"
        f"{ai_text}\n"
    )
    await write_text_async(todo_dir / "input.md", input_body)

    await asyncio.to_thread(_insert_roadmap_item, cwd, slug)

    try:
        repo = Repo(cwd)
        configure_git_env(repo, cwd)
        repo.index.add([f"todos/{slug}/input.md", "todos/roadmap.md"])
        repo.index.commit(f"todo({slug}): capture input")
    except InvalidGitRepositoryError:
        logger.warning("Cannot commit new input todo: %s is not a git repository", cwd)

    return slug, "Created input.md from latest session."


# =============================================================================
# Shared Helper Functions
# =============================================================================


# Valid phases and statuses for state.json
Phase = Literal["build", "review"]
PhaseStatus = Literal["pending", "complete", "approved", "changes_requested"]

DEFAULT_STATE: dict[str, str | bool | dict[str, bool | list[str]]] = {
    "build": "pending",
    "review": "pending",
    "deferrals_processed": False,
    "breakdown": {"assessed": False, "todos": []},
}


def get_state_path(cwd: str, slug: str) -> Path:
    """Get path to state.json in worktree."""
    return Path(cwd) / "todos" / slug / "state.json"


def read_phase_state(cwd: str, slug: str) -> dict[str, str | bool | dict[str, bool | list[str]]]:
    """Read state.json from worktree.

    Returns default state if file doesn't exist.
    """
    state_path = get_state_path(cwd, slug)
    if not state_path.exists():
        return DEFAULT_STATE.copy()

    content = read_text_sync(state_path)
    state: dict[str, str | bool | dict[str, bool | list[str]]] = json.loads(content)
    # Merge with defaults for any missing keys
    return {**DEFAULT_STATE, **state}


def write_phase_state(cwd: str, slug: str, state: dict[str, str | bool | dict[str, bool | list[str]]]) -> None:
    """Write state.json and commit to git."""
    state_path = get_state_path(cwd, slug)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_sync(state_path, json.dumps(state, indent=2) + "\n")

    # Commit the state change
    try:
        repo = Repo(cwd)
        configure_git_env(repo, cwd)
        relative_path = state_path.relative_to(cwd)
        repo.index.add([str(relative_path)])
        # Create descriptive commit message
        phases_done = [p for p, s in state.items() if isinstance(s, str) and s in ("complete", "approved")]
        msg = f"state({slug}): {', '.join(phases_done) if phases_done else 'init'}"
        repo.index.commit(msg)
        logger.info("Committed state update for %s", slug)
    except InvalidGitRepositoryError:
        logger.warning("Cannot commit state: %s is not a git repository", cwd)


def mark_phase(cwd: str, slug: str, phase: str, status: str) -> dict[str, str | bool | dict[str, bool | list[str]]]:
    """Mark a phase with a status and commit.

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
    write_phase_state(cwd, slug, state)
    return state


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
    """Write breakdown state and commit.

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
    build = state.get("build")
    return isinstance(build, str) and build == "complete"


def is_review_approved(cwd: str, slug: str) -> bool:
    """Check if review phase is approved."""
    state = read_phase_state(cwd, slug)
    review = state.get("review")
    return isinstance(review, str) and review == "approved"


def is_review_changes_requested(cwd: str, slug: str) -> bool:
    """Check if review requested changes."""
    state = read_phase_state(cwd, slug)
    review = state.get("review")
    return isinstance(review, str) and review == "changes_requested"


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


def has_pending_bugs(cwd: str) -> bool:
    """Check if todos/bugs.md has unchecked items.

    Returns:
        True if bugs.md exists and contains unchecked checkboxes ([ ]).
    """
    bugs_path = Path(cwd) / "todos" / "bugs.md"
    if not bugs_path.exists():
        return False
    content = read_text_sync(bugs_path)
    return "[ ]" in content


def get_archive_path(cwd: str, slug: str) -> str | None:
    """Check if done/*-{slug}/ directory exists.

    Returns the archive path (e.g., "done/005-my-slug") if found, None otherwise.
    """
    done_dir = Path(cwd) / "done"
    if not done_dir.exists():
        return None
    for entry in done_dir.iterdir():
        if entry.is_dir() and entry.name.endswith(f"-{slug}"):
            return f"done/{entry.name}"
    return None


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
        - Commits the change to git with descriptive message
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

    # Commit the state change
    try:
        repo = Repo(cwd)
        configure_git_env(repo, cwd)
        repo.index.add(["todos/roadmap.md"])
        state_names = {" ": "pending", ".": "ready", ">": "in-progress", "x": "done"}
        msg = f"roadmap({slug}): mark {state_names.get(new_state, new_state)}"
        repo.index.commit(msg)
        logger.info("Updated roadmap state for %s to %s", slug, new_state)
    except InvalidGitRepositoryError:
        logger.warning("Cannot commit roadmap update: %s is not a git repository", cwd)

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
    """Write dependency graph to todos/dependencies.json and commit.

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
            try:
                repo = Repo(cwd)
                configure_git_env(repo, cwd)
                repo.index.remove(["todos/dependencies.json"])  # type: ignore[misc]
                repo.index.commit("deps: remove empty dependencies.json")
            except InvalidGitRepositoryError:
                pass
        return

    deps_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_sync(deps_path, json.dumps(deps, indent=2, sort_keys=True) + "\n")

    try:
        repo = Repo(cwd)
        configure_git_env(repo, cwd)
        repo.index.add(["todos/dependencies.json"])
        repo.index.commit("deps: update dependencies.json")
        logger.info("Updated dependencies.json")
    except InvalidGitRepositoryError:
        logger.warning("Cannot commit dependencies update: %s is not a git repository", cwd)


def check_dependencies_satisfied(cwd: str, slug: str, deps: dict[str, list[str]]) -> bool:
    """Check if all dependencies for a slug are satisfied.

    A dependency is satisfied if:
    - It is marked [x] in roadmap.md, OR
    - It is not present in roadmap.md (assumed completed/archived), OR
    - It exists in done/*-{dep}/ directory

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

        # Check if dependency is archived (done/*-dep exists)
        if get_archive_path(cwd, dep):
            # Archived = completed, even if still in roadmap
            continue

        dep_state = roadmap_items[dep]
        if dep_state != "x":
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

            if in_target_group and line.strip().startswith("- [ ]"):
                return False
    else:
        # Any other format: check for ANY unchecked items
        if "- [ ]" in content:
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
    if "[x] APPROVE" in content:
        return "approved"
    return "changes_requested"


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

    fallback_list = fallback_matrix.get(task_type, [("claude", "med")])
    soonest_unavailable: tuple[str, str, str | None] | None = None

    for agent, thinking_mode in fallback_list:
        availability = await db.get_agent_availability(agent)
        if availability is None or availability["available"]:
            return agent, thinking_mode

        # Track the soonest unavailable_until
        until = availability.get("unavailable_until")
        until_str = until if isinstance(until, str) else None
        if soonest_unavailable is None or (until_str and until_str < (soonest_unavailable[2] or "")):
            soonest_unavailable = (agent, thinking_mode, until_str)

    # All unavailable - return the one with soonest expiry
    if soonest_unavailable:
        return soonest_unavailable[0], soonest_unavailable[1]

    # Fallback to first in list
    return fallback_list[0]


# =============================================================================
# Git Operations
# =============================================================================


def build_git_hook_env(cwd: str, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build env vars so git hooks resolve repo-local venv tools."""
    env = dict(base_env or os.environ)
    path_raw = env.get("PATH", "")
    venv_bin = str(Path(cwd) / ".venv" / "bin")

    path_parts = [p for p in path_raw.split(os.pathsep) if p and p != venv_bin]
    path_parts.insert(0, venv_bin)
    return {
        "PATH": os.pathsep.join(path_parts),
        "VIRTUAL_ENV": str(Path(cwd) / ".venv"),
    }


def configure_git_env(repo: Repo, cwd: str) -> None:
    """Ensure git commands run with repo-local venv tools available."""
    env = build_git_hook_env(cwd)
    repo.git.update_environment(**env)


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


def has_uncommitted_changes(cwd: str, slug: str) -> bool:
    """Check if worktree has uncommitted changes.

    Args:
        cwd: Project root directory
        slug: Work item slug (worktree is at trees/{slug})

    Returns:
        True if there are uncommitted changes (staged or unstaged)
    """
    worktree_path = Path(cwd) / "trees" / slug
    if not worktree_path.exists():
        return False

    try:
        repo = Repo(worktree_path)
        return repo.is_dirty(untracked_files=True)
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
    """Call project-owned preparation hook to prepare worktree.

    Detects project type (Makefile or package.json) and calls appropriate hook:
    - Python/Makefile: make worktree-prepare SLUG={slug}
    - Node/package.json: npm run worktree:prepare -- {slug}

    Args:
        cwd: Project root directory (main repo)
        slug: Work item slug

    Raises:
        RuntimeError: If hook not found or execution fails
    """
    cwd_path = Path(cwd)

    # Check for Makefile
    makefile = cwd_path / "Makefile"
    if makefile.exists():
        # Verify worktree-prepare target exists
        try:
            subprocess.run(
                ["make", "-n", "worktree-prepare"],
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            msg = "make command not found. Install make to use Makefile-based worktree preparation."
            logger.error(msg)
            raise RuntimeError(msg) from None
        except subprocess.CalledProcessError:
            msg = f"Makefile exists but 'worktree-prepare' target not found in {cwd}"
            logger.error(msg)
            raise RuntimeError(msg) from None

        # Call preparation hook
        logger.info("Preparing worktree with: make worktree-prepare SLUG=%s", slug)
        try:
            result = subprocess.run(
                ["make", "worktree-prepare", f"SLUG={slug}"],
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("Worktree preparation output:\n%s", result.stdout)
        except subprocess.CalledProcessError as e:
            stdout_str = str(e.stdout) if e.stdout is not None else ""  # type: ignore[misc]
            stderr_str = str(e.stderr) if e.stderr is not None else ""  # type: ignore[misc]
            msg = (
                f"Worktree preparation failed for {slug}:\n"
                f"Command: make worktree-prepare SLUG={slug}\n"
                f"Exit code: {e.returncode}\n"
                f"stdout: {stdout_str}\n"
                f"stderr: {stderr_str}"
            )
            logger.error(msg)
            raise RuntimeError(msg) from e
        return

    # Check for package.json
    package_json = cwd_path / "package.json"
    if package_json.exists():
        # Parse JSON and verify worktree:prepare script exists
        try:
            with open(package_json, "r", encoding="utf-8") as f:
                data: dict[str, dict[str, str]] = json.load(f)
            if "scripts" not in data or "worktree:prepare" not in data["scripts"]:
                msg = f"package.json exists but 'worktree:prepare' script not found in {cwd}"
                logger.error(msg)
                raise RuntimeError(msg)
        except (json.JSONDecodeError, KeyError) as e:
            msg = f"Failed to parse package.json in {cwd}"
            logger.error(msg)
            raise RuntimeError(msg) from e

        # Call preparation hook
        logger.info("Preparing worktree with: npm run worktree:prepare -- %s", slug)
        try:
            result = subprocess.run(
                ["npm", "run", "worktree:prepare", "--", slug],
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("Worktree preparation output:\n%s", result.stdout)
        except FileNotFoundError:
            msg = "npm command not found. Install Node.js/npm to use package.json-based worktree preparation."
            logger.error(msg)
            raise RuntimeError(msg) from None
        except subprocess.CalledProcessError as e:
            stdout_str = str(e.stdout) if e.stdout is not None else ""  # type: ignore[misc]
            stderr_str = str(e.stderr) if e.stderr is not None else ""  # type: ignore[misc]
            msg = (
                f"Worktree preparation failed for {slug}:\n"
                f"Command: npm run worktree:prepare -- {slug}\n"
                f"Exit code: {e.returncode}\n"
                f"stdout: {stdout_str}\n"
                f"stderr: {stderr_str}"
            )
            logger.error(msg)
            raise RuntimeError(msg) from e
        return

    # No preparation hook found
    msg = (
        f"No worktree preparation hook found in {cwd}. "
        f"Expected either:\n"
        f"  - Makefile with 'worktree-prepare' target\n"
        f"  - package.json with 'worktree:prepare' script"
    )
    logger.error(msg)
    raise RuntimeError(msg)


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
    # 1. Resolve slug
    resolved_slug = slug

    if resolved_slug == "input":
        created_slug, note = await _create_input_todo_from_latest_session(db, cwd)
        if created_slug:
            return format_hitl_guidance(
                f"Captured discussion into todos/{created_slug}/input.md. "
                f'Next: call teleclaude__next_prepare(slug="{created_slug}").'
            )
        return format_hitl_guidance(f"Input capture failed. {note}")

    if not slug and not hitl:
        resolved_slug, _, _ = await resolve_slug_async(cwd, None)

    if not resolved_slug:
        if hitl:
            return format_hitl_guidance(
                "Read todos/roadmap.md. Discuss with the user to identify or propose a "
                "work item slug. Once decided, write requirements.md and "
                "implementation-plan.md yourself and commit."
            )

        # Dispatch next-prepare (no slug) when hitl=False
        agent, mode = await get_available_agent(db, "prepare", PREPARE_FALLBACK)
        return format_tool_call(
            command="next-prepare",
            args="",
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder="",
            note="Roadmap is empty or no item selected. Groom the roadmap to add work items.",
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
        docs_clause = " and commit."
        if missing_docs:
            docs_list = " and ".join(missing_docs)
            docs_clause = f" before writing {docs_list} and commit."
        next_step = (
            "Discuss with the user where it should appear in the list and get approval, "
            f"then add it to the roadmap{docs_clause}"
        )
        note = f"Preparing: {resolved_slug}. This slug is not in todos/roadmap.md. {next_step}"
        if hitl:
            return format_hitl_guidance(note)

        agent, mode = await get_available_agent(db, "prepare", PREPARE_FALLBACK)
        return format_tool_call(
            command="next-prepare",
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
            command="next-prepare",
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
                f"and todos/{resolved_slug}/implementation-plan.md yourself and commit."
            )

        agent, mode = await get_available_agent(db, "prepare", PREPARE_FALLBACK)
        return format_tool_call(
            command="next-prepare",
            args=resolved_slug,
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder="",
            note=f"Discuss until you have enough input. Write todos/{resolved_slug}/requirements.md yourself and commit.",
            next_call="teleclaude__next_prepare",
        )

    # 3. Check implementation plan
    if not check_file_exists(cwd, f"todos/{resolved_slug}/implementation-plan.md"):
        if hitl:
            return format_hitl_guidance(
                f"Preparing: {resolved_slug}. Write todos/{resolved_slug}/implementation-plan.md yourself and commit."
            )

        agent, mode = await get_available_agent(db, "prepare", PREPARE_FALLBACK)
        return format_tool_call(
            command="next-prepare",
            args=resolved_slug,
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder="",
            note=f"Discuss until you have enough input. Write todos/{resolved_slug}/implementation-plan.md yourself and commit.",
            next_call="teleclaude__next_prepare",
        )

    # 4. Both exist - mark as ready if pending (avoid downgrading [>] or [x])
    current_state = await asyncio.to_thread(get_roadmap_state, cwd, resolved_slug)
    if current_state == " ":  # Only transition pending -> ready
        await asyncio.to_thread(update_roadmap_state, cwd, resolved_slug, ".")
    # else: already [.], [>], or [x] - no state change needed
    return format_prepared(resolved_slug)


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
    # 1. Resolve slug - only ready items when no explicit slug
    deps = await asyncio.to_thread(read_dependencies, cwd)

    resolved_slug: str
    if slug:
        # Explicit slug provided - verify it's in ready state and dependencies satisfied
        # Read roadmap to check state
        roadmap_path = Path(cwd) / "todos" / "roadmap.md"
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
        if state == " ":
            # Item is [ ] (pending) - not prepared yet
            return format_error(
                "ITEM_NOT_READY",
                f"Item '{slug}' is [ ] (pending). Must be [.] (ready) to start work.",
                next_call=f"Call teleclaude__next_prepare(slug='{slug}') to prepare it first.",
            )

        # Item is [.] or [>] - check dependencies
        if not await asyncio.to_thread(check_dependencies_satisfied, cwd, slug, deps):
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

    # 2. Check if already finalized
    archive_path = get_archive_path(cwd, resolved_slug)
    if archive_path:
        return format_complete(resolved_slug, archive_path)

    # 3. Validate preconditions
    has_requirements = check_file_exists(cwd, f"todos/{resolved_slug}/requirements.md")
    has_impl_plan = check_file_exists(cwd, f"todos/{resolved_slug}/implementation-plan.md")
    if not (has_requirements and has_impl_plan):
        return format_error(
            "NOT_PREPARED",
            f"todos/{resolved_slug} is missing requirements or implementation plan.",
            next_call=f'Call teleclaude__next_prepare(slug="{resolved_slug}") to complete preparation.',
        )

    # 4. Ensure worktree exists
    worktree_created = await ensure_worktree_async(cwd, resolved_slug)
    if worktree_created:
        logger.info("Created new worktree for %s", resolved_slug)

    worktree_cwd = str(Path(cwd) / "trees" / resolved_slug)

    # 5. Check uncommitted changes
    if has_uncommitted_changes(cwd, resolved_slug):
        return format_uncommitted_changes(resolved_slug)

    # 6. Mark as in-progress BEFORE dispatching (claim the item)
    # Only mark if currently [.] (not already [>])
    roadmap_path = Path(cwd) / "todos" / "roadmap.md"
    if roadmap_path.exists():
        content = await read_text_async(roadmap_path)
        if f"[.] {resolved_slug}" in content:
            await asyncio.to_thread(update_roadmap_state, cwd, resolved_slug, ">")

    # 7. Check build status (from state.json in worktree)
    if not await asyncio.to_thread(is_build_complete, worktree_cwd, resolved_slug):
        agent, mode = await get_available_agent(db, "build", WORK_FALLBACK)
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
            agent, mode = await get_available_agent(db, "fix", WORK_FALLBACK)
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
        if is_main_ahead(cwd, resolved_slug):
            return format_error(
                "MAIN_AHEAD",
                f"main has commits not in trees/{resolved_slug}. Sync the worktree with main before review.",
                next_call=(
                    f'Merge or rebase main into trees/{resolved_slug}, then call teleclaude__next_work(slug="{resolved_slug}") again.'
                ),
            )
        agent, mode = await get_available_agent(db, "review", WORK_FALLBACK)
        return format_tool_call(
            command="next-review",
            args=resolved_slug,
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder=f"trees/{resolved_slug}",
            next_call=f'teleclaude__next_work(slug="{resolved_slug}")',
            note=REVIEW_DIFF_NOTE,
        )

    # 8.5 Check pending deferrals (R7)
    if await asyncio.to_thread(has_pending_deferrals, worktree_cwd, resolved_slug):
        agent, mode = await get_available_agent(db, "defer", WORK_FALLBACK)
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
    agent, mode = await get_available_agent(db, "finalize", WORK_FALLBACK)
    return format_tool_call(
        command="next-finalize",
        args=resolved_slug,
        project=cwd,
        agent=agent,
        thinking_mode=mode,
        subfolder="",  # Empty = main repo, NOT worktree
        next_call="teleclaude__next_work()",
    )
