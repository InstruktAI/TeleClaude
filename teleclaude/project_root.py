"""Resolve command roots by the rules in projects/teleclaude/design/architecture/command-scope."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from teleclaude.config.context_root import resolve_context_root
from teleclaude.config.schema import ConfigKind
from teleclaude.constants import AGENT_ARTIFACT_SOURCE_GLOBS
from teleclaude.core.project_state import resolve_owning_checkout, resolve_project_state_root
from teleclaude.core.worktree_layout import (
    is_integration_worktree as _is_integration_worktree,
)
from teleclaude.core.worktree_layout import (
    is_slug_worktree as _is_slug_worktree,
)
from teleclaude.core.worktree_layout import (
    worktree_home_for_checkout,
)
from teleclaude.paths import TELECLAUDE_HOME

DOC_LAYER_PATTERN = "docs/**"
_PROJECT_ROOT_ERROR = "cwd does not resolve to a project checkout: {invocation_dir}"

__all__ = [
    "AGENT_ARTIFACT_SOURCE_GLOBS",
    "DOC_LAYER_PATTERN",
    "declaration_root",
    "forbidden_slug_worktree_agent_artifact_paths",
    "forbidden_slug_worktree_doc_paths",
    "is_integration_worktree",
    "is_project_checkout",
    "is_slug_worktree",
    "resolve_git_root",
    "resolve_invocation_cwd",
    "resolve_invocation_roots",
    "resolve_owning_checkout",
    "resolve_project_root",
    "worktree_home_root",
]


@dataclass(frozen=True)
class InvocationRoots:
    """Roots selected from the invocation directory and its declared context."""

    context_root: Path | None
    repository_root: Path
    invocation_dir: Path
    context_kind: ConfigKind | None

    def adoption_root(self) -> Path:
        """Return the owning checkout, or let project init adopt a fresh directory before it has a Git checkout."""
        return resolve_owning_checkout(self.invocation_dir) or self.invocation_dir

    def require_project_root(self) -> Path:
        """Return shared project state for project contexts, otherwise fail with the invocation path."""
        if self.context_kind is not ConfigKind.PROJECT or self.context_root is None:
            raise FileNotFoundError(_PROJECT_ROOT_ERROR.format(invocation_dir=self.invocation_dir))
        return resolve_project_state_root(self.context_root)

    def require_commit_boundary_root(self) -> Path:
        """Return project shared state or the platform home for commit-boundary maintenance."""
        if self.context_kind is ConfigKind.PROJECT:
            return self.require_project_root()
        if (
            self.context_kind is ConfigKind.GLOBAL
            and self.context_root is not None
            and self.context_root.expanduser().resolve() == TELECLAUDE_HOME.expanduser().resolve()
        ):
            return self.context_root
        raise FileNotFoundError(_PROJECT_ROOT_ERROR.format(invocation_dir=self.invocation_dir))


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
    explicit = os.environ.get("TELEC_INVOCATION_CWD")  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
    if explicit:
        return Path(explicit)
    pwd = os.environ.get("PWD")  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
    if pwd:
        return Path(pwd)
    return Path.cwd()


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


def resolve_invocation_roots(start: str | Path | None = None) -> InvocationRoots:
    """Resolve the invocation directory, declared context, and containing repository."""
    invocation_path = resolve_invocation_cwd() if start is None else Path(start)
    context = resolve_context_root(invocation_path)
    return InvocationRoots(
        context_root=context.path if context is not None else None,
        repository_root=resolve_git_root(invocation_path),
        invocation_dir=invocation_path,
        context_kind=context.kind if context is not None else None,
    )


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

    `is_linked_worktree` (and the `WorkspaceScopeKind.WORKTREE` it drives in
    `code.py`) is true for both a slug worktree and `trees/_integration` — the
    integrator's own fold worktree, which legitimately commits `docs/**` when
    landing the doc layer. Shared home for the slug-vs-integration boundary so
    code-path checks cannot drift apart.
    """
    return _is_integration_worktree(root)


def is_slug_worktree(root: Path) -> bool:
    """Return True when root is a todo slug worktree (trees/<slug>, not trees/_integration)."""
    return _is_slug_worktree(root)


def worktree_home_root(root: Path) -> Path | None:
    """Return the home clone path for a slug worktree checkout."""
    return worktree_home_for_checkout(root)


def declaration_root(context_root: Path) -> Path:
    """Return the checkout whose declaration governs this invocation.

    A slug worktree carries a branch copy of the project declaration that is not
    authoritative for daemon-facing configuration: the tier and subscriptions an
    invocation answers to belong to the owning checkout. The integration worktree
    is the exception, because its copy is not a proposal — it holds origin/main
    plus the merge under way, so it is the declaration about to be canonical, and
    the owning checkout's copy is the superseded one. Contexts that are not linked
    worktrees answer for themselves, so global, person, and nested contexts
    resolve unchanged.
    """
    if not is_slug_worktree(context_root):
        return context_root
    return resolve_project_root(context_root)


def forbidden_slug_worktree_doc_paths(root: Path, paths: Iterable[str]) -> tuple[str, ...]:
    """Return doc-layer paths that a slug worktree may not commit."""
    if not is_slug_worktree(root):
        return ()
    return tuple(path for path in paths if fnmatch(path, DOC_LAYER_PATTERN))


def forbidden_slug_worktree_agent_artifact_paths(root: Path, paths: Iterable[str]) -> tuple[str, ...]:
    """Return agent-artifact source paths that a slug worktree may not commit."""
    if not is_slug_worktree(root):
        return ()
    return tuple(path for path in paths if any(fnmatch(path, pattern) for pattern in AGENT_ARTIFACT_SOURCE_GLOBS))


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
