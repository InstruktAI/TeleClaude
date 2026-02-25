"""Git repository bootstrap helpers for project setup."""

from __future__ import annotations

import subprocess
from pathlib import Path


def ensure_git_repo(project_root: Path) -> None:
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


def ensure_hooks_path(project_root: Path, hooks_path: str = ".githooks") -> None:
    """Configure git core.hooksPath idempotently for project-local hooks."""
    result = subprocess.run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip() == hooks_path:
        print(f"telec init: git hooksPath already set to {hooks_path}.")
        return

    set_result = subprocess.run(
        ["git", "config", "--local", "core.hooksPath", hooks_path],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if set_result.returncode == 0:
        print(f"telec init: git hooksPath set to {hooks_path}.")
    else:
        print(f"telec init: failed to set git hooksPath to {hooks_path}.")
