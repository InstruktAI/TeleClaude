"""DeepSeek Harness native session-scoping extractor.

DSH sessions persist as zstd-compressed JSONL under ``~/.dsh/sessions``; the
shared timeline extractor (``extract_effective_tool_calls``) already parses
them into normalized tool-use records, so this extractor reuses the common
structured/shell path collectors with DSH's mutator vocabulary.
"""

from __future__ import annotations

from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript import extract_effective_tool_calls

from .._types import ScopeMode
from ._common import extract_shell_paths_from_timeline, extract_structured_paths_from_timeline

__all__ = ["collect_deepseek_paths"]

_DSH_STRUCTURED_MUTATORS = {"write", "edit"}
_DSH_SHELL_MUTATORS = {"bash", "shell", "terminal", "run_shell_command", "exec_command"}


def collect_deepseek_paths(
    *,
    transcript_path: str | None,
    native_session_id: str | None = None,
    workspace_root: str | None,
    scope_mode: ScopeMode,
) -> tuple[set[str], str]:
    """Collect DSH-owned paths from normalized tool-use events."""
    del native_session_id
    if not transcript_path:
        return set(), "deepseek_structured_fallback"

    timeline = extract_effective_tool_calls(
        transcript_path,
        AgentName.DEEPSEEK,
        scope="session" if scope_mode == "session_dirty" else "turn",
    )
    return (
        extract_structured_paths_from_timeline(
            timeline,
            workspace_root=workspace_root,
            allowed_tools=_DSH_STRUCTURED_MUTATORS,
        )
        | extract_shell_paths_from_timeline(
            timeline,
            workspace_root=workspace_root,
            allowed_tools=_DSH_SHELL_MUTATORS,
        ),
        "deepseek_structured_fallback",
    )
