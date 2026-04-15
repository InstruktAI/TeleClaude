"""Native/shared workspace routing for session scoping."""

from __future__ import annotations

from ._extractors import resolve_extractor
from ._git_strategy import collect_git_dirty_paths
from ._types import ResolvedWorkspace, ScopedPathsResult, ScopeMode

__all__ = ["resolve_native_scoped_paths"]


def resolve_native_scoped_paths(
    *,
    workspace: ResolvedWorkspace,
    agent_name: str,
    scope_mode: ScopeMode,
    transcript_path: str | None,
    native_session_id: str | None,
) -> ScopedPathsResult:
    """Resolve scoped paths for shared-git and non-git workspaces."""
    if workspace.kind in {"git_shared", "non_git"} and scope_mode == "workspace_dirty":
        return ScopedPathsResult(
            paths=(),
            scope_mode=scope_mode,
            workspace_kind=workspace.kind,
            strategy="unsupported_mode",
            ledger_updated=False,
        )

    extractor = resolve_extractor(agent_name)
    native_paths, strategy = extractor(
        transcript_path=transcript_path,
        native_session_id=native_session_id,
        workspace_root=workspace.root,
        scope_mode=scope_mode,
    )

    if workspace.kind == "git_shared":
        dirty_paths = collect_git_dirty_paths(workspace.root or "")
        native_paths &= dirty_paths

    return ScopedPathsResult(
        paths=tuple(sorted(native_paths)),
        scope_mode=scope_mode,
        workspace_kind=workspace.kind,
        strategy=strategy,
        ledger_updated=False,
    )
