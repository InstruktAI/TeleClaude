"""Public API orchestration for session scoping."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from ._git_strategy import resolve_git_worktree_paths
from ._native_strategy import resolve_native_scoped_paths
from ._types import ScopedPathsResult, ScopeMode
from ._workspace import resolve_workspace

logger = get_logger(__name__)

__all__ = ["resolve_scoped_paths"]


def resolve_scoped_paths(  # pylint: disable=too-many-arguments
    *,
    session_id: str,
    workspace_root: str | None,
    agent_name: str,
    scope_mode: ScopeMode,
    transcript_path: str | None = None,
    native_session_id: str | None = None,
) -> ScopedPathsResult:
    """Resolve the session-owned path set for the requested scope mode."""
    workspace = resolve_workspace(workspace_root)
    if workspace.kind == "none":
        return ScopedPathsResult(
            paths=(),
            scope_mode=scope_mode,
            workspace_kind="none",
            strategy="none",
            ledger_updated=False,
        )

    try:
        if workspace.kind == "git_worktree":
            return resolve_git_worktree_paths(
                session_id=session_id,
                workspace_root=workspace.root or "",
                agent_name=agent_name,
                scope_mode=scope_mode,
            )
        return resolve_native_scoped_paths(
            workspace=workspace,
            agent_name=agent_name,
            scope_mode=scope_mode,
            transcript_path=transcript_path,
            native_session_id=native_session_id,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Session scoping failed",
            session_id=session_id,
            workspace_root=workspace_root or "",
            agent=agent_name,
            scope_mode=scope_mode,
            workspace_kind=workspace.kind,
            error=str(exc),
            exc_info=True,
        )
        return ScopedPathsResult(
            paths=(),
            scope_mode=scope_mode,
            workspace_kind=workspace.kind,
            strategy="error",
            ledger_updated=False,
        )
