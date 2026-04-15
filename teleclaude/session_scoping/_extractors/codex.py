"""Codex-native session-scoping extractor."""

from __future__ import annotations

from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript import extract_effective_tool_calls

from .._types import ScopeMode
from ._common import extract_structured_paths_from_timeline

__all__ = ["collect_codex_paths"]

_CODEX_MUTATORS = {"edit", "write", "multiedit", "apply_patch", "notebookedit"}


def collect_codex_paths(
    *,
    transcript_path: str | None,
    native_session_id: str | None,
    workspace_root: str | None,
    scope_mode: ScopeMode,
) -> tuple[set[str], str]:
    """Collect Codex-owned paths from explicit structured mutators only."""
    timeline = extract_effective_tool_calls(
        transcript_path,
        AgentName.CODEX,
        native_session_id=native_session_id,
        scope="session" if scope_mode == "session_dirty" else "turn",
    )
    return (
        extract_structured_paths_from_timeline(
            timeline,
            workspace_root=workspace_root,
            allowed_tools=_CODEX_MUTATORS,
        ),
        "codex_structured",
    )
