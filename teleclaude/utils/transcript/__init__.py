"""Parse and convert Claude/Gemini/Codex session transcripts to markdown."""

import importlib
from typing import TYPE_CHECKING

from teleclaude.utils.transcript._block_renderers import (
    _extract_tool_subject,
    _process_entry,
    _process_list_content,
    _process_string_content,
    _process_text_block,
    _process_thinking_block,
    _process_tool_result_block,
    _process_tool_use_block,
    _should_skip_entry,
    iter_assistant_blocks,
)
from teleclaude.utils.transcript._checkpoint_anchors import (
    CheckpointAnchor,
    find_checkpoint_scope_start_idx,
    find_last_checkpoint_anchor,
    is_checkpoint_anchor_entry,
)
from teleclaude.utils.transcript._extraction import (
    _find_workdir_in_obj,
    count_renderable_assistant_blocks,
    extract_last_authored_exchange,
    extract_last_turn_boundary_timestamp,
    extract_last_user_message_with_timestamp,
    extract_workdir_from_transcript,
    get_assistant_messages_since,
    parse_session_transcript,
    transcript_has_stop_response,
)
from teleclaude.utils.transcript._identity import native_entry_id
from teleclaude.utils.transcript._iterators import (
    TRANSCRIPT_READERS,
    TranscriptReader,
    _entry_role,
    _get_entries_for_agent,
    _is_rotation_fallback_candidate,
    _iter_claude_entries,
    _iter_codex_entries,
    _iter_gemini_entries,
    _iter_jsonl_entries,
    _iter_jsonl_entries_tail,
    _start_index_after_timestamp_or_rotation,
)
from teleclaude.utils.transcript._parsers import (
    _extract_codex_reasoning_text,
    normalize_transcript_entry_message,
    unwrap_pasted_content,
)

if TYPE_CHECKING:
    from teleclaude.utils.transcript._rendering import (
        render_agent_output,
        render_clean_agent_output,
        render_transcript_from_entries,
    )
from teleclaude.utils.transcript._tool_calls import (  # type: ignore[attr-defined]
    StructuredMessage,
    ToolCallRecord,
    TurnTimeline,
    _is_compaction_entry,
    _is_user_tool_result_only_message,
    _parse_function_call_arguments,
    extract_effective_tool_calls,
    extract_messages_from_chain,
    extract_structured_messages,
    extract_tool_calls_current_turn,
)
from teleclaude.utils.transcript._user_turns import (
    ClaudeTurnCommitment,
    ClaudeTurnCommitmentOutcome,
    ClaudeTurnCommitmentReason,
    ClaudeTurnCommitmentResolver,
    TurnStart,
    extract_authored_user_text,
    find_last_turn_start,
    find_turn_start_idx,
    is_authored_user_entry,
    is_runtime_artifact_entry,
    is_runtime_artifact_text,
    is_turn_start_entry,
    normalize_runtime_user_text,
    resolve_claude_turn_commitment,
)
from teleclaude.utils.transcript._utils import (
    CHECKPOINT_JSONL_TAIL_ENTRIES,
    CHECKPOINT_JSONL_TAIL_READ_BYTES,
    _apply_tail_limit,
    _apply_tail_limit_codex,
    _escape_triple_backticks,
    _format_thinking,
    _format_timestamp_prefix,
    _italicize_thinking_line,
    _parse_timestamp,
    _wrap_thinking_emphasis,
)
from teleclaude.utils.transcript.tailer import (
    TranscriptTailBatch,
    TranscriptTailCursor,
    TranscriptTailReadError,
    read_appended_jsonl_entries,
)

__all__ = [
    # _rendering
    # _utils
    "CHECKPOINT_JSONL_TAIL_ENTRIES",
    "CHECKPOINT_JSONL_TAIL_READ_BYTES",
    "TRANSCRIPT_READERS",
    # _tool_calls
    "CheckpointAnchor",
    "ClaudeTurnCommitment",
    "ClaudeTurnCommitmentOutcome",
    "ClaudeTurnCommitmentReason",
    "ClaudeTurnCommitmentResolver",
    "StructuredMessage",
    "ToolCallRecord",
    "TranscriptReader",
    "TranscriptTailBatch",
    "TranscriptTailCursor",
    "TranscriptTailReadError",
    "TurnStart",
    "TurnTimeline",
    "_apply_tail_limit",
    "_apply_tail_limit_codex",
    # _iterators
    "_entry_role",
    "_escape_triple_backticks",
    # _parsers
    "_extract_codex_reasoning_text",
    # _extraction
    # _block_renderers
    "_extract_tool_subject",
    "_find_workdir_in_obj",
    "_format_thinking",
    "_format_timestamp_prefix",
    "_get_entries_for_agent",
    "_is_compaction_entry",
    "_is_rotation_fallback_candidate",
    "_is_user_tool_result_only_message",
    "_italicize_thinking_line",
    "_iter_claude_entries",
    "_iter_codex_entries",
    "_iter_gemini_entries",
    "_iter_jsonl_entries",
    "_iter_jsonl_entries_tail",
    "_parse_function_call_arguments",
    "_parse_timestamp",
    "_process_entry",
    "_process_list_content",
    "_process_string_content",
    "_process_text_block",
    "_process_thinking_block",
    "_process_tool_result_block",
    "_process_tool_use_block",
    "_should_skip_entry",
    "_start_index_after_timestamp_or_rotation",
    "_wrap_thinking_emphasis",
    "count_renderable_assistant_blocks",
    "extract_authored_user_text",
    "extract_effective_tool_calls",
    "extract_last_authored_exchange",
    "extract_last_turn_boundary_timestamp",
    "extract_last_user_message_with_timestamp",
    "extract_messages_from_chain",
    "extract_structured_messages",
    "extract_tool_calls_current_turn",
    "extract_workdir_from_transcript",
    "find_checkpoint_scope_start_idx",
    "find_last_checkpoint_anchor",
    "find_last_turn_start",
    "find_turn_start_idx",
    "get_assistant_messages_since",
    "is_authored_user_entry",
    "is_checkpoint_anchor_entry",
    "is_runtime_artifact_entry",
    "is_runtime_artifact_text",
    "is_turn_start_entry",
    "iter_assistant_blocks",
    "native_entry_id",
    "normalize_runtime_user_text",
    "normalize_transcript_entry_message",
    "parse_session_transcript",
    "read_appended_jsonl_entries",
    "render_agent_output",
    "render_clean_agent_output",
    "render_transcript_from_entries",
    "resolve_claude_turn_commitment",
    "transcript_has_stop_response",
    "unwrap_pasted_content",
]


def __getattr__(name: str) -> object:
    if name in {
        "render_transcript_from_entries",
        "render_agent_output",
        "render_clean_agent_output",
    }:
        module = importlib.import_module("teleclaude.utils.transcript._rendering")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
