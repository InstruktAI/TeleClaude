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
from collections.abc import Mapping
from pathlib import Path

from teleclaude.paths import BIN_DIR, DEFAULT_BIN_DIR

_GIT_LOCAL_ENV_VARS_ARGUMENT = "--local-env-vars"
_GIT_LINKED_WORKTREE_ARGUMENTS = ("--path-format=absolute", "--git-dir", "--git-common-dir")
_GIT_INDEX_FILE_ENVIRONMENT_VARIABLE = "GIT_INDEX_FILE"


def _wrapper_dirs() -> set[Path]:
    """Return all git wrapper directories that Python git automation must bypass."""
    return {BIN_DIR.expanduser().resolve(), DEFAULT_BIN_DIR.expanduser().resolve()}


def _find_real_git() -> str:
    """Walk PATH, skip the wrapper directory, return the first real git binary."""
    wrapper_dirs = _wrapper_dirs()
    for entry in os.environ.get("PATH", "").split(os.pathsep):  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
        entry_path = Path(entry).expanduser().resolve()
        if entry_path in wrapper_dirs:
            continue
        candidate = entry_path / "git"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise FileNotFoundError("real git binary not found in PATH")


# Point gitpython at the real binary BEFORE import to prevent recursion
# through the wrapper (whose shebang is uv run).
GIT_EXECUTABLE = _find_real_git()
os.environ["GIT_PYTHON_GIT_EXECUTABLE"] = GIT_EXECUTABLE  # fmt: skip  # guard: direct-env-read - allowed: bootstrap or internal process signal

from typing import cast  # noqa: E402

from git import Actor as Actor  # noqa: E402
from git import IndexFile as IndexFile  # noqa: E402
from git import Repo as Repo  # noqa: E402
from git.cmd import Git as _Git  # noqa: E402
from git.exc import GitCommandError as GitCommandError  # noqa: E402
from git.exc import HookExecutionError as HookExecutionError  # noqa: E402
from git.exc import InvalidGitRepositoryError as InvalidGitRepositoryError  # noqa: E402
from git.exc import NoSuchPathError as NoSuchPathError  # noqa: E402
from gitdb.exc import BadName as BadName  # noqa: E402

__all__ = [
    "GIT_EXECUTABLE",
    "Actor",
    "BadName",
    "GitCommandError",
    "HookExecutionError",
    "IndexFile",
    "InvalidGitRepositoryError",
    "NoSuchPathError",
    "Repo",
    "is_linked_worktree",
]


def is_linked_worktree(path: str | Path) -> bool:
    """Return whether Git identifies path as a linked worktree."""
    git_directories = cast(list[str], _Git(str(path)).rev_parse(*_GIT_LINKED_WORKTREE_ARGUMENTS).splitlines())
    git_dir, git_common_dir = git_directories
    return git_dir != git_common_dir


def no_autostash_env() -> dict[str, str]:
    """Return an env dict that disables all auto-stash mechanisms for a single git subprocess.

    Both rebase and merge can auto-stash dirty files. In multi-worktree environments,
    stash is repo-wide — auto-stash from one worktree corrupts another. Pass this
    to GitPython's env parameter to prevent stash creation without polluting os.environ.
    """
    env = os.environ.copy()  # fmt: skip  # guard: direct-env-read - allowed: child-process environment construction
    count = int(env.get("GIT_CONFIG_COUNT", "0"))
    env[f"GIT_CONFIG_KEY_{count}"] = "rebase.autoStash"
    env[f"GIT_CONFIG_VALUE_{count}"] = "false"
    env[f"GIT_CONFIG_KEY_{count + 1}"] = "merge.autoStash"
    env[f"GIT_CONFIG_VALUE_{count + 1}"] = "false"
    env["GIT_CONFIG_COUNT"] = str(count + 2)
    return env


def _active_git_index_file() -> str | None:
    """Return the caller's explicit index path for a tree-read subprocess."""
    return os.environ.get(_GIT_INDEX_FILE_ENVIRONMENT_VARIABLE)  # fmt: skip  # guard: direct-env-read - allowed: child-process environment construction


def hook_free_environment(
    repo_root: str | Path,
    *,
    base_environment: Mapping[str, str] | None = None,
    preserve: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Return an environment without Git's repository-local hook variables."""
    if base_environment is None:
        env = os.environ.copy()  # fmt: skip  # guard: direct-env-read - allowed: child-process environment construction
    else:
        env = dict(base_environment)
    names = Repo(str(Path(repo_root).resolve())).git.rev_parse(_GIT_LOCAL_ENV_VARS_ARGUMENT).splitlines()
    for name in names:
        if name not in preserve:
            env.pop(name, None)
    if _GIT_INDEX_FILE_ENVIRONMENT_VARIABLE in preserve and _GIT_INDEX_FILE_ENVIRONMENT_VARIABLE not in env:
        active_index = _active_git_index_file()
        if active_index is not None:
            env[_GIT_INDEX_FILE_ENVIRONMENT_VARIABLE] = active_index
    return env
