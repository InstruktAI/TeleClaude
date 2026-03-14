"""Git repository bootstrap helpers for project setup."""

from __future__ import annotations

import shutil
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
    result = subprocess.run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        subprocess.run(
            ["git", "config", "--local", "--unset", "core.hooksPath"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        print("telec init: removed core.hooksPath (restoring .git/hooks/).")

    # Copy project-local hooks into .git/hooks/ (preserving pre-commit)
    for hook_file in source_dir.iterdir():
        if not hook_file.is_file():
            continue
        dest = git_hooks_dir / hook_file.name
        shutil.copy2(hook_file, dest)
        dest.chmod(dest.stat().st_mode | 0o111)

    print(f"telec init: installed project hooks from {hooks_path}/ into .git/hooks/.")
