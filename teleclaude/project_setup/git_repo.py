"""Git repository bootstrap helpers for project setup."""

from __future__ import annotations

from pathlib import Path

from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo


def ensure_git_repo(project_root: Path) -> None:
    """Initialize a git repo if the project is not already in one."""
    try:
        Repo(project_root, search_parent_directories=True)
        return
    except (InvalidGitRepositoryError, NoSuchPathError):
        pass

    try:
        Repo.init(project_root)
        print("telec projects init: initialized git repository.")
    except GitCommandError:
        print("telec projects init: failed to initialize git repository; skipping git setup.")
