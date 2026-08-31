"""Canonical TeleClaude path-root resolution."""

from __future__ import annotations

import os
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path

from teleclaude.config.context_root import resolve_context_root
from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.project_state import resolve_project_state_root

DOC_LAYER_PATTERN = "docs/**"

__all__ = [
    "DOC_LAYER_PATTERN",
    "forbidden_slug_worktree_doc_paths",
    "is_integration_worktree",
    "is_project_checkout",
    "is_slug_worktree",
    "resolve_git_root",
    "resolve_invocation_cwd",
    "resolve_invocation_project_root",
    "resolve_project_root",
    "resolve_workspace_root",
]


def resolve_invocation_cwd() -> Path:
    """Return the user's actual invocation directory.

    The ``bin/telec`` wrapper uses ``uv run --directory "$INSTALL_DIR"`` so
    that uv can resolve the virtualenv from TeleClaude's installation root.
    That flag also sets the Python process's cwd to the installation root,
    which means ``Path.cwd()`` no longer reflects the directory the user was
    in when they ran ``telec``. Worktree detection and project-root resolution
    silently fail because the cwd now points at the main repo, not the actual
    invocation directory.

    The wrapper mitigates by exporting ``TELEC_INVOCATION_CWD=$PWD`` before
    exec'ing uv. Handlers read that first. ``$PWD`` is the secondary
    fallback — shell-exported PWD survives across ``uv run`` because uv
    inherits the environment. ``Path.cwd()`` is the last resort for direct
    module invocations that never went through the wrapper.

    Resolution order:
    1. ``TELEC_INVOCATION_CWD`` (wrapper-exported, authoritative).
    2. ``PWD`` (shell environment, survives ``uv run --directory``).
    3. ``Path.cwd()`` (process cwd; potentially hijacked by uv).
    """
    explicit = os.environ.get("TELEC_INVOCATION_CWD")
    if explicit:
        return Path(explicit)
    pwd = os.environ.get("PWD")
    if pwd:
        return Path(pwd)
    return Path.cwd()


def resolve_invocation_project_root() -> Path:
    """Return the canonical main project root for the current invocation.

    Normalizes the invocation cwd — which may be a todo worktree or a subdir —
    back to the owning main checkout via :func:`resolve_project_root`. Doc and
    other shared-state lookups resolve against main's artifacts, which are the
    only place those artifacts live; a worktree never carries a generated index.
    """
    return resolve_project_root(resolve_invocation_cwd())


def resolve_workspace_root(start: str | Path) -> Path:
    """Return the checkout/worktree root where commands should execute.

    Walks up from ``start`` to find the nearest TeleClaude project checkout by
    locating ``teleclaude.yml``. In todo worktrees this returns the worktree
    root, not the main checkout.
    """
    context = resolve_context_root(Path(start))
    if context is None:
        raise FileNotFoundError("No anchoring configuration declaration found in directory hierarchy")
    return context.path


def resolve_git_root(start: str | Path) -> Path:
    """Return the active Git checkout root where file operations should run.

    Linked worktrees carry ``.git`` as a gitdir file; for code and quality
    operations the checkout root is the directory containing that file, not the
    main repository that owns the shared Git metadata.
    """
    current = Path(start).expanduser().resolve()
    if current.is_file():
        current = current.parent
    original = current

    while current != current.parent:
        git_path = current / ".git"
        if git_path.is_dir() or git_path.is_file():
            return current
        current = current.parent

    return original


def resolve_project_root(start: str | Path) -> Path:
    """Return the canonical main project root where shared state lives, or raise.

    Accepts a path at the repo root, inside the repo, or inside a git worktree
    (worktree-aware: a linked worktree's ``.git`` file resolves back to the
    owning main checkout, never the worktree itself). The resolved root must
    also carry ``teleclaude.yml`` — proof it is a genuine TeleClaude project
    checkout, not merely any git repository. Raises ``FileNotFoundError`` in
    every failure case; there is no fallback to the provided path. Untrusted
    caller-supplied cwd (todo API boundaries, CLI commands) must resolve
    through this function so a mis-resolved cwd fails loud instead of
    silently materializing or reading a stray state store.
    """
    return resolve_project_state_root(start)


def is_integration_worktree(root: Path) -> bool:
    """Return True when root is the integrator's fold worktree (trees/_integration).

    `is_worktree` (and the `WorkspaceScopeKind.WORKTREE` it drives in
    `code.py`) is true for both a slug worktree and `trees/_integration` — the
    integrator's own fold worktree, which legitimately commits `docs/**` when
    landing the doc layer and legitimately deploys via `telec sync`. Shared
    home for the slug-vs-integration boundary so `code.py` and `misc.py` guards
    cannot drift apart.
    """
    return root.parent.name == WORKTREE_DIR and root.name == "_integration"


def is_slug_worktree(root: Path) -> bool:
    """Return True when root is a todo slug worktree (trees/<slug>, not trees/_integration)."""
    return root.parent.name == WORKTREE_DIR and not is_integration_worktree(root)


def forbidden_slug_worktree_doc_paths(root: Path, paths: Iterable[str]) -> tuple[str, ...]:
    """Return doc-layer paths that a slug worktree may not commit."""
    if not is_slug_worktree(root):
        return ()
    return tuple(path for path in paths if fnmatch(path, DOC_LAYER_PATTERN))


def is_project_checkout(start: str | Path) -> bool:
    """Return whether ``start`` resolves to a genuine TeleClaude project checkout.

    ``True`` exactly when :func:`resolve_project_root` succeeds for ``start``;
    ``False`` when it raises ``FileNotFoundError``. Callers that must decide
    whether to request a checkout-owned resource (a todo store, for example)
    for a directory that exists but may not be a checkout use this predicate
    instead of re-testing ``teleclaude.yml`` inline, so the checkout invariant
    stays owned in one place.
    """
    try:
        resolve_project_root(start)
    except FileNotFoundError:
        return False
    return True
