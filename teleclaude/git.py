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

from teleclaude.paths import BIN_DIR, DEFAULT_BIN_DIR


def _wrapper_dirs() -> set[Path]:
    """Return all git wrapper directories that Python git automation must bypass."""
    return {BIN_DIR.expanduser().resolve(), DEFAULT_BIN_DIR.expanduser().resolve()}


def _find_real_git() -> str:
    """Walk PATH, skip the wrapper directory, return the first real git binary."""
    wrapper_dirs = _wrapper_dirs()
    for entry in os.environ.get("PATH", "").split(os.pathsep):
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
os.environ["GIT_PYTHON_GIT_EXECUTABLE"] = GIT_EXECUTABLE
# ---------------------------------------------------------------------------
# Observability: log every gitpython invocation (argv, rc, duration, stderr).
#
# GitPython calls bypass the bash wrapper because GIT_PYTHON_GIT_EXECUTABLE
# points at the real binary. Without this hook, every git operation invoked
# from Python (telec code commit, state machine, daemon git_ops) is invisible
# to the central log. Errors like "Unable to create .git/index.lock" then
# surface only in the calling agent's stderr and disappear.
#
# The hook wraps git.cmd.Git.execute — gitpython's single funnel for all
# subprocess invocations — and emits one structured log line per call
# regardless of whether the caller used with_extended_output or not.
# ---------------------------------------------------------------------------
import time as _time  # noqa: E402
from typing import Any  # noqa: E402

from git import Repo as Repo  # noqa: E402
from git.cmd import Git as _Git  # noqa: E402
from git.exc import GitCommandError as GitCommandError  # noqa: E402
from git.exc import InvalidGitRepositoryError as InvalidGitRepositoryError  # noqa: E402
from git.exc import NoSuchPathError as NoSuchPathError  # noqa: E402
from gitdb.exc import BadName as BadName  # noqa: E402
from instrukt_ai_logging import get_logger as _get_logger  # noqa: E402

_exec_logger = _get_logger("teleclaude.git.exec")
_original_execute = _Git.execute


def _logged_execute(self: _Git, command: Any, *args: Any, **kwargs: Any) -> Any:
    argv = list(command) if isinstance(command, list | tuple) else [str(command)]
    t0 = _time.monotonic()
    try:
        result = _original_execute(self, command, *args, **kwargs)
    except GitCommandError as exc:
        duration_ms = int((_time.monotonic() - t0) * 1000)
        stderr = (str(exc.stderr) if exc.stderr else "").strip()
        # A non-zero rc with empty stderr is a routine query outcome, not a
        # failure: `git grep` / `git diff --quiet` / fallback `rev-parse` all
        # exit non-zero to signal "no match" with nothing on stderr. Only a
        # real diagnostic (fatal:/error: text on stderr) earns ERROR; the rest
        # is DEBUG so benign no-match queries don't masquerade as alarms.
        _log = _exec_logger.error if stderr else _exec_logger.debug
        _log(
            "git_exec_failed argv=%s rc=%s duration_ms=%d stderr=%s",
            argv,
            exc.status,
            duration_ms,
            stderr,
            extra={
                "argv": argv,
                "rc": exc.status,
                "duration_ms": duration_ms,
                "stderr": stderr,
                "stdout": (str(exc.stdout) if exc.stdout else "").strip(),
            },
        )
        raise
    duration_ms = int((_time.monotonic() - t0) * 1000)
    # Per-call success is pure tracing — central observability of the git seam,
    # not an operational signal. TRACE keeps it out of routine DEBUG views.
    if isinstance(result, tuple) and len(result) == 3:
        rc, stdout, stderr = result
        _exec_logger.trace(
            "git_exec argv=%s rc=%s duration_ms=%d",
            argv,
            rc,
            duration_ms,
            extra={
                "argv": argv,
                "rc": rc,
                "duration_ms": duration_ms,
                "stdout": (str(stdout) if stdout else "").strip(),
                "stderr": (str(stderr) if stderr else "").strip(),
            },
        )
    else:
        _exec_logger.trace(
            "git_exec argv=%s rc=0 duration_ms=%d",
            argv,
            duration_ms,
            extra={
                "argv": argv,
                "rc": 0,
                "duration_ms": duration_ms,
                "stdout": (str(result) if isinstance(result, str) else "").strip(),
            },
        )
    return result


_Git.execute = _logged_execute  # type: ignore[method-assign]

__all__ = [
    "GIT_EXECUTABLE",
    "BadName",
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
