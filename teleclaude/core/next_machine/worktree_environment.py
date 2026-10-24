"""Rebind pre-existing slug worktrees to an associated project's environment."""

from __future__ import annotations

import os
from pathlib import Path

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.checkout_roots import resolve_checkout_roots
from teleclaude.core.next_machine._types import _WORKTREE_PREP_STATE_REL
from teleclaude.slug import validate_slug

_VENV_NAME = ".venv"
_ENV_NAME = ".env"
_ENVIRONMENT_LINKS = (_VENV_NAME, _ENV_NAME)
_RESERVED_PREFIX = "_"
_BIN_DIRECTORY = "bin"
_PYTHON_EXECUTABLE = "python"
_NO_ASSOCIATION_ERROR = "the installed checkout has no registered development location"
_ENVIRONMENT_NOT_READY_ERROR = "the development checkout environment is not ready"
_NON_LINK_ENVIRONMENT_PATH_ERROR = "refusing to replace non-link environment path {path}"


class WorktreeEnvironmentRebindError(RuntimeError):
    """A retained worktree could not be safely moved to the development environment."""


def rebind_retained_worktree_environments(installed_root: Path) -> tuple[Path, ...]:
    """Repoint the installed checkout's retained slug worktrees and invalidate prep receipts."""
    roots = resolve_checkout_roots(installed_root)
    if roots.installed != installed_root.expanduser().resolve() or roots.authoring == roots.installed:
        raise WorktreeEnvironmentRebindError(_NO_ASSOCIATION_ERROR)
    development = roots.authoring
    if (
        not (development / _VENV_NAME / _BIN_DIRECTORY / _PYTHON_EXECUTABLE).is_file()
        or not (development / _ENV_NAME).is_file()
    ):
        raise WorktreeEnvironmentRebindError(_ENVIRONMENT_NOT_READY_ERROR)

    changed: list[Path] = []
    worktrees_root = roots.installed / WORKTREE_DIR
    if not worktrees_root.is_dir():
        return ()
    for worktree in sorted(worktrees_root.iterdir()):
        if worktree.name.startswith(_RESERVED_PREFIX) or not worktree.is_dir():
            continue
        try:
            validate_slug(worktree.name)
        except ValueError:
            continue
        for name in _ENVIRONMENT_LINKS:
            link = worktree / name
            if link.exists() and not link.is_symlink():
                raise WorktreeEnvironmentRebindError(_NON_LINK_ENVIRONMENT_PATH_ERROR.format(path=link))
            if link.is_symlink():
                link.unlink()
            os.symlink(development / name, link)
        (worktree / _WORKTREE_PREP_STATE_REL).unlink(missing_ok=True)
        changed.append(worktree)
    return tuple(changed)
