"""Git-backed path collection for isolated worktree scoping."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.git import Repo

from ._store import current_timestamp, load_workspace_ledger, save_workspace_ledger
from ._types import ScopedPathsResult, ScopeMode, WorkspaceScopeLedger

logger = get_logger(__name__)

__all__ = ["collect_git_dirty_paths", "resolve_git_worktree_paths"]


def _paths_from_porcelain(status_output: str) -> set[str]:
    """Parse git --porcelain output into the current changed-path set."""
    paths: set[str] = set()
    for line in status_output.rstrip().splitlines():
        if len(line) < 4:
            continue
        filepath = line[3:].strip()
        if " -> " in filepath:
            filepath = filepath.split(" -> ", 1)[1]
        if filepath:
            paths.add(filepath)
    return paths


def collect_git_dirty_paths(workspace_root: str) -> set[str]:
    """Return the full current dirty-path set for a git workspace."""
    repo = Repo(workspace_root)
    status_output = repo.git.status("--porcelain", "--untracked-files=all")
    return _paths_from_porcelain(status_output)


def _build_result(
    *,
    paths: set[str],
    scope_mode: ScopeMode,
    ledger_updated: bool,
) -> ScopedPathsResult:
    return ScopedPathsResult(
        paths=tuple(sorted(paths)),
        scope_mode=scope_mode,
        workspace_kind="git_worktree",
        strategy="git_worktree",
        ledger_updated=ledger_updated,
    )


def resolve_git_worktree_paths(
    *,
    session_id: str,
    workspace_root: str,
    agent_name: str,
    scope_mode: ScopeMode,
) -> ScopedPathsResult:
    """Resolve scoped paths for an isolated git worktree."""
    current_paths = collect_git_dirty_paths(workspace_root)
    if scope_mode in {"workspace_dirty", "session_dirty"}:
        return _build_result(paths=current_paths, scope_mode=scope_mode, ledger_updated=False)

    existing_ledger = load_workspace_ledger(session_id, workspace_root)
    seen_paths = set(existing_ledger.seen_paths) if existing_ledger is not None else set()
    new_paths = current_paths - seen_paths
    updated_seen_paths = tuple(sorted(seen_paths | current_paths))
    should_persist = existing_ledger is None or tuple(existing_ledger.seen_paths) != updated_seen_paths

    ledger_updated = False
    if should_persist:
        try:
            save_workspace_ledger(
                session_id,
                WorkspaceScopeLedger(
                    workspace_root=workspace_root,
                    workspace_kind="git_worktree",
                    strategy="git_worktree",
                    agent=agent_name,
                    seen_paths=updated_seen_paths,
                    last_updated=current_timestamp(),
                ),
            )
            ledger_updated = True
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Ledger write failed, returning paths without persistence",
                session_id=session_id,
                workspace_root=workspace_root,
                exc_info=True,
            )

    return _build_result(paths=new_paths, scope_mode=scope_mode, ledger_updated=ledger_updated)
