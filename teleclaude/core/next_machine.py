"""Next Machine - Deterministic workflow state machine for orchestrating work.

This module provides two main functions:
- next_prepare(): Phase A state machine for collaborative architect work
- next_work(): Phase B state machine for deterministic builder work

Both derive state from files (stateless) and return plain text instructions
for the orchestrator AI to execute literally.
"""

import json
import re
from pathlib import Path
from typing import Literal

from git import Repo
from git.exc import InvalidGitRepositoryError
from instrukt_ai_logging import get_logger

from teleclaude.core.db import Db

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
}

# Post-completion instructions for each command (used in format_tool_call)
# These tell the orchestrator what to do AFTER a worker completes
POST_COMPLETION: dict[str, str] = {
    "next-bugs": """WHEN WORKER COMPLETES:
1. Verify bugs fixed and tests pass
2. If success:
   - teleclaude__end_session(computer="local", session_id="<session_id>")
   - Call {next_call}()
3. If bugs remain or tests fail:
   - Keep session alive and guide worker to resolution""",
    "next-build": """WHEN WORKER COMPLETES:
1. Verify worker reports success with passing tests
2. If success:
   - teleclaude__mark_phase(slug="{args}", phase="build", status="complete")
   - teleclaude__end_session(computer="local", session_id="<session_id>")
   - Call {next_call}()
3. If failure or blocker:
   - Keep session alive and guide worker to resolution""",
    "next-review": """WHEN WORKER COMPLETES:
1. Read trees/{args}/todos/{args}/review-findings.md
2. Relay verdict to state:
   - If "[x] APPROVE": teleclaude__mark_phase(slug="{args}", phase="review", status="approved")
   - If "[x] REQUEST CHANGES": teleclaude__mark_phase(slug="{args}", phase="review", status="changes_requested")
3. teleclaude__end_session(computer="local", session_id="<session_id>")
4. Call {next_call}()""",
    "next-fix-review": """WHEN WORKER COMPLETES:
1. Verify fixes applied and tests pass
2. If fixes complete:
   - teleclaude__mark_phase(slug="{args}", phase="review", status="pending")
   - teleclaude__end_session(computer="local", session_id="<session_id>")
   - Call {next_call}()
3. If fixes incomplete:
   - Keep session alive and guide worker to finish""",
    "next-finalize": """WHEN WORKER COMPLETES:
1. Verify merge and archive succeeded
2. If success:
   - teleclaude__end_session(computer="local", session_id="<session_id>")
   - Call {next_call}()
3. If failed:
   - Keep session alive and help resolve""",
}


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
        # Substitute {args} and {next_call} placeholders
        post_completion = post_completion.format(args=args, next_call=next_call)

    result = f"""Before running the command below, read ~/.agents/commands/{command}.md if you haven't already.

Execute these steps in order:

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

C) YOU SEND ANOTHER MESSAGE TO THE AGENT:
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

ASK USER: Do you want to continue with more preparation work, or start the build/review cycle with teleclaude__next_work()?"""


def format_complete(slug: str, archive_path: str) -> str:
    """Format a 'complete' message indicating work item is finalized."""
    return f"""COMPLETE: todos/{slug} has been finalized and delivered to {archive_path}/

NEXT: Call teleclaude__next_work() to continue with more work."""


def format_uncommitted_changes(slug: str) -> str:
    """Format instruction for orchestrator to commit uncommitted changes directly."""
    return f"""UNCOMMITTED CHANGES in trees/{slug}

Commit, then call teleclaude__next_work() to continue."""


def format_hitl_guidance(context: str) -> str:
    """Format guidance for the calling AI to work interactively with the user.

    Used when HITL=True.
    """
    return f"""Before proceeding, read ~/.agents/commands/next-prepare.md if you haven't already.

{context}"""


# =============================================================================
# Shared Helper Functions
# =============================================================================


# Valid phases and statuses for state.json
Phase = Literal["build", "review"]
PhaseStatus = Literal["pending", "complete", "approved", "changes_requested"]

DEFAULT_STATE: dict[str, str] = {
    "build": "pending",
    "review": "pending",
}


def get_state_path(cwd: str, slug: str) -> Path:
    """Get path to state.json in worktree."""
    return Path(cwd) / "todos" / slug / "state.json"


def read_phase_state(cwd: str, slug: str) -> dict[str, str]:
    """Read state.json from worktree.

    Returns default state if file doesn't exist.
    """
    state_path = get_state_path(cwd, slug)
    if not state_path.exists():
        return DEFAULT_STATE.copy()

    content = state_path.read_text(encoding="utf-8")
    state: dict[str, str] = json.loads(content)
    # Merge with defaults for any missing keys
    return {**DEFAULT_STATE, **state}


def write_phase_state(cwd: str, slug: str, state: dict[str, str]) -> None:
    """Write state.json and commit to git."""
    state_path = get_state_path(cwd, slug)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    # Commit the state change
    try:
        repo = Repo(cwd)
        relative_path = state_path.relative_to(cwd)
        repo.index.add([str(relative_path)])
        # Create descriptive commit message
        phases_done = [p for p, s in state.items() if s in ("complete", "approved")]
        msg = f"state({slug}): {', '.join(phases_done) if phases_done else 'init'}"
        repo.index.commit(msg)
        logger.info("Committed state update for %s", slug)
    except InvalidGitRepositoryError:
        logger.warning("Cannot commit state: %s is not a git repository", cwd)


def mark_phase(cwd: str, slug: str, phase: str, status: str) -> dict[str, str]:
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


def is_build_complete(cwd: str, slug: str) -> bool:
    """Check if build phase is complete."""
    state = read_phase_state(cwd, slug)
    return state.get("build") == "complete"


def is_review_approved(cwd: str, slug: str) -> bool:
    """Check if review phase is approved."""
    state = read_phase_state(cwd, slug)
    return state.get("review") == "approved"


def is_review_changes_requested(cwd: str, slug: str) -> bool:
    """Check if review requested changes."""
    state = read_phase_state(cwd, slug)
    return state.get("review") == "changes_requested"


def resolve_slug(cwd: str, slug: str | None, ready_only: bool = False) -> tuple[str | None, bool, str]:
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

    content = roadmap_path.read_text(encoding="utf-8")

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


def check_file_exists(cwd: str, relative_path: str) -> bool:
    """Check if a file exists relative to cwd."""
    return (Path(cwd) / relative_path).exists()


def has_pending_bugs(cwd: str) -> bool:
    """Check if todos/bugs.md has unchecked items.

    Returns:
        True if bugs.md exists and contains unchecked checkboxes ([ ]).
    """
    bugs_path = Path(cwd) / "todos" / "bugs.md"
    if not bugs_path.exists():
        return False
    content = bugs_path.read_text(encoding="utf-8")
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

    content = roadmap_path.read_text(encoding="utf-8")

    # Pattern: - [STATE] slug where STATE is space, ., >, or x
    pattern = re.compile(rf"^(- \[)[ .>x](\] {re.escape(slug)})(\s|$)", re.MULTILINE)
    new_content, count = pattern.subn(rf"\g<1>{new_state}\g<2>\g<3>", content)

    if count == 0:
        return False

    roadmap_path.write_text(new_content, encoding="utf-8")

    # Commit the state change
    try:
        repo = Repo(cwd)
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

    content = deps_path.read_text(encoding="utf-8")
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
                repo.index.remove(["todos/dependencies.json"])  # type: ignore[misc]
                repo.index.commit("deps: remove empty dependencies.json")
            except InvalidGitRepositoryError:
                pass
        return

    deps_path.write_text(json.dumps(deps, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    try:
        repo = Repo(cwd)
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

    content = roadmap_path.read_text(encoding="utf-8")
    pattern = re.compile(r"^- \[([x.> ])\] ([a-z0-9-]+)", re.MULTILINE)

    roadmap_items: dict[str, str] = {}
    for match in pattern.finditer(content):
        state, item_slug = match.groups()
        roadmap_items[item_slug] = state

    for dep in item_deps:
        if dep not in roadmap_items:
            # Not in roadmap - check if archived
            if get_archive_path(cwd, dep) is None:
                # Not archived either - dependency doesn't exist
                # This shouldn't happen if validation worked, but treat as unsatisfied
                return False
            # Archived = satisfied
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

    content = impl_plan_path.read_text(encoding="utf-8")

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

    content = review_path.read_text(encoding="utf-8")
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
    """Ensure worktree exists, creating it if needed.

    Creates: git worktree add trees/{slug} -b {slug}

    Args:
        cwd: Project root directory
        slug: Work item slug

    Returns:
        True if a new worktree was created, False if it already existed
    """
    worktree_path = Path(cwd) / "trees" / slug
    if worktree_path.exists():
        return False

    try:
        repo = Repo(cwd)
        # Ensure trees directory exists
        trees_dir = Path(cwd) / "trees"
        trees_dir.mkdir(exist_ok=True)

        # Create worktree with new branch
        repo.git.worktree("add", str(worktree_path), "-b", slug)
        logger.info("Created worktree at %s", worktree_path)
        return True
    except InvalidGitRepositoryError:
        logger.error("Cannot create worktree: %s is not a git repository", cwd)
        raise


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

    if not slug and not hitl:
        resolved_slug, _, _ = resolve_slug(cwd, None)

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

    # 4. Both exist - mark as ready and return prepared
    update_roadmap_state(cwd, resolved_slug, ".")
    return format_prepared(resolved_slug)


async def next_work(db: Db, slug: str | None, cwd: str) -> str:
    """Phase B state machine for deterministic builder work.

    Executes the build/review/fix/finalize cycle on prepared work items.

    Args:
        db: Database instance
        slug: Optional explicit slug (resolved from roadmap if not provided)
        cwd: Current working directory (project root)

    Returns:
        Plain text instructions for the orchestrator to execute
    """
    # 1. Resolve slug
    resolved_slug, is_in_progress, description = resolve_slug(cwd, slug)
    if not resolved_slug:
        return format_error(
            "NO_ROADMAP_ITEMS",
            "No items found in roadmap.",
            next_call="Call teleclaude__next_prepare() to groom the roadmap.",
        )

    if not is_in_progress:
        desc_text = f"\n\nDescription:\n{description}" if description else ""
        return format_error(
            "ITEM_NOT_STARTED",
            f"Found roadmap item '{resolved_slug}' (not started).{desc_text}",
            next_call="Call teleclaude__next_prepare() to start work on it.",
        )

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
            next_call=f'Call teleclaude__next_prepare("{resolved_slug}") to complete preparation.',
        )

    # 4. Ensure worktree exists
    worktree_created = ensure_worktree(cwd, resolved_slug)
    if worktree_created:
        logger.info("Created new worktree for %s", resolved_slug)

    # From here on, use worktree context for file checks
    # The builder works in the worktree, so implementation-plan.md and
    # review-findings.md are committed there, not in main repo
    worktree_cwd = str(Path(cwd) / "trees" / resolved_slug)

    # 5. Check uncommitted changes - orchestrator handles commits directly
    if has_uncommitted_changes(cwd, resolved_slug):
        return format_uncommitted_changes(resolved_slug)

    # 6. Check build status (from state.json in worktree)
    if not is_build_complete(worktree_cwd, resolved_slug):
        agent, mode = await get_available_agent(db, "build", WORK_FALLBACK)
        return format_tool_call(
            command="next-build",
            args=resolved_slug,
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder=f"trees/{resolved_slug}",
            next_call="teleclaude__next_work",
        )

    # 7. Check review status (from state.json in worktree)
    if not is_review_approved(worktree_cwd, resolved_slug):
        # Check if review hasn't started yet or needs fixes
        if is_review_changes_requested(worktree_cwd, resolved_slug):
            agent, mode = await get_available_agent(db, "fix", WORK_FALLBACK)
            return format_tool_call(
                command="next-fix-review",
                args=resolved_slug,
                project=cwd,
                agent=agent,
                thinking_mode=mode,
                subfolder=f"trees/{resolved_slug}",
                next_call="teleclaude__next_work",
            )
        # Review not started or still pending
        agent, mode = await get_available_agent(db, "review", WORK_FALLBACK)
        return format_tool_call(
            command="next-review",
            args=resolved_slug,
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder=f"trees/{resolved_slug}",
            next_call="teleclaude__next_work",
        )

    # 9. Review approved - dispatch finalize (runs from MAIN REPO, not worktree)
    agent, mode = await get_available_agent(db, "finalize", WORK_FALLBACK)
    return format_tool_call(
        command="next-finalize",
        args=resolved_slug,
        project=cwd,
        agent=agent,
        thinking_mode=mode,
        subfolder="",  # Empty = main repo, NOT worktree
        next_call="teleclaude__next_work",
    )
