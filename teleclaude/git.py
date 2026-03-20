"""GitPython configuration — resolves the real git binary, bypassing the agent wrapper.

The TeleClaude git wrapper (~/.teleclaude/bin/git) is a PATH-based safety net for
agent CLI sessions. Python automation code is trusted system logic and must not be
subject to wrapper restrictions. This module resolves the real git binary using the
same algorithm as the wrapper's ``_real_git()`` function: walk PATH, skip the wrapper
directory, return the first executable ``git``.

All production code that needs git operations should import from here::

    from teleclaude.git import Repo, GitCommandError
"""

from __future__ import annotations

import os
from pathlib import Path

import git as _gitpython
from git import Repo as Repo  # pylint: disable=useless-import-alias  # Re-export for public API
from git.exc import (  # pylint: disable=useless-import-alias  # Re-export for public API
    GitCommandError as GitCommandError,
)
from git.exc import (  # pylint: disable=useless-import-alias  # Re-export for public API
    InvalidGitRepositoryError as InvalidGitRepositoryError,
)
from git.exc import (  # pylint: disable=useless-import-alias  # Re-export for public API
    NoSuchPathError as NoSuchPathError,
)

__all__ = [
    "GitCommandError",
    "InvalidGitRepositoryError",
    "NoSuchPathError",
    "Repo",
]

_WRAPPER_DIR = str(Path("~/.teleclaude/bin").expanduser())


def _find_real_git() -> str:
    """Walk PATH, skip the wrapper directory, return the first real git binary."""
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry == _WRAPPER_DIR:
            continue
        candidate = Path(entry) / "git"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise FileNotFoundError("real git binary not found in PATH")


_gitpython.refresh(_find_real_git())

# Disable rebase.autoStash globally for all GitPython operations in this process.
# Git's pull --rebase delegates to git rebase, which auto-stashes dirty files when
# rebase.autoStash is set. In multi-worktree environments, stash is repo-wide —
# auto-stash from one worktree corrupts another. This env-var override ensures no
# GitPython call path can create stash entries, regardless of user/global git config.
os.environ["GIT_CONFIG_COUNT"] = str(int(os.environ.get("GIT_CONFIG_COUNT", "0")) + 1)
_idx = int(os.environ["GIT_CONFIG_COUNT"]) - 1
os.environ[f"GIT_CONFIG_KEY_{_idx}"] = "rebase.autoStash"
os.environ[f"GIT_CONFIG_VALUE_{_idx}"] = "false"
