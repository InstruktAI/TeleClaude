"""Git repository bootstrap helpers for project setup."""

from __future__ import annotations

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

logger = get_logger(__name__)

_INITIALIZED_EVENT = "project_git_repository_initialized"
_INITIALIZATION_FAILED_EVENT = "project_git_repository_initialization_failed"


def ensure_git_repo(project_root: Path) -> None:
    """Initialize a git repo if the project is not already in one."""
    try:
        Repo(project_root, search_parent_directories=True)
        return
    except (InvalidGitRepositoryError, NoSuchPathError):
        pass

    try:
        Repo.init(project_root, initial_branch="main")
        logger.info(_INITIALIZED_EVENT, project_root=str(project_root))
    except GitCommandError:
        logger.exception(_INITIALIZATION_FAILED_EVENT, project_root=str(project_root))
