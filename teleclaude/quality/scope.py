"""Shared scope utilities for quality tooling.

Workspace scope resolution, language detection, and path validation used by
code, lint, and test commands.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from teleclaude.git import GitCommandError, Repo
from teleclaude.session_identity import get_session_id  # deferred: heavy transitive imports
from teleclaude.todo_scaffold import (  # deferred: heavy transitive imports
    NoSessionTouchedFiles,
    collect_session_touched_files,
)

logger = logging.getLogger(__name__)

_PYTHON_EXTENSIONS = (".py", ".pyi")
_TYPESCRIPT_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_MARKDOWN_EXTENSIONS = (".md",)
_PRETTIER_EXTENSIONS = (
    ".md",
    ".mdx",
    ".yaml",
    ".yml",
    ".json",
    ".jsonc",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
)
_ROOT_RUST_METADATA = {"Cargo.toml", "Cargo.lock", "rust-toolchain.toml"}


class WorkspaceScopeKind(Enum):
    WORKTREE = "worktree"
    SHARED_BRANCH = "shared_branch"


class DirtyOp(Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass(frozen=True)
class DirtyPath:
    path: str
    op: DirtyOp


@dataclass(frozen=True)
class WorkspaceScopeResolution:
    """Resolved workspace scope.

    ``dirty_paths`` is the full dirty set. ``scoped_dirty_paths`` is the
    workspace-owned dirty subset, including deletions, for staging and index
    checks. ``scoped_existing_paths`` excludes deletions and missing paths for
    tools that require filesystem targets.
    """

    kind: WorkspaceScopeKind
    has_session_identity: bool
    dirty_paths: tuple[DirtyPath, ...]
    scoped_dirty_paths: tuple[str, ...]
    scoped_existing_paths: tuple[str, ...]


class RustScopeKind(Enum):
    EMPTY = "empty"
    PACKAGE = "package"
    WORKSPACE = "workspace"


@dataclass(frozen=True)
class RustScope:
    kind: RustScopeKind
    workspace_root: Path | None
    package: str | None = None
    rust_owned_paths: tuple[str, ...] = ()
    unresolved_paths: tuple[str, ...] = ()


class CargoWorkspaceError(RuntimeError):
    """Raised when Rust is configured but the Cargo workspace root is missing."""

    def __init__(self, manifest_path: Path) -> None:
        self.manifest_path = manifest_path
        super().__init__(f"Cargo workspace manifest not found: {manifest_path}")


def is_worktree(project_root: Path) -> bool:
    """Check if the project is in a git worktree (not the main repo).

    Compares git rev-parse --git-common-dir vs --git-dir. In a worktree
    these differ; in the main repo they are identical.

    Justified subprocess: git plumbing has no Python API.
    """
    try:
        git_common = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        git_dir = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return git_common != git_dir
    except subprocess.CalledProcessError:
        return False


def resolve_workspace_scope_resolution(project_root: Path) -> WorkspaceScopeResolution:
    """Resolve dirty workspace metadata and action-ready scoped paths."""
    dirty_paths = _resolve_dirty_paths(project_root)
    session_id = get_session_id()
    has_session_identity = bool(session_id)

    if is_worktree(project_root):
        return WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.WORKTREE,
            has_session_identity=has_session_identity,
            dirty_paths=dirty_paths,
            scoped_dirty_paths=tuple(dirty.path for dirty in dirty_paths),
            scoped_existing_paths=_existing_dirty_paths(project_root, dirty_paths),
        )

    if not session_id:
        return WorkspaceScopeResolution(
            kind=WorkspaceScopeKind.SHARED_BRANCH,
            has_session_identity=False,
            dirty_paths=dirty_paths,
            scoped_dirty_paths=(),
            scoped_existing_paths=(),
        )

    touched = _resolve_session_touched_paths(project_root)
    dirty_path_set = {dirty.path for dirty in dirty_paths}
    dirty_existing = set(_existing_dirty_paths(project_root, dirty_paths))
    # Scope is strictly (this session's touched paths) ∩ (currently dirty paths).
    # We do NOT union in ALL deleted-in-working-tree paths: doing so leaks
    # foreign deletions into this session's scope (agent A deletes foo.py;
    # agent B's scope picks up the deletion and B's commit silently records
    # A's work). If a Bash-based `rm` falls out of the transcript-touched
    # extractor, the agent must declare the deletion explicitly with
    # `telec code commit --approved '<msg>' --include <deleted-path>`; the
    # include path is the sanctioned channel for "I deleted this; my
    # transcript didn't capture it."
    scoped_dirty = tuple(sorted(set(touched) & dirty_path_set))
    scoped = tuple(sorted(path for path in touched if path in dirty_existing))
    return WorkspaceScopeResolution(
        kind=WorkspaceScopeKind.SHARED_BRANCH,
        has_session_identity=True,
        dirty_paths=dirty_paths,
        scoped_dirty_paths=scoped_dirty,
        scoped_existing_paths=scoped,
    )


def _resolve_dirty_paths(project_root: Path) -> tuple[DirtyPath, ...]:
    repo = Repo(str(project_root))
    try:
        status = repo.git.status("--porcelain", "--untracked-files=all")
    except GitCommandError as exc:
        raise RuntimeError(f"Failed to resolve dirty workspace paths: {exc}") from exc
    return tuple(_parse_dirty_status_line(line) for line in status.splitlines() if len(line) > 3)


def _parse_dirty_status_line(line: str) -> DirtyPath:
    status_code = line[:2]
    raw_path = line[3:].strip()
    path = raw_path.rsplit(" -> ", maxsplit=1)[-1]
    if "D" in status_code:
        op = DirtyOp.DELETED
    elif status_code == "??" or "A" in status_code:
        op = DirtyOp.ADDED
    else:
        op = DirtyOp.MODIFIED
    return DirtyPath(path=path, op=op)


def _existing_dirty_paths(project_root: Path, dirty_paths: tuple[DirtyPath, ...]) -> tuple[str, ...]:
    return tuple(
        dirty.path for dirty in dirty_paths if dirty.op is not DirtyOp.DELETED and (project_root / dirty.path).exists()
    )


def _resolve_session_touched_paths(project_root: Path) -> tuple[str, ...]:
    try:
        touched: set[str] = collect_session_touched_files(str(project_root))
    except NoSessionTouchedFiles:
        # Transcript yields no signal (e.g. integrator session, fresh shell, or
        # a human staging files manually). Empty scope lets the caller fall
        # back to whatever's pre-staged instead of crashing.
        return ()
    except Exception as exc:
        raise RuntimeError(f"Failed to collect session-touched files: {exc}") from exc
    return tuple(sorted(touched))


_FRONTEND_CANDIDATES = ("frontend", "web", "client", "src")


def get_project_languages(project_root: Path) -> list[str]:
    """Detect project languages from repo artifacts.

    Python: pyproject.toml, setup.py, or root *.py files.
    TypeScript: tsconfig.json or package.json with a typescript dep. When
    teleclaude.yml specifies frontend_root, that directory is checked first
    (authoritative); otherwise _FRONTEND_CANDIDATES are searched.
    Rust: Cargo.toml.
    """
    languages: list[str] = []

    if (project_root / "pyproject.toml").exists() or (project_root / "setup.py").exists():
        languages.append("python")
    elif any(project_root.glob("*.py")):
        languages.append("python")

    frontend_root: str | None = None
    config_path = project_root / "teleclaude.yml"
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            frontend_root = data.get("frontend_root") or None

    if _detect_typescript(project_root, frontend_root=frontend_root):
        languages.append("typescript")

    if (project_root / "Cargo.toml").exists():
        languages.append("rust")

    return languages


def _detect_typescript(project_root: Path, *, frontend_root: str | None = None) -> bool:
    """Return True if TypeScript indicators are found at or under the project root.

    When frontend_root is supplied (from teleclaude.yml), it is checked first.
    The generic _FRONTEND_CANDIDATES then cover conventional layouts.
    """
    if (project_root / "tsconfig.json").exists():
        return True

    def _check_dir(candidate_dir: Path) -> bool:
        if not candidate_dir.is_dir():
            return False
        if (candidate_dir / "tsconfig.json").exists():
            return True
        pkg = candidate_dir / "package.json"
        if pkg.exists():
            pkg_data = json.loads(pkg.read_text(encoding="utf-8"))
            deps = pkg_data.get("dependencies", {})
            dev_deps = pkg_data.get("devDependencies", {})
            if "typescript" in deps or "typescript" in dev_deps:
                return True
        return False

    if frontend_root and _check_dir(project_root / frontend_root):
        return True

    for candidate in _FRONTEND_CANDIDATES:
        if frontend_root and candidate == frontend_root:
            continue  # already checked above
        if _check_dir(project_root / candidate):
            return True

    return False


def python_files(paths: list[str]) -> list[str]:
    """Return only Python targets from *paths*.

    Directories are passed through unchanged — ruff and pyright recurse into
    them. Only individual file paths are filtered by extension.
    """
    return [path for path in paths if Path(path).is_dir() or path.endswith(_PYTHON_EXTENSIONS)]


def typescript_files(paths: list[str]) -> list[str]:
    """Return only JavaScript/TypeScript targets from *paths*."""
    return [path for path in paths if path.endswith(_TYPESCRIPT_EXTENSIONS)]


def markdown_files(paths: list[str]) -> list[str]:
    """Return only Markdown targets from *paths*.

    Directories are not passed through — markdown.py expects file paths and
    the full-run path uses repo-wide scanning rather than dir targets.
    """
    return [path for path in paths if path.endswith(_MARKDOWN_EXTENSIONS)]


def prettier_files(paths: list[str]) -> list[str]:
    """Return only files owned by prettier from *paths*."""
    return [path for path in paths if path.endswith(_PRETTIER_EXTENSIONS)]


def rust_files(paths: list[str]) -> list[str]:
    """Return paths owned by Rust/Cargo quality tooling."""
    return [path for path in paths if _is_rust_owned_path(_as_posix(path))]


def resolve_cargo_workspace_root(project_root: Path) -> Path:
    """Resolve the Cargo workspace root from the root Cargo.toml."""
    manifest_path = project_root / "Cargo.toml"
    if not manifest_path.exists():
        raise CargoWorkspaceError(manifest_path)
    return manifest_path.parent


def resolve_rust_scope(project_root: Path, paths: list[str], *, run_all: bool = False) -> RustScope:
    """Resolve changed Rust paths to Cargo package or workspace scope."""
    normalized_paths = [_project_relative_path(project_root, path) for path in paths]
    owned_paths = tuple(rust_files(normalized_paths))

    if run_all:
        workspace_root = resolve_cargo_workspace_root(project_root)
        return RustScope(
            kind=RustScopeKind.WORKSPACE,
            workspace_root=workspace_root,
            rust_owned_paths=owned_paths,
        )

    if not owned_paths:
        return RustScope(kind=RustScopeKind.EMPTY, workspace_root=None)

    workspace_root = resolve_cargo_workspace_root(project_root)
    packages: set[str] = set()
    unresolved_paths: list[str] = []

    for path in owned_paths:
        if _is_root_rust_metadata(path):
            return RustScope(
                kind=RustScopeKind.WORKSPACE,
                workspace_root=workspace_root,
                rust_owned_paths=owned_paths,
            )
        package_name = _resolve_package_for_rust_path(project_root, path)
        if package_name is None:
            unresolved_paths.append(path)
            continue
        packages.add(package_name)

    if unresolved_paths:
        logger.warning("Rust paths with unresolved Cargo ownership force workspace scope: %s", unresolved_paths)
        return RustScope(
            kind=RustScopeKind.WORKSPACE,
            workspace_root=workspace_root,
            rust_owned_paths=owned_paths,
            unresolved_paths=tuple(unresolved_paths),
        )

    if len(packages) == 1:
        return RustScope(
            kind=RustScopeKind.PACKAGE,
            workspace_root=workspace_root,
            package=next(iter(packages)),
            rust_owned_paths=owned_paths,
        )

    return RustScope(
        kind=RustScopeKind.WORKSPACE,
        workspace_root=workspace_root,
        rust_owned_paths=owned_paths,
    )


def _project_relative_path(project_root: Path, path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(project_root.resolve()).as_posix()
        except ValueError:
            return candidate.as_posix()
    return _as_posix(path)


def _as_posix(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def _is_rust_owned_path(path: str) -> bool:
    parts = Path(path).parts
    return (
        path.endswith(".rs")
        or _is_root_rust_metadata(path)
        or _is_crate_manifest(parts)
        or _is_crate_migration(parts, path)
    )


def _is_root_rust_metadata(path: str) -> bool:
    return path in _ROOT_RUST_METADATA


def _is_crate_manifest(parts: tuple[str, ...]) -> bool:
    return len(parts) == 3 and parts[0] == "crates" and parts[2] == "Cargo.toml"


def _is_crate_migration(parts: tuple[str, ...], path: str) -> bool:
    return len(parts) >= 4 and parts[0] == "crates" and parts[2] == "migrations" and path.endswith(".sql")


def _resolve_package_for_rust_path(project_root: Path, path: str) -> str | None:
    parts = Path(path).parts
    if len(parts) < 3 or parts[0] != "crates":
        return None
    manifest_path = project_root / "crates" / parts[1] / "Cargo.toml"
    if not manifest_path.exists():
        return None
    with open(manifest_path, "rb") as f:
        data = tomllib.load(f)
    package_name = data.get("package", {}).get("name")
    if not isinstance(package_name, str) or not package_name:
        return None
    return package_name


def validate_scoped_paths(paths: list[str], project_root: Path) -> list[str]:
    """Return project-relative paths that stay inside *project_root*.

    Security boundary: prevents traversal, sibling-prefix escapes, and
    leading-dash paths from entering make argv, subprocess argv, or git
    pathspecs.
    """
    safe: list[str] = []
    root = project_root.resolve()
    for raw_path in paths:
        if raw_path.startswith("-"):
            logger.warning("Rejected leading-dash path from workspace scope: %s", raw_path)
            continue

        candidate = Path(raw_path)
        resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            logger.warning("Rejected path outside project root: %s", raw_path)
            continue
        if relative.as_posix().startswith("-"):
            logger.warning("Rejected leading-dash path from workspace scope: %s", raw_path)
            continue
        safe.append(relative.as_posix())
    return safe
