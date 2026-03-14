"""Git operations — dirty checks, stash introspection, worktree merges, agent guidance.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import cast

from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError, NoSuchPathError
from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import _WORKTREE_PREP_STATE_REL
from teleclaude.core.next_machine.state_io import read_text_sync, write_text_sync

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Async file helpers
# ---------------------------------------------------------------------------


async def read_text_async(path: Path) -> str:
    """Read text from a file without blocking the event loop."""
    return await asyncio.to_thread(read_text_sync, path)


async def write_text_async(path: Path, content: str) -> None:
    """Write text to a file without blocking the event loop."""
    await asyncio.to_thread(write_text_sync, path, content)


# ---------------------------------------------------------------------------
# Git status helpers
# ---------------------------------------------------------------------------


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
# Worktree git operations
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Agent availability guidance
# ---------------------------------------------------------------------------


async def compose_agent_guidance(db: Db) -> str:
    """Compose runtime availability guidance for agent selection.

    Agent characteristics (strengths, cognitive profiles) are documented in the
    baseline concept snippet 'general/concept/agent-characteristics' and loaded
    into every agent's context. This function only adds runtime availability
    information (enabled/disabled, degraded status).
    """
    from teleclaude.config import config as app_config
    from teleclaude.core.agents import AgentName

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


__all__ = [
    "_has_meaningful_diff",
    "_merge_origin_main_into_worktree",
    "build_git_hook_env",
    "compose_agent_guidance",
    "get_stash_entries",
    "has_git_stash_entries",
    "has_uncommitted_changes",
    "read_text_async",
    "write_text_async",
]
