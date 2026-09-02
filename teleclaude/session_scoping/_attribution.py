"""Strict timestamped attribution for captured foreign sessions."""

from __future__ import annotations

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.codex_transcript import discover_codex_transcript_path
from teleclaude.core.models import Session
from teleclaude.utils.transcript import extract_effective_tool_calls

from ._extractors._common import extract_touch_evidence_from_timeline
from ._extractors.claude import collect_claude_touch_evidence
from ._extractors.gemini import collect_gemini_touch_evidence
from ._types import AttributionSignal, SessionAttributionResult, TouchEvidence

logger = get_logger(__name__)

_STRUCTURED_MUTATORS = {
    AgentName.CLAUDE: {"write", "edit"},
    AgentName.CODEX: {"edit", "write", "multiedit", "apply_patch", "notebookedit"},
    AgentName.DEEPSEEK: {"write", "edit"},
    AgentName.GEMINI: {"edit", "writefile"},
}
_SHELL_MUTATORS = {"bash", "shell", "terminal", "run_shell_command", "exec_command"}
_UNDETERMINED_STRATEGY = "foreign_transcript_undetermined"
_ATTRIBUTION_DEGRADE_LOG = "Foreign transcript attribution failed; marking session undetermined"


def resolve_session_attribution(
    session: Session,
    *,
    workspace_root: str,
) -> SessionAttributionResult:
    """Resolve foreign-session mutation evidence without legacy empty-scope fallback."""
    agent_raw = (session.active_agent or "").strip()
    try:
        agent = AgentName.from_str(agent_raw)
    except ValueError:
        return SessionAttributionResult(AttributionSignal.UNDETERMINED, (), _UNDETERMINED_STRATEGY)

    transcript_path = (session.native_log_file or "").strip()
    if not transcript_path and agent is AgentName.CODEX and session.native_session_id:
        transcript_path = discover_codex_transcript_path(session.native_session_id) or ""
    if not transcript_path or not Path(transcript_path).is_file():
        return SessionAttributionResult(AttributionSignal.UNDETERMINED, (), _UNDETERMINED_STRATEGY)

    try:
        timeline = extract_effective_tool_calls(
            transcript_path,
            agent,
            native_session_id=session.native_session_id,
            scope="session",
        )
        if not timeline.has_data:
            return SessionAttributionResult(AttributionSignal.UNDETERMINED, (), _UNDETERMINED_STRATEGY)
        raw_touches = extract_touch_evidence_from_timeline(
            timeline,
            workspace_root=workspace_root,
            structured_tools=_STRUCTURED_MUTATORS[agent],
            shell_tools=_SHELL_MUTATORS,
        )
        touches = {TouchEvidence(path=path, touched_at=touched_at) for path, touched_at in raw_touches}
        if agent is AgentName.CLAUDE:
            touches.update(
                collect_claude_touch_evidence(transcript_path=transcript_path, workspace_root=workspace_root)
            )
        if agent is AgentName.GEMINI:
            touches.update(
                collect_gemini_touch_evidence(transcript_path=transcript_path, workspace_root=workspace_root)
            )
    except Exception:
        # A bad foreign transcript cannot prevent ownership resolution for every other live session.
        logger.debug(_ATTRIBUTION_DEGRADE_LOG, exc_info=True)
        return SessionAttributionResult(AttributionSignal.UNDETERMINED, (), _UNDETERMINED_STRATEGY)

    ordered_touches = tuple(sorted(touches, key=lambda touch: (touch.touched_at, touch.path)))
    return SessionAttributionResult(AttributionSignal.RESOLVED, ordered_touches, f"{agent.value}_strict")
