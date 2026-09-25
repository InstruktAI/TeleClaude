"""Transcript rendering: convert entries to markdown, parse agent transcripts."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.models import JsonDict
from teleclaude.output_projection.conversation_projector import project_entries
from teleclaude.output_projection.models import VisibilityPolicy

from ._block_renderers import (
    _extract_tool_subject,
    _process_entry,
    _process_tool_result_block,
    _process_tool_use_block,
    _should_skip_entry,
)
from ._iterators import (
    _get_entries_for_agent,
    _start_index_after_timestamp_or_rotation,
)
from ._noop_turns import without_noop_output
from ._user_turns import find_turn_start_idx
from ._utils import _apply_tail_limit, _format_thinking, _parse_timestamp

logger = get_logger(__name__)


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
        return find_turn_start_idx(entries, full_session=False, agent_name=agent_name)
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
    """Append a single clean-render pre_tool_use block."""
    tool_name = str(block.get("name", "unknown"))
    tool_name_safe = tool_name.split("\n", maxsplit=1)[0].split("(")[0].split("{")[0].strip()
    subject = _extract_tool_subject(block)  # type: ignore[arg-type]
    if subject == tool_name_safe:
        subject = None

    formatted_name = f"**`{tool_name_safe}`**"
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
            lines.append(str(text))
            return True
        return False

    if block_type == "thinking":
        thinking = block.get("thinking", "")
        if thinking:
            lines.append(_format_thinking(str(thinking)))
            return True
        return False

    if block_type == "pre_tool_use":
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
            lines.append(f"{time_prefix}{text}")
            return True
        return False

    if block_type == "thinking":
        thinking = block.get("thinking", "")
        if thinking:
            lines.append(f"{time_prefix}{_format_thinking(str(thinking))}")
            return True
        return False

    if block_type == "pre_tool_use":
        _process_tool_use_block(block, time_prefix, lines)  # type: ignore[arg-type]
        return True

    if block_type == "tool_result":
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
    include_tools: bool = True,
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

    assistant_entries = without_noop_output(entries[start_idx:])
    if not assistant_entries:
        return None, None

    # Route through canonical conversation projection.
    # Policy: thinking visible, tool results hidden, tool invocations caller-controlled.
    # Behavior is identical to the previous iter_assistant_blocks() iteration;
    # the projection layer now owns the visibility decision.
    clean_policy = VisibilityPolicy(
        include_tools=include_tools,
        include_tool_results=False,
        include_thinking=True,
    )
    lines: list[str] = []
    emitted = False
    last_entry_dt: datetime | None = None
    last_block_is_tool = False

    for pb in project_entries(assistant_entries, clean_policy, agent_name):
        if pb.role != "assistant":
            continue  # only format assistant content blocks

        if pb.timestamp:
            entry_dt = _parse_timestamp(pb.timestamp)
            if entry_dt:
                last_entry_dt = entry_dt

        current_is_tool = pb.block_type == "pre_tool_use"
        if lines and (current_is_tool != last_block_is_tool):
            lines.append("")

        if _append_clean_render_block(pb.block, pb.block_type, lines):
            emitted = True
            last_block_is_tool = current_is_tool
        # tool_result: suppressed by clean_policy (include_tool_results=False)

    if not emitted:
        return None, last_entry_dt

    return "\n".join(lines).strip(), last_entry_dt


def render_transcript_from_entries(
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
    assistant_entries = without_noop_output(entries[start_idx:])
    logger.trace(
        "Rendering incremental output",
        {
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
    render_policy = VisibilityPolicy(
        include_tools=include_tools,
        include_tool_results=include_tool_results,
        include_thinking=True,  # always visible in render_agent_output
    )

    lines: list[str] = []
    emitted = False
    last_entry_dt: datetime | None = None
    last_block_is_tool = False

    for pb in project_entries(assistant_entries, render_policy, agent_name):
        if pb.role != "assistant":
            continue  # only format assistant content blocks

        if pb.timestamp:
            entry_dt = _parse_timestamp(pb.timestamp)
            if entry_dt:
                last_entry_dt = entry_dt

        time_prefix = ""
        if include_timestamps and last_entry_dt:
            time_prefix = f"[{last_entry_dt.strftime('%H:%M:%S')}] "

        current_is_tool = pb.block_type in ("pre_tool_use", "tool_result")
        if lines and (current_is_tool != last_block_is_tool):
            lines.append("")

        if _append_standard_render_block(pb.block, pb.block_type, time_prefix, lines):
            emitted = True
            last_block_is_tool = current_is_tool

    if not emitted:
        return None, last_entry_dt

    result = "\n".join(lines).strip()
    return result, last_entry_dt
