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


def no_autostash_env() -> dict[str, str]:
    """Return an env dict that disables all auto-stash mechanisms for a single git subprocess.

    Both rebase and merge can auto-stash dirty files. In multi-worktree environments,
    stash is repo-wide — auto-stash from one worktree corrupts another. Pass this
    to GitPython's env parameter to prevent stash creation without polluting os.environ.
    """
    env = os.environ.copy()
    count = int(env.get("GIT_CONFIG_COUNT", "0"))
    env[f"GIT_CONFIG_KEY_{count}"] = "rebase.autoStash"
    env[f"GIT_CONFIG_VALUE_{count}"] = "false"
    env[f"GIT_CONFIG_KEY_{count + 1}"] = "merge.autoStash"
    env[f"GIT_CONFIG_VALUE_{count + 1}"] = "false"
    env["GIT_CONFIG_COUNT"] = str(count + 2)
    return env
