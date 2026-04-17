"""GitPython configuration — resolves the git binary for Python automation.

All production code that needs git operations should import from here::

    from teleclaude.git import Repo, GitCommandError
"""

from __future__ import annotations

import os
from pathlib import Path


def _find_git() -> str:
    """Find the first executable git binary on PATH."""
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(entry) / "git"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise FileNotFoundError("git binary not found in PATH")


# Point gitpython at the real binary BEFORE import to prevent recursion
# through the wrapper (whose shebang is uv run).
os.environ["GIT_PYTHON_GIT_EXECUTABLE"] = _find_git()
# pylint: disable=useless-import-alias,wrong-import-position,wrong-import-order
from git import Repo as Repo  # noqa: E402
from git.exc import GitCommandError as GitCommandError  # noqa: E402
from git.exc import InvalidGitRepositoryError as InvalidGitRepositoryError  # noqa: E402
from git.exc import NoSuchPathError as NoSuchPathError  # noqa: E402

__all__ = [
    "GitCommandError",
    "InvalidGitRepositoryError",
    "NoSuchPathError",
    "Repo",
]


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
