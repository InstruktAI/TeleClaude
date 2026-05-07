"""Git-based primitives for session scoping.

Single git query that captures every path that differs between an anchor
commit (HEAD at turn-start) and the current working tree — committed-since
and uncommitted edits in one diff.
"""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

logger = get_logger(__name__)

__all__ = ["paths_changed_since", "read_head_sha"]

_GIT_FAILURES = (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError)


def read_head_sha(workspace_root: str) -> str | None:
    """Return the HEAD commit SHA for the workspace, or None on failure."""
    try:
        repo = Repo(workspace_root, search_parent_directories=True)
        sha = str(repo.git.rev_parse("HEAD")).strip()
        return sha or None
    except _GIT_FAILURES as exc:
        logger.debug(
            "read_head_sha failed",
            workspace_root=workspace_root,
            error=str(exc),
        )
        return None


def paths_changed_since(workspace_root: str, anchor_sha: str) -> set[str]:
    """Return paths that differ between anchor commit and the working state.

    Combines three sources to cover everything that changed in this turn:
    - `git diff --name-only <anchor>`: committed-since-anchor + tracked dirty
    - `git ls-files --others --exclude-standard`: untracked files (e.g. agent
      Write of a new file that hasn't been added yet)

    Fails open: returns empty set if any git query fails.
    """
    try:
        repo = Repo(workspace_root, search_parent_directories=True)
        diff_output = repo.git.diff("--name-only", anchor_sha)
        untracked_output = repo.git.ls_files("--others", "--exclude-standard")
        paths: set[str] = set()
        for line in diff_output.splitlines():
            stripped = line.strip()
            if stripped:
                paths.add(stripped)
        for line in untracked_output.splitlines():
            stripped = line.strip()
            if stripped:
                paths.add(stripped)
        return paths
    except _GIT_FAILURES as exc:
        logger.warning(
            "paths_changed_since failed",
            workspace_root=workspace_root,
            anchor_sha=anchor_sha,
            error=str(exc),
        )
        return set()
