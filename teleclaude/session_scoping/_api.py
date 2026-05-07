"""Public session-scoping API.

Single canonical mechanism: the per-agent transcript extractor returns
files mutated by the agent. When a turn anchor SHA is supplied, the
result is intersected with `git diff <anchor>` so the path set reflects
exactly what changed in this turn — covering both uncommitted edits and
in-turn commits.
"""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from ._extractors import resolve_extractor
from ._git import paths_changed_since
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
    turn_anchor_sha: str | None = None,
) -> ScopedPathsResult:
    """Resolve the session-owned path set for the requested scope mode.

    When `turn_anchor_sha` is supplied with `scope_mode="turn_delta"`, the
    extractor runs in cumulative session mode and the result is intersected
    with `git diff <anchor>` — capturing every path changed since turn-start
    regardless of whether it was committed in-turn or remains uncommitted.
    """
    workspace = resolve_workspace(workspace_root)
    if workspace.kind == "none":
        return ScopedPathsResult(
            paths=(),
            scope_mode=scope_mode,
            workspace_kind="none",
            strategy="none",
            ledger_updated=False,
        )

    use_anchor = bool(turn_anchor_sha) and scope_mode == "turn_delta" and workspace.root is not None

    try:
        extractor = resolve_extractor(agent_name)
        extractor_mode: ScopeMode = "session_dirty" if use_anchor else scope_mode
        native_paths, strategy = extractor(
            transcript_path=transcript_path,
            native_session_id=native_session_id,
            workspace_root=workspace.root,
            scope_mode=extractor_mode,
        )

        if use_anchor:
            assert turn_anchor_sha is not None
            assert workspace.root is not None
            diff_paths = paths_changed_since(workspace.root, turn_anchor_sha)
            scoped_paths = native_paths & diff_paths
            strategy = f"{strategy}+anchor_diff"
        else:
            scoped_paths = native_paths

        return ScopedPathsResult(
            paths=tuple(sorted(scoped_paths)),
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
