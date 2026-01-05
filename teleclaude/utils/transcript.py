"""Parse and convert Claude/Gemini/Codex session transcripts to markdown."""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, cast

from teleclaude.core.agents import AgentName


def parse_claude_transcript(
    transcript_path: str,
    title: str,
    since_timestamp: Optional[str] = None,
    until_timestamp: Optional[str] = None,
    tail_chars: int = 5000,
    collapse_tool_results: bool = False,
) -> str:
    """Convert Claude Code JSONL transcript to markdown with filtering.

    Args:
        transcript_path: Path to Claude session .jsonl file
        title: Session title for header
        since_timestamp: Optional ISO 8601 UTC start filter (inclusive)
        until_timestamp: Optional ISO 8601 UTC end filter (inclusive)
        tail_chars: Max characters to return from end (default 5000, 0 for unlimited)

    Returns:
        Markdown formatted conversation with timestamps on each section
    """
    path = Path(transcript_path).expanduser()
    if not path.exists():
        return f"Transcript file not found: {transcript_path}"

    try:
        entries = _iter_claude_entries(path)
        return _render_transcript_from_entries(
            entries,
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
    since_timestamp: Optional[str] = None,
    until_timestamp: Optional[str] = None,
    tail_chars: int = 5000,
    collapse_tool_results: bool = False,
) -> str:
    """Convert Codex JSONL transcript to markdown with filtering."""

    path = Path(transcript_path).expanduser()
    if not path.exists():
        return f"Transcript file not found: {transcript_path}"

    try:
        entries = _iter_codex_entries(path)
        return _render_transcript_from_entries(
            entries,
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
    since_timestamp: Optional[str] = None,
    until_timestamp: Optional[str] = None,
    tail_chars: int = 5000,
    collapse_tool_results: bool = False,
) -> str:
    """Convert Gemini JSON transcript into markdown."""

    path = Path(transcript_path).expanduser()
    if not path.exists():
        return f"Transcript file not found: {transcript_path}"

    try:
        entries = _iter_gemini_entries(path)
        return _render_transcript_from_entries(
            entries,
            title,
            since_timestamp,
            until_timestamp,
            tail_chars,
            collapse_tool_results=collapse_tool_results,
        )
    except Exception as e:
        return f"Error parsing transcript: {e}"


def _should_skip_entry(entry: dict[str, object], since_dt: Optional[datetime], until_dt: Optional[datetime]) -> bool:  # noqa: loose-dict - External entry
    """Check if entry should be skipped based on type and timestamp filters."""
    if entry.get("type") == "summary":
        return True

    entry_timestamp = entry.get("timestamp")
    if isinstance(entry_timestamp, str):
        entry_dt = _parse_timestamp(entry_timestamp)
        if since_dt and entry_dt and entry_dt < since_dt:
            return True
        if until_dt and entry_dt and entry_dt > until_dt:
            return True

    return False


def _process_entry(
    entry: dict[str, object],  # noqa: loose-dict - External entry
    lines: list[str],
    last_section: Optional[str],
    collapse_tool_results: bool,
) -> Optional[str]:  # noqa: loose-dict - External entry
    """Process a transcript entry and append formatted content to lines."""
    entry_timestamp = entry.get("timestamp")
    entry_dt = None
    if isinstance(entry_timestamp, str):
        entry_dt = _parse_timestamp(entry_timestamp)
    time_prefix = _format_timestamp_prefix(entry_dt) if entry_dt else ""

    message = entry.get("message")

    # Handle Codex/Gemini "response_item" format where message is in payload
    if not isinstance(message, dict) and entry.get("type") == "response_item":
        payload = entry.get("payload")
        if isinstance(payload, dict):
            message = payload

    if not isinstance(message, dict):
        return last_section

    role = message.get("role")
    content: object = message.get("content", [])

    if not role or not isinstance(role, str):
        return last_section

    if isinstance(content, str):
        return _process_string_content(content, time_prefix, lines, last_section)

    if isinstance(content, list):
        return _process_list_content(content, role, time_prefix, lines, last_section, collapse_tool_results)

    return last_section


def _process_string_content(content: str, time_prefix: str, lines: list[str], last_section: Optional[str]) -> str:
    """Process string content (user message)."""
    if last_section != "user" or time_prefix:
        lines.append("")
        lines.append(f"## {time_prefix}👤 User")
        lines.append("")
    lines.append(content)
    return "user"


def _process_list_content(
    content: list[object],
    role: str,
    time_prefix: str,
    lines: list[str],
    last_section: Optional[str],
    collapse_tool_results: bool,
) -> Optional[str]:
    """Process list of content blocks."""
    current_section = last_section

    for block in content:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type")
        if not isinstance(block_type, str):
            continue

        if block_type in ("text", "input_text", "output_text"):
            current_section = _process_text_block(block, role, time_prefix, lines, current_section)
        elif block_type == "thinking":
            current_section = _process_thinking_block(block, time_prefix, lines, current_section)
        elif block_type == "tool_use":
            current_section = _process_tool_use_block(block, time_prefix, lines)
        elif block_type == "tool_result":
            current_section = _process_tool_result_block(
                block,
                time_prefix,
                lines,
                collapse_tool_results,
            )

    return current_section


def _process_text_block(
    block: dict[str, object],  # noqa: loose-dict - External block
    role: str,
    time_prefix: str,
    lines: list[str],
    last_section: Optional[str],
) -> Optional[str]:
    """Process text block from assistant or user."""
    if role == "assistant" and last_section != "assistant":
        lines.append("")
        lines.append(f"## {time_prefix}🤖 Assistant")
        lines.append("")
    elif role == "user" and (last_section != "user" or time_prefix):
        lines.append("")
        lines.append(f"## {time_prefix}👤 User")
        lines.append("")

    text = block.get("text", "")
    lines.append(str(text))

    if role == "assistant":
        return "assistant"
    if role == "user":
        return "user"
    return last_section


def _process_thinking_block(
    block: dict[str, object],  # noqa: loose-dict - External block
    time_prefix: str,
    lines: list[str],
    last_section: Optional[str],
) -> str:
    """Process thinking block."""
    if last_section != "assistant":
        lines.append("")
        lines.append(f"## {time_prefix}🤖 Assistant")
        lines.append("")
    thinking = block.get("thinking", "")
    formatted_thinking = _format_thinking(str(thinking))
    lines.append(formatted_thinking)
    return "assistant"


def _process_tool_use_block(block: dict[str, object], time_prefix: str, lines: list[str]) -> str:  # noqa: loose-dict - External block
    """Process tool use block."""
    tool_name = block.get("name", "unknown")
    tool_input = block.get("input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}
    serialized_input = json.dumps(tool_input)
    lines.append("")
    lines.append(f"{time_prefix}🔧 **TOOL CALL:** {tool_name} {serialized_input}")
    return "tool_use"


def _process_tool_result_block(
    block: dict[str, object],  # noqa: loose-dict - External block
    time_prefix: str,
    lines: list[str],
    collapse_tool_results: bool,
) -> str:  # noqa: loose-dict - External block
    """Process tool result block."""
    is_error = block.get("is_error", False)
    status_emoji = "❌" if is_error else "✅"
    content_data = block.get("content", "")
    lines.append("")
    content_lines = str(content_data).splitlines() or [""]
    if collapse_tool_results:
        lines.append(f"{time_prefix}{status_emoji} **TOOL RESPONSE (tap to reveal):**")
        lines.append("")
        for line in content_lines:
            lines.append(f"||{line}||" if line else "|| ||")
        lines.append("")
    else:
        lines.append(f"{time_prefix}{status_emoji} **TOOL RESPONSE:**")
        lines.append("")
        for line in content_lines:
            lines.append(f"> {line}" if line else ">")
        lines.append("")
    return "tool_result"


def _apply_tail_limit(result: str, tail_chars: int) -> str:
    """Apply tail_chars limit to result."""
    if 0 < tail_chars < len(result):
        truncated = result[-tail_chars:]
        header_pos = truncated.find("\n## ")
        if 0 <= header_pos < 500:
            truncated = truncated[header_pos + 1 :]
        return f"[...truncated, showing last {tail_chars} chars...]\n\n{truncated}"
    return result


def _apply_tail_limit_codex(result: str, tail_chars: int) -> str:
    """Apply tail_chars limit for Codex transcripts.

    Codex clients can truncate tool output from the start; for long transcripts
    we prefer to start at a recent section boundary so the newest content
    appears near the beginning of the returned text.
    """
    if not (0 < tail_chars < len(result)):
        return result

    truncated = result[-tail_chars:]

    # Prefer the most recent section header ("\n## ") so we start at the newest
    # readable boundary. This intentionally drops older sections even if they
    # still fit within the last-N window.
    last_header_pos = truncated.rfind("\n## ")
    if last_header_pos >= 0:
        truncated = truncated[last_header_pos + 1 :]
    else:
        first_header_pos = truncated.find("\n## ")
        if 0 <= first_header_pos < 500:
            truncated = truncated[first_header_pos + 1 :]

    return f"[...truncated, showing last {tail_chars} chars...]\n\n{truncated}"


def _parse_timestamp(ts: str) -> Optional[datetime]:
    """Parse ISO 8601 timestamp string to datetime.

    Args:
        ts: ISO 8601 timestamp (e.g., "2025-11-11T04:25:33.890Z")

    Returns:
        datetime object or None if parsing fails
    """
    if not ts:
        return None
    try:
        # Handle Z suffix and milliseconds
        ts_clean = ts.replace("Z", "+00:00")
        # Try with microseconds first, then without
        for fmt in ["%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"]:
            try:
                return datetime.strptime(ts_clean, fmt)
            except ValueError:
                continue
        # Fallback: fromisoformat handles most cases
        return datetime.fromisoformat(ts_clean)
    except (ValueError, TypeError):
        return None


def _format_timestamp_prefix(dt: datetime) -> str:
    """Format datetime as prefix for section headers.

    Args:
        dt: datetime object

    Returns:
        Formatted string like "14:25:33 · " or "2025-11-11 14:25:33 · "
    """
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()

    # If same day, just show time
    if dt.date() == now.date():
        return f"{dt.strftime('%H:%M:%S')} · "

    # Different day, show full date + time
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} · "


def _format_thinking(text: str) -> str:
    """Format thinking block with italics, preserving code blocks.

    Args:
        text: Thinking block text

    Returns:
        Formatted markdown with italics for non-code lines, blank line after
    """
    lines = text.split("\n")
    result_lines = []
    in_code_block = False

    for line in lines:
        if line.strip().startswith("```"):
            if not in_code_block:
                # Add blank line before opening backticks
                result_lines.append("")
            result_lines.append(line)
            in_code_block = not in_code_block
        elif in_code_block or not line.strip():
            result_lines.append(line)
        else:
            result_lines.append(f"*{line}*")

    # Add blank line after thinking block
    result_lines.append("")

    return "\n".join(result_lines)


def _render_transcript_from_entries(
    entries: Iterable[dict[str, object]],  # noqa: loose-dict - External entries
    title: str,
    since_timestamp: Optional[str],
    until_timestamp: Optional[str],
    tail_chars: int,
    *,
    tail_limit_fn: Callable[[str, int], str] = _apply_tail_limit,
    collapse_tool_results: bool = False,
) -> str:
    """Render markdown from normalized transcript entries."""

    since_dt = _parse_timestamp(since_timestamp) if since_timestamp else None
    until_dt = _parse_timestamp(until_timestamp) if until_timestamp else None

    lines: list[str] = [f"# {title}", ""]
    last_section: Optional[str] = None

    for entry in entries:
        if _should_skip_entry(entry, since_dt, until_dt):
            continue

        last_section = _process_entry(entry, lines, last_section, collapse_tool_results)

    result = "\n".join(lines)
    return tail_limit_fn(result, tail_chars)


def _iter_jsonl_entries(path: Path) -> Iterable[dict[str, object]]:  # noqa: loose-dict - External JSONL unknown structure
    """Yield JSON objects for each line in a transcript file."""

    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                entry_value: object = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(entry_value, dict):
                yield cast(dict[str, object], entry_value)  # noqa: loose-dict - Parsed JSONL entry


def _iter_claude_entries(path: Path) -> Iterable[dict[str, object]]:  # noqa: loose-dict - External JSONL unknown structure
    """Yield entries from Claude Code transcripts (raw JSONL)."""

    yield from _iter_jsonl_entries(path)


def _iter_codex_entries(path: Path) -> Iterable[dict[str, object]]:  # noqa: loose-dict - External JSONL unknown structure
    """Yield entries from Codex JSONL transcripts, skipping metadata."""

    for entry in _iter_jsonl_entries(path):
        if entry.get("type") == "session_meta":
            continue
        yield entry


def _iter_gemini_entries(path: Path) -> Iterable[dict[str, object]]:  # noqa: loose-dict - External JSONL unknown structure
    """Yield normalized entries from Gemini JSON session files."""

    with open(path, encoding="utf-8") as f:
        raw_document: object = json.load(f)

    document: dict[str, object] = {}  # noqa: loose-dict - External JSON document
    if isinstance(raw_document, dict):
        document = cast(dict[str, object], raw_document)  # noqa: loose-dict - External JSON document

    raw_messages = document.get("messages", [])
    messages: list[dict[str, object]] = []  # noqa: loose-dict - External JSON messages
    if isinstance(raw_messages, list):
        for item in raw_messages:
            if isinstance(item, dict):
                messages.append(cast(dict[str, object], item))  # noqa: loose-dict - External JSON message

    for message in messages:
        msg_type = message.get("type")
        timestamp = message.get("timestamp")

        if msg_type == "user":
            content_value = message.get("content", "")
            yield {
                "type": "user",
                "timestamp": timestamp,
                "message": {
                    "role": "user",
                    "content": [{"type": "input_text", "text": str(content_value)}],
                },
            }
            continue

        if msg_type != "gemini":
            continue

        blocks: list[dict[str, object]] = []  # noqa: loose-dict - Internal normalized blocks
        thoughts_raw = message.get("thoughts")
        thoughts: list[dict[str, object]] = []  # noqa: loose-dict - External thoughts
        if isinstance(thoughts_raw, list):
            for thought_item in thoughts_raw:
                if isinstance(thought_item, dict):
                    thoughts.append(cast(dict[str, object], thought_item))  # noqa: loose-dict - External thought

        for thought in thoughts:
            description = thought.get("description") or thought.get("text") or ""
            if description:
                blocks.append({"type": "thinking", "thinking": description})

        content_text = message.get("content")
        if content_text:
            blocks.append({"type": "text", "text": str(content_text)})

        tool_calls_raw = message.get("toolCalls")
        tool_calls: list[dict[str, object]] = []  # noqa: loose-dict - External tool calls
        if isinstance(tool_calls_raw, list):
            for tool_item in tool_calls_raw:
                if isinstance(tool_item, dict):
                    tool_calls.append(cast(dict[str, object], tool_item))  # noqa: loose-dict - External tool call

        for tool_call in tool_calls:
            name = tool_call.get("displayName") or tool_call.get("name") or "tool"
            args = tool_call.get("args")
            input_payload: dict[str, object] = {}  # noqa: loose-dict - External tool args
            if isinstance(args, dict):
                input_payload = cast(dict[str, object], args)  # noqa: loose-dict - External tool args
            blocks.append(
                {
                    "type": "tool_use",
                    "name": name,
                    "input": input_payload,
                }
            )

            result_texts: list[str] = []
            result_raw = tool_call.get("result")
            if isinstance(result_raw, list):
                for result in result_raw:
                    if not isinstance(result, dict):
                        continue
                    function_response = result.get("functionResponse")
                    if isinstance(function_response, dict):
                        response_candidate = function_response.get("response")
                    else:
                        response_candidate = result.get("response")

                    response_value = None
                    if isinstance(response_candidate, dict):
                        response_value = response_candidate.get("output")
                    elif response_candidate:
                        response_value = response_candidate
                    if response_value:
                        result_texts.append(str(response_value))

            fallback_text = tool_call.get("resultDisplay") or tool_call.get("description")
            if fallback_text and not result_texts:
                result_texts.append(str(fallback_text))

            if any(result_texts):
                blocks.append({"type": "tool_result", "content": "\n\n".join(result_texts)})

        if not blocks and content_text:
            blocks.append({"type": "text", "text": str(content_text)})

        if not blocks:
            continue

        yield {
            "type": "assistant",
            "timestamp": timestamp,
            "message": {
                "role": "assistant",
                "content": blocks,
            },
        }


@dataclass(frozen=True)
class TranscriptParserInfo:
    """Metadata for formatting a native agent transcript."""

    display_name: str
    file_prefix: str
    parser: Callable[[str, str, Optional[str], Optional[str], int, bool], str]


AGENT_TRANSCRIPT_PARSERS: dict[AgentName, TranscriptParserInfo] = {
    AgentName.CLAUDE: TranscriptParserInfo("Claude Code", "claude", parse_claude_transcript),
    AgentName.GEMINI: TranscriptParserInfo("Gemini", "gemini", parse_gemini_transcript),
    AgentName.CODEX: TranscriptParserInfo("Codex", "codex", parse_codex_transcript),
}


def get_transcript_parser_info(agent_name: AgentName) -> TranscriptParserInfo:
    """Return metadata for the given agent's transcript parser."""
    return AGENT_TRANSCRIPT_PARSERS[agent_name]


def parse_session_transcript(
    transcript_path: str,
    title: str,
    *,
    agent_name: AgentName,
    since_timestamp: Optional[str] = None,
    until_timestamp: Optional[str] = None,
    tail_chars: int = 5000,
    escape_triple_backticks: bool = False,
    collapse_tool_results: bool = False,
) -> str:
    """Parse a session transcript using the agent-specific parser.

    Args:
        transcript_path: Path to transcript file
        title: Session title for header
        agent_name: Agent type for parser selection
        since_timestamp: Optional ISO 8601 UTC start filter (inclusive)
        until_timestamp: Optional ISO 8601 UTC end filter (inclusive)
        tail_chars: Max characters to return from end (default 5000, 0 for unlimited)
        escape_triple_backticks: If True, escape ``` to avoid breaking outer code blocks
    """

    parser_info = get_transcript_parser_info(agent_name)
    rendered = parser_info.parser(
        transcript_path,
        title,
        since_timestamp,
        until_timestamp,
        tail_chars,
        collapse_tool_results,
    )
    if escape_triple_backticks:
        return _escape_triple_backticks(rendered)
    return rendered


def _escape_triple_backticks(text: str) -> str:
    """Escape triple backticks to avoid nested code block breakage."""
    return text.replace("```", "`\u200b``")
