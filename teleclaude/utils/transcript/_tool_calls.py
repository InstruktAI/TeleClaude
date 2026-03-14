"""Tool-call and structured message extraction for checkpoint heuristics and Messages API."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import cast

from teleclaude.constants import CHECKPOINT_RESULT_SNIPPET_MAX_CHARS
from teleclaude.core.agents import AgentName
from teleclaude.core.models import JsonDict

from ._iterators import _get_entries_for_agent
from ._parsers import normalize_transcript_entry_message
from ._utils import CHECKPOINT_JSONL_TAIL_ENTRIES, _parse_timestamp

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Layer 2: Tool-call extraction for checkpoint heuristics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCallRecord:
    """A single tool invocation extracted from the current turn."""

    tool_name: str
    input_data: JsonDict = field(default_factory=dict)
    had_error: bool = False
    result_snippet: str = ""
    timestamp: datetime | None = None


@dataclass
class TurnTimeline:
    """Ordered tool calls from the current turn."""

    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    has_data: bool = True


@dataclass
class _ToolCallExtractionState:
    """Mutable state while extracting tool calls from transcript entries."""

    records: list[ToolCallRecord] = field(default_factory=list)
    pending_record: ToolCallRecord | None = None
    pending_function_calls: dict[str, ToolCallRecord] = field(default_factory=dict)


def _parse_function_call_arguments(raw_arguments: object) -> Mapping[str, object]:
    """Parse function_call arguments into a dict payload."""
    if isinstance(raw_arguments, dict):
        return cast(
            dict[str, object],  # guard: loose-dict - External tool input
            raw_arguments,
        )
    if isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
            if isinstance(parsed, dict):
                return cast(
                    dict[str, object],  # guard: loose-dict - External tool input
                    parsed,
                )
        except json.JSONDecodeError:
            return {"raw_arguments": raw_arguments}
        return {"raw_arguments": raw_arguments}
    return {}


def _infer_function_call_output_error(output_text: str) -> bool:
    """Best-effort error detection for Codex function_call_output payloads."""
    lowered = output_text.lower()
    if lowered.startswith("err:") or "tool call error" in lowered:
        return True

    marker = "Process exited with code "
    idx = output_text.find(marker)
    if idx >= 0:
        remainder = output_text[idx + len(marker) :].strip()
        digits = ""
        for ch in remainder:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            return digits != "0"
    return False


def _is_user_tool_result_only_message(message: Mapping[str, object]) -> bool:
    """Return True when a user message only carries tool_result blocks.

    Claude writes tool outputs as role=user messages. Those entries are part
    of the assistant turn and must not reset current-turn boundaries.
    """
    if message.get("role") != "user":
        return False

    content = message.get("content")
    if isinstance(content, str):
        return False
    if not isinstance(content, list) or not content:
        return False

    saw_block = False
    for block in content:
        if not isinstance(block, dict):
            return False
        saw_block = True
        if block.get("type") != "tool_result":
            return False
    return saw_block


def _tool_call_tail_entries(agent_name: AgentName, full_session: bool) -> int | None:
    """Resolve tail-scoping policy for tool-call extraction."""
    if full_session:
        return None
    if agent_name in (AgentName.CLAUDE, AgentName.CODEX):
        return CHECKPOINT_JSONL_TAIL_ENTRIES
    return None


def _find_turn_start_idx(entries: list[JsonDict], full_session: bool) -> int:
    """Find the first entry to inspect for the current turn."""
    if full_session:
        return 0

    for i in range(len(entries) - 1, -1, -1):
        message = normalize_transcript_entry_message(entries[i])
        if isinstance(message, dict) and message.get("role") == "user":
            if _is_user_tool_result_only_message(message):
                continue
            return i + 1
    return 0


def _entry_timestamp(entry: Mapping[str, object]) -> datetime | None:
    """Parse an entry timestamp when present."""
    entry_ts_str = entry.get("timestamp")
    return _parse_timestamp(entry_ts_str) if isinstance(entry_ts_str, str) else None


def _flush_pending_record(state: _ToolCallExtractionState) -> None:
    """Persist any in-progress non-function tool record."""
    if state.pending_record is not None:
        state.records.append(state.pending_record)
        state.pending_record = None


def _parse_custom_tool_input(raw_input: object) -> JsonDict:
    """Parse custom_tool_call input payloads into dict form."""
    if isinstance(raw_input, dict):
        return cast(JsonDict, raw_input)
    if not isinstance(raw_input, str):
        return {}

    try:
        parsed_input = json.loads(raw_input)
    except json.JSONDecodeError:
        parsed_input = None

    if isinstance(parsed_input, dict):
        return cast(JsonDict, parsed_input)
    return {"input": raw_input}


def _handle_function_call_payload(
    payload: Mapping[str, object],
    entry_dt: datetime | None,
    state: _ToolCallExtractionState,
) -> bool:
    """Extract a Codex function_call payload."""
    _flush_pending_record(state)

    tool_name = str(payload.get("name", "unknown"))
    call_id = str(payload.get("call_id", "")).strip()
    function_record = ToolCallRecord(
        tool_name=tool_name,
        input_data=dict(_parse_function_call_arguments(payload.get("arguments", {}))),  # type: ignore[arg-type]
        had_error=False,
        result_snippet="",
        timestamp=entry_dt,
    )
    if call_id:
        state.pending_function_calls[call_id] = function_record
    else:
        state.records.append(function_record)
    return True


def _handle_function_call_output_payload(
    payload: Mapping[str, object],
    state: _ToolCallExtractionState,
) -> bool:
    """Match a Codex function_call_output payload to a prior call."""
    output_str = str(payload.get("output", ""))
    call_id = str(payload.get("call_id", "")).strip()
    matched = state.pending_function_calls.pop(call_id, None) if call_id else None
    if matched is None:
        return True

    state.records.append(
        ToolCallRecord(
            tool_name=matched.tool_name,
            input_data=matched.input_data,
            had_error=_infer_function_call_output_error(output_str),
            result_snippet=output_str[:CHECKPOINT_RESULT_SNIPPET_MAX_CHARS],
            timestamp=matched.timestamp,
        )
    )
    return True


def _handle_custom_tool_call_payload(
    payload: Mapping[str, object],
    entry_dt: datetime | None,
    state: _ToolCallExtractionState,
) -> bool:
    """Extract a Codex custom_tool_call payload."""
    _flush_pending_record(state)

    status = str(payload.get("status", "")).strip().lower()
    had_error = status in {"error", "failed", "cancelled", "canceled"}
    output_text = payload.get("output")
    if output_text is None and had_error:
        output_text = payload.get("error", "")

    state.records.append(
        ToolCallRecord(
            tool_name=str(payload.get("name", "unknown")),
            input_data=_parse_custom_tool_input(payload.get("input", {})),
            had_error=had_error,
            result_snippet=str(output_text or "")[:CHECKPOINT_RESULT_SNIPPET_MAX_CHARS],
            timestamp=entry_dt,
        )
    )
    return True


def _handle_response_item_entry(
    entry: Mapping[str, object],
    entry_dt: datetime | None,
    state: _ToolCallExtractionState,
) -> bool:
    """Handle Codex response_item transcript entries."""
    if entry.get("type") != "response_item":
        return False

    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return False

    payload_type = payload.get("type")
    if payload_type == "function_call":
        return _handle_function_call_payload(payload, entry_dt, state)
    if payload_type == "function_call_output":
        return _handle_function_call_output_payload(payload, state)
    if payload_type == "custom_tool_call":
        return _handle_custom_tool_call_payload(payload, entry_dt, state)
    return False


def _start_pending_tool_use(block: Mapping[str, object], entry_dt: datetime | None) -> ToolCallRecord:
    """Create a pending record from a transcript tool_use block."""
    raw_input = block.get("input", {})
    input_data: JsonDict = {}
    if isinstance(raw_input, dict):
        input_data = cast(JsonDict, raw_input)
    return ToolCallRecord(
        tool_name=str(block.get("name", "unknown")),
        input_data=input_data,
        had_error=False,
        result_snippet="",
        timestamp=entry_dt,
    )


def _complete_pending_tool_result(
    block: Mapping[str, object],
    state: _ToolCallExtractionState,
) -> None:
    """Complete the pending tool record with a matching tool_result block."""
    if state.pending_record is None:
        return

    matched = state.pending_record
    state.pending_record = None
    state.records.append(
        ToolCallRecord(
            tool_name=matched.tool_name,
            input_data=matched.input_data,
            had_error=bool(block.get("is_error", False)),
            result_snippet=str(block.get("content", ""))[:CHECKPOINT_RESULT_SNIPPET_MAX_CHARS],
            timestamp=matched.timestamp,
        )
    )


def _process_entry_message_blocks(
    entry: Mapping[str, object],
    entry_dt: datetime | None,
    state: _ToolCallExtractionState,
) -> None:
    """Extract tool-use state transitions from normalized message blocks."""
    message = normalize_transcript_entry_message(entry)
    if not isinstance(message, dict):
        return

    content = message.get("content")
    if not isinstance(content, list):
        return

    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "tool_use":
            _flush_pending_record(state)
            state.pending_record = _start_pending_tool_use(block, entry_dt)
            continue
        if block_type == "tool_result":
            _complete_pending_tool_result(block, state)


def extract_tool_calls_current_turn(
    transcript_path: str,
    agent_name: AgentName,
    *,
    full_session: bool = False,
) -> TurnTimeline:
    """Extract tool calls from the current turn (or full session) of a transcript.

    guard: allow-string-compare

    Uses _get_entries_for_agent() (Layer 1) to load normalized entries,
    then walks from the last user message boundary to end of transcript,
    building ToolCallRecord instances from tool_use/tool_result blocks.

    When full_session=True, skips the turn boundary and extracts from all entries.
    Used as a fallback when current-turn scoping misses edits from earlier turns.

    Fails open: returns TurnTimeline(tool_calls=[], has_data=False) on any error.
    """
    try:
        tail_entries = _tool_call_tail_entries(agent_name, full_session)
        entries = _get_entries_for_agent(transcript_path, agent_name, tail_entries=tail_entries)
        if entries is None:
            return TurnTimeline(tool_calls=[], has_data=False)

        turn_start_idx = _find_turn_start_idx(entries, full_session)
        state = _ToolCallExtractionState()
        for entry in entries[turn_start_idx:]:
            entry_dt = _entry_timestamp(entry)
            if _handle_response_item_entry(entry, entry_dt, state):
                continue
            _process_entry_message_blocks(entry, entry_dt, state)

        _flush_pending_record(state)
        if state.pending_function_calls:
            state.records.extend(state.pending_function_calls.values())

        return TurnTimeline(tool_calls=state.records, has_data=True)

    except Exception:
        logger.debug("Tool-call extraction failed (fail-open)", exc_info=True)
        return TurnTimeline(tool_calls=[], has_data=False)


# ---------------------------------------------------------------------------
# Layer 3: Structured message extraction for Messages API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StructuredMessage:
    """A single structured message extracted from a transcript entry."""

    role: str  # "user" | "assistant" | "system"
    type: str  # "text" | "compaction" | "tool_use" | "tool_result" | "thinking"
    text: str
    timestamp: str | None = None
    entry_index: int = 0
    file_index: int = 0

    def to_dict(self) -> dict[str, object]:  # guard: loose-dict - API response serialization
        """Serialize to JSON-compatible dict."""
        return {
            "role": self.role,
            "type": self.type,
            "text": self.text,
            "timestamp": self.timestamp,
            "entry_index": self.entry_index,
            "file_index": self.file_index,
        }


def _is_compaction_entry(entry: dict[str, object], entry_index: int) -> bool:  # guard: loose-dict
    """Detect Claude system entries that mark context compaction.

    Claude system entries with a parentUuid (after the initial session start
    entry at index 0) are compaction events.
    """
    if entry_index == 0:
        return False
    message = entry.get("message")
    if not isinstance(message, dict):
        return False
    if message.get("role") != "system":
        return False
    # System entries with parentUuid indicate compaction
    if "parentUuid" in entry:
        return True
    return False


def _resolve_entry_timestamp(
    entry: Mapping[str, object],
    since_dt: datetime | None,
) -> tuple[str | None, bool]:
    """Return entry timestamp and whether it passes the since filter."""
    entry_ts_str = entry.get("timestamp")
    if not isinstance(entry_ts_str, str):
        return None, True
    if since_dt is None:
        return entry_ts_str, True

    entry_dt = _parse_timestamp(entry_ts_str)
    if entry_dt and entry_dt <= since_dt:
        return entry_ts_str, False
    return entry_ts_str, True


def _append_compaction_message(
    messages: list[StructuredMessage],
    entry: dict[str, object],  # guard: loose-dict - External transcript entry
    entry_ts: str | None,
    entry_index: int,
) -> bool:
    """Append a compaction marker when the entry represents one."""
    if not _is_compaction_entry(entry, entry_index):
        return False
    messages.append(
        StructuredMessage(
            role="system",
            type="compaction",
            text="Context compacted",
            timestamp=entry_ts,
            entry_index=entry_index,
        )
    )
    return True


def _append_tool_result_only_messages(
    messages: list[StructuredMessage],
    content: object,
    entry_ts: str | None,
    entry_index: int,
    *,
    include_tools: bool,
) -> None:
    """Append Claude-style tool_result-only user messages."""
    if not include_tools or not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            messages.append(
                StructuredMessage(
                    role="assistant",
                    type="tool_result",
                    text=str(block.get("content", "")),
                    timestamp=entry_ts,
                    entry_index=entry_index,
                )
            )


def _append_string_content_message(
    messages: list[StructuredMessage],
    role: str,
    content: str,
    entry_ts: str | None,
    entry_index: int,
) -> None:
    """Append a plain string-content structured message when applicable."""
    if role != "user":
        return
    messages.append(
        StructuredMessage(
            role="user",
            type="text",
            text=content,
            timestamp=entry_ts,
            entry_index=entry_index,
        )
    )


def _append_block_content_messages(
    messages: list[StructuredMessage],
    role: str,
    content: list[object],
    entry_ts: str | None,
    entry_index: int,
    *,
    include_tools: bool,
    include_thinking: bool,
) -> None:
    """Append structured messages derived from content blocks."""
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")

        if block_type in ("text", "input_text", "output_text"):
            text = str(block.get("text", ""))
            if text.strip():
                msg_role = role if role in ("user", "assistant") else "assistant"
                messages.append(
                    StructuredMessage(
                        role=msg_role,
                        type="text",
                        text=text,
                        timestamp=entry_ts,
                        entry_index=entry_index,
                    )
                )
            continue

        if block_type == "thinking":
            if include_thinking:
                thinking_text = str(block.get("thinking", ""))
                if thinking_text.strip():
                    messages.append(
                        StructuredMessage(
                            role="assistant",
                            type="thinking",
                            text=thinking_text,
                            timestamp=entry_ts,
                            entry_index=entry_index,
                        )
                    )
            continue

        if block_type == "tool_use":
            if include_tools:
                tool_name = str(block.get("name", "unknown"))
                tool_input = block.get("input", {})
                messages.append(
                    StructuredMessage(
                        role="assistant",
                        type="tool_use",
                        text=f"{tool_name}: {json.dumps(tool_input)}",
                        timestamp=entry_ts,
                        entry_index=entry_index,
                    )
                )
            continue

        if block_type == "tool_result" and include_tools:
            messages.append(
                StructuredMessage(
                    role="assistant",
                    type="tool_result",
                    text=str(block.get("content", "")),
                    timestamp=entry_ts,
                    entry_index=entry_index,
                )
            )


def extract_structured_messages(
    transcript_path: str,
    agent_name: AgentName,
    *,
    since: str | None = None,
    include_tools: bool = False,
    include_thinking: bool = False,
) -> list[StructuredMessage]:
    """Extract structured messages from a single transcript file.

    Uses existing _get_entries_for_agent() and _iter_*_entries() infrastructure.

    Args:
        transcript_path: Path to transcript file
        agent_name: Agent name for iterator selection
        since: Optional ISO 8601 UTC timestamp; only messages after this time
        include_tools: Whether to include tool_use/tool_result entries
        include_thinking: Whether to include thinking/reasoning blocks

    Returns:
        List of StructuredMessage objects in chronological order.
    """
    entries = _get_entries_for_agent(transcript_path, agent_name)
    if entries is None:
        return []

    since_dt = _parse_timestamp(since) if since else None
    messages: list[StructuredMessage] = []

    for idx, entry in enumerate(entries):
        entry_ts, include_entry = _resolve_entry_timestamp(entry, since_dt)
        if not include_entry:
            continue

        if _append_compaction_message(messages, entry, entry_ts, idx):  # type: ignore[arg-type]
            continue

        message = normalize_transcript_entry_message(entry)
        if not isinstance(message, dict):
            continue

        role = message.get("role")
        if not isinstance(role, str):
            continue

        content = message.get("content")

        if role == "user" and _is_user_tool_result_only_message(message):
            _append_tool_result_only_messages(
                messages,
                content,
                entry_ts,
                idx,
                include_tools=include_tools,
            )
            continue

        if isinstance(content, str):
            _append_string_content_message(messages, role, content, entry_ts, idx)
            continue

        if isinstance(content, list):
            _append_block_content_messages(
                messages,
                role,
                content,
                entry_ts,
                idx,
                include_tools=include_tools,
                include_thinking=include_thinking,
            )

    return messages


def extract_messages_from_chain(
    file_paths: list[str],
    agent_name: AgentName,
    *,
    since: str | None = None,
    include_tools: bool = False,
    include_thinking: bool = False,
) -> list[dict[str, object]]:  # guard: loose-dict - API response messages
    """Extract structured messages from a chain of transcript files.

    .. deprecated::
        Use ``project_conversation_chain()`` from
        ``teleclaude.output_projection.conversation_projector`` instead.
        This function operates independently with its own extraction logic.

    Reads files in order (oldest first) and concatenates messages with file_index.

    Args:
        file_paths: Ordered list of transcript file paths (oldest first)
        agent_name: Agent name for iterator selection
        since: Optional ISO 8601 UTC timestamp filter
        include_tools: Whether to include tool_use/tool_result entries
        include_thinking: Whether to include thinking/reasoning blocks

    Returns:
        List of message dicts with file_index added, in chronological order.
    """
    all_messages: list[dict[str, object]] = []  # guard: loose-dict - API response

    for file_idx, file_path in enumerate(file_paths):
        file_messages = extract_structured_messages(
            file_path,
            agent_name,
            since=since,
            include_tools=include_tools,
            include_thinking=include_thinking,
        )
        for msg in file_messages:
            msg_dict = msg.to_dict()
            msg_dict["file_index"] = file_idx
            all_messages.append(msg_dict)

    return all_messages
