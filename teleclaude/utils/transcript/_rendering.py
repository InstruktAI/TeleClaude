"""Transcript rendering: convert entries to markdown, parse agent transcripts."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from teleclaude.core.agents import AgentName
from teleclaude.core.models import JsonDict

from ._block_renderers import (
    _extract_tool_subject,
    _process_entry,
    _process_tool_result_block,
    _process_tool_use_block,
    _should_skip_entry,
)
from ._iterators import (
    _get_entries_for_agent,
    _iter_claude_entries,
    _iter_codex_entries,
    _iter_gemini_entries,
    _start_index_after_timestamp_or_rotation,
)
from ._parsers import normalize_transcript_entry_message
from ._utils import _apply_tail_limit, _apply_tail_limit_codex, _format_thinking, _parse_timestamp

logger = logging.getLogger(__name__)


def parse_claude_transcript(
    transcript_path: str,
    title: str,
    since_timestamp: str | None = None,
    until_timestamp: str | None = None,
    tail_chars: int = 2000,
    collapse_tool_results: bool = False,
) -> str:
    """Convert Claude Code JSONL transcript to markdown with filtering.

    guard: allow-string-compare

    Args:
        transcript_path: Path to Claude session .jsonl file
        title: Session title for header
        since_timestamp: Optional ISO 8601 UTC start filter (inclusive)
        until_timestamp: Optional ISO 8601 UTC end filter (inclusive)
        tail_chars: Max characters to return from end (default 2000, 0 for unlimited)

    Returns:
        Markdown formatted conversation with timestamps on each section
    """
    path = Path(transcript_path).expanduser()
    if not path.exists():
        return f"Transcript file not found: {transcript_path}"

    try:
        entries = _iter_claude_entries(path)
        return _render_transcript_from_entries(
            entries,  # type: ignore[arg-type]
            title,
            since_timestamp,
            until_timestamp,
            tail_chars,
            collapse_tool_results=collapse_tool_results,
        )
    except Exception as e:
        return f"Error parsing transcript: {e}"


def parse_codex_transcript(
    transcript_path: str,
    title: str,
    since_timestamp: str | None = None,
    until_timestamp: str | None = None,
    tail_chars: int = 2000,
    collapse_tool_results: bool = False,
) -> str:
    """Convert Codex JSONL transcript to markdown with filtering.

    guard: allow-string-compare
    """

    path = Path(transcript_path).expanduser()
    if not path.exists():
        return f"Transcript file not found: {transcript_path}"

    try:
        entries = _iter_codex_entries(path)
        return _render_transcript_from_entries(
            entries,  # type: ignore[arg-type]
            title,
            since_timestamp,
            until_timestamp,
            tail_chars,
            tail_limit_fn=_apply_tail_limit_codex,
            collapse_tool_results=collapse_tool_results,
        )
    except Exception as e:
        return f"Error parsing transcript: {e}"


def parse_gemini_transcript(
    transcript_path: str,
    title: str,
    since_timestamp: str | None = None,
    until_timestamp: str | None = None,
    tail_chars: int = 2000,
    collapse_tool_results: bool = False,
) -> str:
    """Convert Gemini JSON transcript into markdown.

    guard: allow-string-compare
    """

    path = Path(transcript_path).expanduser()
    if not path.exists():
        return f"Transcript file not found: {transcript_path}"

    try:
        entries = _iter_gemini_entries(path)
        return _render_transcript_from_entries(
            entries,  # type: ignore[arg-type]
            title,
            since_timestamp,
            until_timestamp,
            tail_chars,
            collapse_tool_results=collapse_tool_results,
        )
    except Exception as e:
        return f"Error parsing transcript: {e}"


def _last_user_boundary_start(entries: list[JsonDict]) -> int:
    """Return the index after the last user message."""
    last_user_idx = -1
    for i in range(len(entries) - 1, -1, -1):
        message = normalize_transcript_entry_message(entries[i])
        if isinstance(message, dict) and message.get("role") == "user":
            last_user_idx = i
            break
    return last_user_idx + 1


def _resolve_render_start_index(
    entries: list[JsonDict],
    transcript_path: str,
    agent_name: AgentName,
    since_timestamp: datetime | None,
    *,
    mode: str,
) -> int | None:
    """Resolve the starting entry index for incremental rendering."""
    if since_timestamp is None:
        return _last_user_boundary_start(entries)
    return _start_index_after_timestamp_or_rotation(
        entries,
        since_timestamp,
        transcript_path=transcript_path,
        agent_name=agent_name,
        mode=mode,
    )


def _append_clean_tool_use_block(
    block: JsonDict,
    lines: list[str],
) -> None:
    """Append a single clean-render tool_use block."""
    tool_name = str(block.get("name", "unknown"))
    tool_name_safe = tool_name.split("\n")[0].split("(")[0].split("{")[0].strip()

    formatted_name = f"**`{tool_name_safe}`**"
    subject = _extract_tool_subject(block)  # type: ignore[arg-type]

    base_len = len(tool_name_safe)
    if subject:
        base_len += 2
    budget = max(0, 70 - base_len)

    if subject and budget > 0:
        if len(subject) > budget:
            subject = subject[: budget - 1] + "…"
        block_content = f"{formatted_name}: `{subject}`"
    else:
        block_content = formatted_name

    if lines:
        lines.append("")
    lines.append(block_content)


def _append_clean_render_block(
    block: JsonDict,
    block_type: str,
    lines: list[str],
) -> bool:
    """Render one projected assistant block for clean output."""
    if block_type == "text":
        text = block.get("text", "")
        if text:
            if lines:
                lines.append("")
            lines.append(str(text))
            return True
        return False

    if block_type == "thinking":
        thinking = block.get("thinking", "")
        if thinking:
            if lines:
                lines.append("")
            lines.append(_format_thinking(str(thinking)))
            return True
        return False

    if block_type == "tool_use":
        _append_clean_tool_use_block(block, lines)
        return True

    return False


def _append_standard_render_block(
    block: JsonDict,
    block_type: str,
    time_prefix: str,
    lines: list[str],
) -> bool:
    """Render one projected assistant block for standard output."""
    if block_type == "text":
        text = block.get("text", "")
        if text:
            if lines:
                lines.append("")
            lines.append(f"{time_prefix}{text}")
            return True
        return False

    if block_type == "thinking":
        thinking = block.get("thinking", "")
        if thinking:
            if lines:
                lines.append("")
            lines.append(f"{time_prefix}{_format_thinking(str(thinking))}")
            return True
        return False

    if block_type == "tool_use":
        lines.append("")
        _process_tool_use_block(block, time_prefix, lines)  # type: ignore[arg-type]
        return True

    if block_type == "tool_result":
        lines.append("")
        _process_tool_result_block(
            block,  # type: ignore[arg-type]
            time_prefix,
            lines,
            collapse_tool_results=False,
            max_chars=2000,
        )
        return True

    return False


def render_clean_agent_output(
    transcript_path: str,
    agent_name: AgentName,
    since_timestamp: datetime | None = None,
) -> tuple[str | None, datetime | None]:
    """Render metadata-free markdown for assistant activity.

    Used for sequential, incremental output blocks in the UI.
    Renders thinking in italics and tool invocations in bold monospace.
    Completely omits tool results.

    Args:
        transcript_path: Path to transcript file
        agent_name: Agent name for iterator selection
        since_timestamp: Optional UTC datetime boundary.

    Returns:
        Tuple of (markdown text or None, timestamp of last rendered entry or None)
    """
    entries = _get_entries_for_agent(transcript_path, agent_name)
    if not entries:
        return None, None

    start_idx = _resolve_render_start_index(
        entries,
        transcript_path,
        agent_name,
        since_timestamp,
        mode="clean",
    )
    if start_idx is None:
        return None, None

    assistant_entries = entries[start_idx:]
    if not assistant_entries:
        return None, None

    # Route through canonical conversation projection with THREADED_CLEAN_POLICY.
    # Policy: thinking visible, tool invocations visible, tool results hidden.
    # Behavior is identical to the previous iter_assistant_blocks() iteration;
    # the projection layer now owns the visibility decision.
    from teleclaude.output_projection.conversation_projector import project_entries  # pylint: disable=C0415
    from teleclaude.output_projection.models import THREADED_CLEAN_POLICY  # pylint: disable=C0415

    lines: list[str] = []
    emitted = False
    last_entry_dt: datetime | None = None

    for pb in project_entries(assistant_entries, THREADED_CLEAN_POLICY):
        if pb.role != "assistant":
            continue  # only format assistant content blocks

        if pb.timestamp:
            entry_dt = _parse_timestamp(pb.timestamp)
            if entry_dt:
                last_entry_dt = entry_dt

        if _append_clean_render_block(pb.block, pb.block_type, lines):
            emitted = True
        # tool_result: suppressed by THREADED_CLEAN_POLICY (include_tool_results=False)

    if not emitted:
        return None, last_entry_dt

    return "\n".join(lines).strip(), last_entry_dt


def _render_transcript_from_entries(
    entries: Iterable[dict[str, object]],  # guard: loose-dict - External entries
    title: str,
    since_timestamp: str | None,
    until_timestamp: str | None,
    tail_chars: int,
    *,
    tail_limit_fn: Callable[[str, int], str] = _apply_tail_limit,
    collapse_tool_results: bool = False,
    include_thinking: bool = True,
    include_tools: bool = True,
) -> str:
    """Render markdown from normalized transcript entries."""

    since_dt = _parse_timestamp(since_timestamp) if since_timestamp else None
    until_dt = _parse_timestamp(until_timestamp) if until_timestamp else None

    lines: list[str] = [f"# {title}", ""]
    last_section: str | None = None
    emitted = False

    for entry in entries:
        if _should_skip_entry(entry, since_dt, until_dt):
            continue

        before_len = len(lines)
        last_section = _process_entry(
            entry,
            lines,
            last_section,
            collapse_tool_results,
            include_thinking=include_thinking,
            include_tools=include_tools,
        )
        if len(lines) != before_len:
            emitted = True

    if not emitted and (since_timestamp or until_timestamp):
        lines.append("_No entries in the requested time range._")

    result = "\n".join(lines)
    return tail_limit_fn(result, tail_chars)


def render_agent_output(
    transcript_path: str,
    agent_name: AgentName,
    include_tools: bool = False,
    include_tool_results: bool = True,
    since_timestamp: datetime | None = None,
    include_timestamps: bool = True,
) -> tuple[str | None, datetime | None]:
    """Render markdown for assistant activity since the last user boundary or since_timestamp.

    Used for sequential, incremental output blocks. No truncation is applied;
    the adapter handles pagination/splitting for platform limits.

    Args:
        transcript_path: Path to transcript file
        agent_name: Agent name for iterator selection
        include_tools: Whether to include tool call blocks
        include_tool_results: Whether to include tool result blocks
        since_timestamp: Optional UTC datetime boundary. If provided, only returns activity AFTER this.
        include_timestamps: Whether to prefix blocks with [HH:MM:SS] timestamps

    Returns:
        Tuple of (markdown text or None, timestamp of last rendered entry or None)
    """
    entries = _get_entries_for_agent(transcript_path, agent_name)
    if not entries:
        return None, None

    start_idx = _resolve_render_start_index(
        entries,
        transcript_path,
        agent_name,
        since_timestamp,
        mode="standard",
    )
    if start_idx is None:
        return None, None

    if since_timestamp is None:
        logger.debug("[STD_RENDER] No cursor. Starting after last user message at index %d", start_idx)

    # Collect assistant activity from start_idx
    assistant_entries = entries[start_idx:]
    logger.debug(
        "Rendering incremental output",
        extra={
            "session": transcript_path,
            "start_idx": start_idx,
            "total_entries": len(entries),
            "assistant_entries": len(assistant_entries),
            "since_ts": since_timestamp,
        },
    )
    if not assistant_entries:
        return None, None

    # Route through canonical conversation projection with a policy derived
    # from the caller's include_tools / include_tool_results flags.
    # Visibility decision is now owned by the projection layer.
    from teleclaude.output_projection.conversation_projector import project_entries  # pylint: disable=C0415
    from teleclaude.output_projection.models import VisibilityPolicy  # pylint: disable=C0415

    render_policy = VisibilityPolicy(
        include_tools=include_tools,
        include_tool_results=include_tool_results,
        include_thinking=True,  # always visible in render_agent_output
    )

    lines: list[str] = []
    emitted = False
    last_entry_dt: datetime | None = None

    for pb in project_entries(assistant_entries, render_policy):
        if pb.role != "assistant":
            continue  # only format assistant content blocks

        if pb.timestamp:
            entry_dt = _parse_timestamp(pb.timestamp)
            if entry_dt:
                last_entry_dt = entry_dt

        time_prefix = ""
        if include_timestamps and last_entry_dt:
            time_prefix = f"[{last_entry_dt.strftime('%H:%M:%S')}] "

        if _append_standard_render_block(pb.block, pb.block_type, time_prefix, lines):
            emitted = True

    if not emitted:
        return None, last_entry_dt

    result = "\n".join(lines).strip()
    return result, last_entry_dt


@dataclass(frozen=True)
class TranscriptParserInfo:
    """Metadata for formatting a native agent transcript."""

    display_name: str
    file_prefix: str
    parse: Callable[[str, str, str | None, str | None, int, bool], str]


AGENT_TRANSCRIPT_PARSERS: dict[AgentName, TranscriptParserInfo] = {
    AgentName.CLAUDE: TranscriptParserInfo("Claude Code", "claude", parse_claude_transcript),
    AgentName.GEMINI: TranscriptParserInfo("Gemini", "gemini", parse_gemini_transcript),
    AgentName.CODEX: TranscriptParserInfo("Codex", "codex", parse_codex_transcript),
}


def get_transcript_parser_info(agent_name: AgentName) -> TranscriptParserInfo:
    """Return metadata for the given agent's transcript parser."""
    return AGENT_TRANSCRIPT_PARSERS[agent_name]
