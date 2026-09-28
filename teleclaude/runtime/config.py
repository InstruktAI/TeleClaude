"""Resolve this checkout's runtime home once, before the CLI loads.

Code from a slug worktree uses the home provisioned beside that checkout and
never reads ``TELECLAUDE_HOME``. Other checkouts retain the deployment-time
``TELECLAUDE_HOME`` behavior, including its live-home default. Runtime code
reads the result through ``get_runtime_config()``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from teleclaude.core.worktree_layout import worktree_home_for_checkout

_DEFAULT_HOME = Path("~/.teleclaude").expanduser()
_WORKTREE_HOME_MISSING_MESSAGE = "Slug worktree home is missing: {home}"
_FOREIGN_REPOSITORY_WRITE_MESSAGE = "Slug worktree at {worktree} cannot write repository {target}"


class WorktreeHomeMissingError(RuntimeError):
    """Raised when code loaded from a slug worktree has no provisioned home."""


class ForeignRepositoryWriteRefusedError(RuntimeError):
    """Raised when slug-worktree code attempts to write a different repository."""


@dataclass(frozen=True)
class RuntimeConfig:
    home: Path = _DEFAULT_HOME
    worktree_checkout: Path | None = None


def _init_default() -> RuntimeConfig:
    checkout = Path(__file__).resolve().parents[2]
    worktree_home = worktree_home_for_checkout(checkout)
    if worktree_home is not None:
        if not worktree_home.is_dir():
            raise WorktreeHomeMissingError(_WORKTREE_HOME_MISSING_MESSAGE.format(home=worktree_home))
        return RuntimeConfig(home=worktree_home, worktree_checkout=checkout)

    raw_home = os.getenv("TELECLAUDE_HOME")
    home = Path(raw_home).expanduser() if raw_home else _DEFAULT_HOME

    return RuntimeConfig(home=home)


_instance: RuntimeConfig = _init_default()


def get_runtime_config() -> RuntimeConfig:
    """Return the active RuntimeConfig singleton."""
    return _instance


def set_runtime_config(config: RuntimeConfig) -> None:
    """Replace the active RuntimeConfig singleton.

    Call once at process startup (or in test conftest) before importing
    modules that derive paths from it.  Not thread-safe after import time.
    """
    global _instance
    _instance = config


def require_own_checkout(root: Path) -> None:
    """Refuse repository writes outside the checkout that loaded this code."""
    worktree_checkout = get_runtime_config().worktree_checkout
    if worktree_checkout is None:
        return
    target = root.resolve()
    if target != worktree_checkout:
        raise ForeignRepositoryWriteRefusedError(
            _FOREIGN_REPOSITORY_WRITE_MESSAGE.format(worktree=worktree_checkout, target=target),
        )
