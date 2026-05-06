"""Public session-scoping API.

Single canonical mechanism: the per-agent transcript extractor returns
files mutated by the agent in the requested scope. The transcript is the
source of truth, regardless of workspace kind.
"""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from ._extractors import resolve_extractor
from ._types import ScopedPathsResult, ScopeMode
from ._workspace import resolve_workspace

logger = get_logger(__name__)

__all__ = ["resolve_scoped_paths"]


def resolve_scoped_paths(
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
        extractor = resolve_extractor(agent_name)
        native_paths, strategy = extractor(
            transcript_path=transcript_path,
            native_session_id=native_session_id,
            workspace_root=workspace.root,
            scope_mode=scope_mode,
        )
        return ScopedPathsResult(
            paths=tuple(sorted(native_paths)),
            scope_mode=scope_mode,
            workspace_kind=workspace.kind,
            strategy=strategy,
            ledger_updated=False,
        )
    except Exception as exc:
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
