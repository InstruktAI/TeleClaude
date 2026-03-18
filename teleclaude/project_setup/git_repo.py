"""Git repository bootstrap helpers for project setup."""

from __future__ import annotations

import shutil
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
        print("telec init: initialized git repository.")
    except GitCommandError:
        print("telec init: failed to initialize git repository; skipping git setup.")


def ensure_hooks_path(project_root: Path, hooks_path: str = ".githooks") -> None:
    """Install project-local hooks into .git/hooks/ without touching core.hooksPath.

    Previously this function set core.hooksPath, which made git ignore
    .git/hooks/ entirely — silently killing pre-commit framework hooks.
    Now it copies hooks from the project-local directory into .git/hooks/
    so they coexist with pre-commit.
    """
    source_dir = project_root / hooks_path
    if not source_dir.is_dir():
        return

    git_hooks_dir = project_root / ".git" / "hooks"
    if not git_hooks_dir.is_dir():
        return

    # If core.hooksPath was previously set, unset it to restore .git/hooks/
    try:
        repo = Repo(project_root)
    except (InvalidGitRepositoryError, NoSuchPathError):
        return

    try:
        repo.git.config("--local", "--get", "core.hooksPath")
        # If we got here, the value exists — unset it
        repo.git.config("--local", "--unset", "core.hooksPath")
        print("telec init: removed core.hooksPath (restoring .git/hooks/).")
    except GitCommandError:
        # core.hooksPath not set — expected, continue
        pass

    # Copy project-local hooks into .git/hooks/ (preserving pre-commit)
    for hook_file in source_dir.iterdir():
        if not hook_file.is_file():
            continue
        dest = git_hooks_dir / hook_file.name
        shutil.copy2(hook_file, dest)
        dest.chmod(dest.stat().st_mode | 0o111)

    print(f"telec init: installed project hooks from {hooks_path}/ into .git/hooks/.")
