"""Project setup and initialization for TeleClaude."""

import subprocess
from pathlib import Path

from teleclaude.project_setup.git_filters import setup_git_filters
from teleclaude.project_setup.gitattributes import update_gitattributes
from teleclaude.project_setup.hooks import install_precommit_hook
from teleclaude.project_setup.sync import install_docs_watch, sync_project_artifacts


def init_project(project_root: Path) -> None:
    """Initialize a project for TeleClaude.

    Sets up git filters, pre-commit hooks, syncs artifacts, and installs watchers.

    Args:
        project_root: Path to the project root directory.
    """
    _ensure_git_repo(project_root)
    setup_git_filters(project_root)
    update_gitattributes(project_root)
    install_precommit_hook(project_root)
    sync_project_artifacts(project_root)
    install_docs_watch(project_root)
    print("telec init complete.")


def _ensure_git_repo(project_root: Path) -> None:
    """Initialize a git repo if the project is not already in one."""
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return
    init_result = subprocess.run(
        ["git", "init"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if init_result.returncode == 0:
        print("telec init: initialized git repository.")
    else:
        print("telec init: failed to initialize git repository; skipping git setup.")


__all__ = [
    "init_project",
    "setup_git_filters",
    "update_gitattributes",
    "install_precommit_hook",
    "sync_project_artifacts",
    "install_docs_watch",
]
