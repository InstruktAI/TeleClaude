"""Next Machine - Deterministic workflow state machine for orchestrating work.

This module provides two main functions:
- next_prepare(): Phase A state machine for collaborative architect work
- next_work(): Phase B state machine for deterministic builder work

Both derive state from files (stateless) and return plain text instructions
for the orchestrator AI to execute literally.
"""

import re
from pathlib import Path

from git import Repo
from git.exc import InvalidGitRepositoryError
from instrukt_ai_logging import get_logger

from teleclaude.core.db import Db

logger = get_logger(__name__)

# Fallback matrices: task_type -> [(agent, thinking_mode), ...]
PREPARE_FALLBACK: dict[str, list[tuple[str, str]]] = {
    "prepare": [("claude", "slow"), ("gemini", "slow")],
}

WORK_FALLBACK: dict[str, list[tuple[str, str]]] = {
    "bugs": [("codex", "med"), ("claude", "med"), ("gemini", "med")],
    "build": [("gemini", "med"), ("claude", "med"), ("codex", "med")],
    "review": [("codex", "slow"), ("claude", "slow"), ("gemini", "slow")],
    "fix": [("claude", "med"), ("gemini", "med"), ("codex", "med")],
    "commit": [("claude", "fast"), ("gemini", "fast"), ("codex", "fast")],
    "finalize": [("claude", "med"), ("gemini", "med"), ("codex", "med")],
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
    result = f"""Execute this tool call, then STOP your response entirely.

teleclaude__run_agent_command(
  computer="local",
  command="{command}",
  args="{args}",
  project="{project}",
  agent="{agent}",
  thinking_mode="{thinking_mode}",
  subfolder="{subfolder}"
)

AFTER DISPATCH:
1. Tell the user: "Dispatched session. Waiting for completion."
2. STOP responding. Do NOT call any more tools.
3. You will receive a notification when the worker completes.

FALLBACK TIMER (if no notification after 5 minutes):
Run this Bash command to set a timer, then check on the session:
  Bash: sleep 300 && echo "Timer complete"
After the sleep completes, call: teleclaude__get_session_data(computer="local", session_id="<id>", tail_chars=2000)

IMPORTANT: Do NOT call get_session_data before the 5-minute timer completes or before receiving a notification.

NEXT: When you receive the notification (or timer completes), call {next_call}() to check next step."""
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


# =============================================================================
# Shared Helper Functions
# =============================================================================


def resolve_slug(cwd: str, slug: str | None) -> tuple[str | None, bool, str]:
    """Resolve slug from argument or roadmap.

    Roadmap format expected:
        - [ ] my-slug   (pending)
        - [>] my-slug   (in progress)
        Description of the work item.

    Args:
        cwd: Current working directory (project root)
        slug: Optional explicit slug

    Returns:
        Tuple of (slug, is_in_progress, description).
        If slug provided, returns (slug, True, "").
        If found in roadmap, returns (slug, True if [>], False if [ ], description).
        If nothing found, returns (None, False, "").
    """
    if slug:
        return slug, True, ""

    roadmap_path = Path(cwd) / "todos" / "roadmap.md"
    if not roadmap_path.exists():
        return None, False, ""

    content = roadmap_path.read_text(encoding="utf-8")

    # Pattern: - [>] or - [ ] followed by slug
    pattern = re.compile(r"^-\s+\[([ >])\]\s+(\S+)", re.MULTILINE)
    match = pattern.search(content)
    if match:
        status: str = match.group(1)
        found_slug: str = match.group(2)
        is_in_progress: bool = status == ">"

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
        return found_slug, is_in_progress, description

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


def parse_impl_plan_done(cwd: str, slug: str) -> bool:
    """Check if Groups 1-4 in implementation plan are all done.

    Reads todos/{slug}/implementation-plan.md and checks for unchecked
    items (- [ ]) within Groups 1 through 4.

    Returns:
        True if NO unchecked items in Groups 1-4, False otherwise.
    """
    impl_plan_path = Path(cwd) / "todos" / slug / "implementation-plan.md"
    if not impl_plan_path.exists():
        return False

    content = impl_plan_path.read_text(encoding="utf-8")

    # Find sections: ## Group 1, ## Group 2, ## Group 3, ## Group 4
    # Check for unchecked items within those sections
    in_target_group = False
    group_pattern = re.compile(r"^##\s+Group\s+(\d+)")

    for line in content.split("\n"):
        group_match = group_pattern.match(line)
        if group_match:
            group_num = int(group_match.group(1))
            in_target_group = 1 <= group_num <= 4

        if in_target_group and line.strip().startswith("- [ ]"):
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


def ensure_worktree(cwd: str, slug: str) -> None:
    """Ensure worktree exists, creating it if needed.

    Creates: git worktree add trees/{slug} -b {slug}

    Args:
        cwd: Project root directory
        slug: Work item slug
    """
    worktree_path = Path(cwd) / "trees" / slug
    if worktree_path.exists():
        return

    try:
        repo = Repo(cwd)
        # Ensure trees directory exists
        trees_dir = Path(cwd) / "trees"
        trees_dir.mkdir(exist_ok=True)

        # Create worktree with new branch
        repo.git.worktree("add", str(worktree_path), "-b", slug)
        logger.info("Created worktree at %s", worktree_path)
    except InvalidGitRepositoryError:
        logger.error("Cannot create worktree: %s is not a git repository", cwd)
        raise


# =============================================================================
# Main Functions
# =============================================================================


async def next_prepare(db: Db, slug: str | None, cwd: str) -> str:
    """Phase A state machine for collaborative architect work.

    Checks what's missing (requirements.md, implementation-plan.md) and
    returns instructions to dispatch the appropriate architect session.

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
        # Dispatch roadmap grooming when roadmap is empty
        agent, mode = await get_available_agent(db, "prepare", PREPARE_FALLBACK)
        return format_tool_call(
            command="next-roadmap",
            args="",
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder="",
            note="Roadmap is empty. Groom the roadmap to add work items.",
            next_call="teleclaude__next_prepare",
        )

    # If not in progress, return helpful info about what was found
    if not is_in_progress:
        desc_text = f"\n\nDescription:\n{description}" if description else ""
        return format_error(
            "ITEM_NOT_STARTED",
            f"Found roadmap item '{resolved_slug}' (not started).{desc_text}\n\n"
            f"To start: mark as '- [>] {resolved_slug}' in todos/roadmap.md",
            next_call="After marking in-progress, call teleclaude__next_prepare() again.",
        )

    # 2. Check requirements
    if not check_file_exists(cwd, f"todos/{resolved_slug}/requirements.md"):
        agent, mode = await get_available_agent(db, "prepare", PREPARE_FALLBACK)
        return format_tool_call(
            command="next-prepare",
            args=resolved_slug,
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder="",
            note="Engage as collaborator - this is an architect session requiring discussion.",
            next_call="teleclaude__next_prepare",
        )

    # 3. Check implementation plan
    if not check_file_exists(cwd, f"todos/{resolved_slug}/implementation-plan.md"):
        agent, mode = await get_available_agent(db, "prepare", PREPARE_FALLBACK)
        return format_tool_call(
            command="next-prepare",
            args=resolved_slug,
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder="",
            note="Engage as collaborator - this is an architect session requiring discussion.",
            next_call="teleclaude__next_prepare",
        )

    # 4. Both exist - prepared
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
    # 0. Bug check (only when no explicit slug - bugs are priority)
    if not slug and has_pending_bugs(cwd):
        agent, mode = await get_available_agent(db, "bugs", WORK_FALLBACK)
        return format_tool_call(
            command="next-bugs",
            args="",
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder="",
            note="Fix bugs in todos/bugs.md before proceeding with roadmap work.",
            next_call="teleclaude__next_work",
        )

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
    ensure_worktree(cwd, resolved_slug)

    # 5. Check uncommitted changes
    if has_uncommitted_changes(cwd, resolved_slug):
        agent, mode = await get_available_agent(db, "commit", WORK_FALLBACK)
        return format_tool_call(
            command="next-commit",
            args=resolved_slug,
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder=f"trees/{resolved_slug}",
            next_call="teleclaude__next_work",
        )

    # 6. Check build status
    if not parse_impl_plan_done(cwd, resolved_slug):
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

    # 7. Check review status
    review_status = check_review_status(cwd, resolved_slug)
    if review_status == "missing":
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

    # 8. Check if review approved
    if review_status == "changes_requested":
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
