"""Git primitives for session scoping."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

logger = get_logger(__name__)

__all__ = ["read_head_sha"]

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
