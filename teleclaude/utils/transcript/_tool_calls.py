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
    input_data: dict[str, object] = field(  # guard: loose-dict - External tool input
        default_factory=dict
    )
    had_error: bool = False
    result_snippet: str = ""
    timestamp: datetime | None = None


@dataclass
class TurnTimeline:
    """Ordered tool calls from the current turn."""

    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    has_data: bool = True


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
        # full_session=True: read entire transcript (fallback after tail-scoping missed edits)
        tail_entries = (
            None
            if full_session
            else (CHECKPOINT_JSONL_TAIL_ENTRIES if agent_name in (AgentName.CLAUDE, AgentName.CODEX) else None)
        )
        entries = _get_entries_for_agent(transcript_path, agent_name, tail_entries=tail_entries)
        if entries is None:
            return TurnTimeline(tool_calls=[], has_data=False)

        # Find turn boundary: walk backward to last *real* user prompt.
        # Claude tool outputs are encoded as role=user tool_result messages and
        # must not reset the boundary within the same turn.
        # When full_session=True, skip this and start from the beginning.
        turn_start_idx = 0
        if not full_session:
            for i in range(len(entries) - 1, -1, -1):
                entry = entries[i]
                message = normalize_transcript_entry_message(entry)
                if isinstance(message, dict) and message.get("role") == "user":
                    if _is_user_tool_result_only_message(message):
                        continue
                    turn_start_idx = i + 1
                    break

        # Walk forward from turn boundary, extracting tool calls
        records: list[ToolCallRecord] = []
        pending_record: ToolCallRecord | None = None
        pending_function_calls: dict[str, ToolCallRecord] = {}

        for entry in entries[turn_start_idx:]:
            entry_ts_str = entry.get("timestamp")
            entry_dt = _parse_timestamp(entry_ts_str) if isinstance(entry_ts_str, str) else None

            # Codex function tool calls are emitted as response_item payloads.
            if entry.get("type") == "response_item":
                payload = entry.get("payload")
                if isinstance(payload, dict):
                    payload_type = payload.get("type")

                    if payload_type == "function_call":
                        if pending_record is not None:
                            records.append(pending_record)
                            pending_record = None

                        tool_name = str(payload.get("name", "unknown"))
                        call_id = str(payload.get("call_id", "")).strip()
                        input_data = dict(_parse_function_call_arguments(payload.get("arguments", {})))
                        function_record = ToolCallRecord(
                            tool_name=tool_name,
                            input_data=input_data,
                            had_error=False,
                            result_snippet="",
                            timestamp=entry_dt,
                        )
                        if call_id:
                            pending_function_calls[call_id] = function_record
                        else:
                            records.append(function_record)
                        continue

                    if payload_type == "function_call_output":
                        output_raw = payload.get("output", "")
                        output_str = str(output_raw)
                        snippet = output_str[:CHECKPOINT_RESULT_SNIPPET_MAX_CHARS]
                        had_error = _infer_function_call_output_error(output_str)
                        call_id = str(payload.get("call_id", "")).strip()

                        if call_id and call_id in pending_function_calls:
                            matched = pending_function_calls.pop(call_id)
                            records.append(
                                ToolCallRecord(
                                    tool_name=matched.tool_name,
                                    input_data=matched.input_data,
                                    had_error=had_error,
                                    result_snippet=snippet,
                                    timestamp=matched.timestamp,
                                )
                            )
                        continue

                    if payload_type == "custom_tool_call":
                        if pending_record is not None:
                            records.append(pending_record)
                            pending_record = None

                        tool_name = str(payload.get("name", "unknown"))
                        raw_input = payload.get("input", {})
                        input_data = {}
                        if isinstance(raw_input, dict):
                            input_data = cast(
                                dict[str, object],  # guard: loose-dict - External tool input
                                raw_input,
                            )
                        elif isinstance(raw_input, str):
                            try:
                                parsed_input = json.loads(raw_input)
                            except json.JSONDecodeError:
                                parsed_input = None
                            if isinstance(parsed_input, dict):
                                input_data = cast(
                                    dict[str, object],  # guard: loose-dict - External tool input
                                    parsed_input,
                                )
                            else:
                                input_data = {"input": raw_input}

                        status = str(payload.get("status", "")).strip().lower()
                        had_error = status in {"error", "failed", "cancelled", "canceled"}
                        output_text = payload.get("output")
                        if output_text is None and had_error:
                            output_text = payload.get("error", "")
                        snippet = str(output_text or "")[:CHECKPOINT_RESULT_SNIPPET_MAX_CHARS]

                        records.append(
                            ToolCallRecord(
                                tool_name=tool_name,
                                input_data=input_data,
                                had_error=had_error,
                                result_snippet=snippet,
                                timestamp=entry_dt,
                            )
                        )
                        continue

            message = normalize_transcript_entry_message(entry)
            if not isinstance(message, dict):
                continue

            content = message.get("content")
            if not isinstance(content, list):
                continue

            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")

                if block_type == "tool_use":
                    # Finalize any pending record without a result
                    if pending_record is not None:
                        records.append(pending_record)
                    tool_name = str(block.get("name", "unknown"))
                    raw_input = block.get("input", {})
                    input_data: dict[str, object] = {}  # guard: loose-dict - External tool input
                    if isinstance(raw_input, dict):
                        input_data = cast(
                            dict[str, object],  # guard: loose-dict - External tool input
                            raw_input,
                        )
                    pending_record = ToolCallRecord(
                        tool_name=tool_name,
                        input_data=input_data,
                        had_error=False,
                        result_snippet="",
                        timestamp=entry_dt,
                    )

                elif block_type == "tool_result":
                    if pending_record is not None:
                        is_error = bool(block.get("is_error", False))
                        raw_content = block.get("content", "")
                        snippet = str(raw_content)[:CHECKPOINT_RESULT_SNIPPET_MAX_CHARS]
                        pending_record = ToolCallRecord(
                            tool_name=pending_record.tool_name,
                            input_data=pending_record.input_data,
                            had_error=is_error,
                            result_snippet=snippet,
                            timestamp=pending_record.timestamp,
                        )
                        records.append(pending_record)
                        pending_record = None

        # Finalize any trailing tool_use without a result
        if pending_record is not None:
            records.append(pending_record)
        if pending_function_calls:
            records.extend(pending_function_calls.values())

        return TurnTimeline(tool_calls=records, has_data=True)

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
        entry_ts_str = entry.get("timestamp")
        entry_ts: str | None = None
        if isinstance(entry_ts_str, str):
            entry_ts = entry_ts_str
            if since_dt:
                entry_dt = _parse_timestamp(entry_ts_str)
                if entry_dt and entry_dt <= since_dt:
                    continue

        # Compaction detection (Claude-specific)
        if _is_compaction_entry(entry, idx):
            messages.append(
                StructuredMessage(
                    role="system",
                    type="compaction",
                    text="Context compacted",
                    timestamp=entry_ts,
                    entry_index=idx,
                )
            )
            continue

        # Resolve message from entry
        message = normalize_transcript_entry_message(entry)
        if not isinstance(message, dict):
            continue

        role = message.get("role")
        if not isinstance(role, str):
            continue

        content = message.get("content")

        # User messages with tool_result-only content (Claude pattern)
        if role == "user" and _is_user_tool_result_only_message(message):
            if not include_tools:
                continue
            # Emit as tool_result entries
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        result_text = str(block.get("content", ""))
                        messages.append(
                            StructuredMessage(
                                role="assistant",
                                type="tool_result",
                                text=result_text,
                                timestamp=entry_ts,
                                entry_index=idx,
                            )
                        )
            continue

        # Simple string content (user prompt)
        if isinstance(content, str):
            if role == "user":
                messages.append(
                    StructuredMessage(
                        role="user",
                        type="text",
                        text=content,
                        timestamp=entry_ts,
                        entry_index=idx,
                    )
                )
            continue

        # Block-based content
        if isinstance(content, list):
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
                                entry_index=idx,
                            )
                        )
                elif block_type == "thinking":
                    if include_thinking:
                        thinking_text = str(block.get("thinking", ""))
                        if thinking_text.strip():
                            messages.append(
                                StructuredMessage(
                                    role="assistant",
                                    type="thinking",
                                    text=thinking_text,
                                    timestamp=entry_ts,
                                    entry_index=idx,
                                )
                            )
                elif block_type == "tool_use":
                    if include_tools:
                        tool_name = str(block.get("name", "unknown"))
                        tool_input = block.get("input", {})
                        messages.append(
                            StructuredMessage(
                                role="assistant",
                                type="tool_use",
                                text=f"{tool_name}: {json.dumps(tool_input)}",
                                timestamp=entry_ts,
                                entry_index=idx,
                            )
                        )
                elif block_type == "tool_result":
                    if include_tools:
                        result_text = str(block.get("content", ""))
                        messages.append(
                            StructuredMessage(
                                role="assistant",
                                type="tool_result",
                                text=result_text,
                                timestamp=entry_ts,
                                entry_index=idx,
                            )
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
