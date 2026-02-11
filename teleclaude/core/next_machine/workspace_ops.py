"""Workspace and worktree operations for Next Machine."""

from __future__ import annotations

from pathlib import Path

from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


def ensure_git_repo(cwd: str) -> None:
    """Ensure the workspace has a git repository initialized."""
    try:
        Repo(cwd)
    except InvalidGitRepositoryError:
        logger.info("Initializing git repository at %s", cwd)
        Repo.init(cwd)


def ensure_worktree(cwd: str, slug: str) -> bool:
    """Ensure a git worktree exists for the slug.

    If the worktree path already exists, it is assumed valid and skipped.
    """
    worktree_path = Path(cwd) / "trees" / slug
    if worktree_path.exists():
        logger.info("Worktree %s exists, skipping creation", slug)
        return False

    try:
        repo = Repo(cwd)
    except InvalidGitRepositoryError as exc:
        msg = f"Cannot create worktree: {cwd} is not a git repository"
        logger.error(msg)
        raise RuntimeError(msg) from exc

    trees_dir = Path(cwd) / "trees"
    trees_dir.mkdir(exist_ok=True)

    try:
        repo.git.worktree("add", str(worktree_path), "-b", slug)
    except GitCommandError:
        # Branch may already exist (e.g. partial finalize cleanup)
        try:
            repo.git.worktree("add", str(worktree_path), slug)
        except GitCommandError as exc:
            msg = f"Failed to create worktree at {worktree_path}"
            logger.error(msg)
            raise RuntimeError(msg) from exc

    logger.info("Created worktree at %s", worktree_path)
    return True
