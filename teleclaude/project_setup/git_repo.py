"""Git repository bootstrap helpers for project setup."""

from __future__ import annotations

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.paths import is_platform_home

logger = get_logger(__name__)

_INITIALIZED_EVENT = "project_git_repository_initialized"
_INITIALIZATION_FAILED_EVENT = "project_git_repository_initialization_failed"
_MAIN_BRANCH = "main"


def _enclosing_repository_holds_project(project_root: Path) -> bool:
    """Return whether a repository encloses the folder and may hold it as a project.

    The global home's repository never holds a project: a folder inside it that
    is not the global home itself needs a repository of its own.
    """
    try:
        working_tree = Repo(project_root, search_parent_directories=True).working_tree_dir
    except (InvalidGitRepositoryError, NoSuchPathError):
        return False
    if working_tree is None:
        return False
    return is_platform_home(project_root) or not is_platform_home(Path(working_tree))


def ensure_git_repo(project_root: Path, *, always_init: bool = False) -> None:
    """Give the project a repository of its own when no suitable repository holds it.

    A repository is initialized on ``main`` when none encloses the folder, or when
    the enclosing one is the global home's. With ``always_init`` the folder gets
    its own repository regardless, which is how a created project starts.
    """
    if not always_init and _enclosing_repository_holds_project(project_root):
        return

    try:
        Repo.init(project_root, initial_branch=_MAIN_BRANCH)
        logger.info(_INITIALIZED_EVENT, project_root=str(project_root))
    except GitCommandError:
        logger.exception(_INITIALIZATION_FAILED_EVENT, project_root=str(project_root))
