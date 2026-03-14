"""Canonical conversation projection route.

Applies visibility policy to transcript entries and yields ProjectedBlock objects.
Reuses existing normalization infrastructure from utils.transcript.

Included parts (yielded as ProjectedBlock):
    - user ``text`` (plain string or block-based)
    - assistant ``text``, ``input_text``, ``output_text`` (normalized to block_type="text")
    - assistant ``thinking`` (when policy.include_thinking is True)
    - assistant ``tool_use`` (when policy.include_tools or tool name in visible_tool_names)
    - assistant ``tool_result`` (when policy.include_tool_results; user tool_result-only
      messages are re-roled to assistant per Claude's transcript convention)
    - ``compaction`` markers (system role, always emitted)

Input sanitization rules (applied to user text before emission):
    - User text starting with ``TELECLAUDE_SYSTEM_PREFIX`` ("[TeleClaude") is stripped.
    - User text that is a pure ``<task-notification>`` or ``<system-reminder>`` wrapper
      is stripped.
    - User messages emptied by sanitization are dropped from the public stream.

Intentionally dropped data:
    - Non-Mapping entries (malformed transcript lines)
    - ``type: "summary"`` entries (internal compaction metadata)
    - Entries with un-normalizable messages (no ``message`` or ``payload`` key)
    - Messages with missing or non-string ``role``
    - Messages with non-user, non-assistant roles and block-based content (system entries)
    - Non-dict blocks within content lists
    - Text blocks with empty/whitespace-only content
    - Non-list, non-string content on non-user-tool-result messages
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Mapping
from typing import cast

from teleclaude.constants import is_internal_user_text
from teleclaude.core.agents import AgentName
from teleclaude.core.models import JsonDict
from teleclaude.output_projection.models import ProjectedBlock, VisibilityPolicy
from teleclaude.utils.transcript import (
    _get_entries_for_agent,
    _is_compaction_entry,
    _is_user_tool_result_only_message,
    _parse_timestamp,
    normalize_transcript_entry_message,
)

logger = logging.getLogger(__name__)


def _compaction_block(entry_ts: str | None, entry_idx: int, file_index: int) -> ProjectedBlock:
    return ProjectedBlock(
        block_type="compaction",
        block={"type": "compaction", "text": "Context compacted"},
        role="system",
        timestamp=entry_ts,
        entry_index=entry_idx,
        file_index=file_index,
    )


def _project_user_tool_results(
    content: object,
    policy: VisibilityPolicy,
    *,
    entry_ts: str | None,
    entry_idx: int,
    file_index: int,
) -> Iterator[ProjectedBlock]:
    if not policy.include_tool_results or not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            yield ProjectedBlock(
                block_type="tool_result",
                block=block,
                role="assistant",
                timestamp=entry_ts,
                entry_index=entry_idx,
                file_index=file_index,
            )


def _project_user_text(
    content: str,
    *,
    entry_ts: str | None,
    entry_idx: int,
    file_index: int,
) -> Iterator[ProjectedBlock]:
    if is_internal_user_text(content):
        logger.debug("Sanitized TeleClaude-internal user text at index %d", entry_idx)
        return
    yield ProjectedBlock(
        block_type="text",
        block={"type": "text", "text": content},
        role="user",
        timestamp=entry_ts,
        entry_index=entry_idx,
        file_index=file_index,
    )


def _project_content_block(
    block: Mapping[str, object],
    *,
    role: str,
    policy: VisibilityPolicy,
    entry_ts: str | None,
    entry_idx: int,
    file_index: int,
) -> Iterator[ProjectedBlock]:
    block_type = str(block.get("type", ""))
    if block_type in ("text", "input_text", "output_text"):
        text = str(block.get("text", ""))
        if not text.strip():
            return
        if role == "user" and is_internal_user_text(text):
            logger.debug("Sanitized TeleClaude-internal user text block at index %d", entry_idx)
            return
        yield ProjectedBlock(
            block_type="text",
            block=block,  # type: ignore[arg-type]
            role=role,
            timestamp=entry_ts,
            entry_index=entry_idx,
            file_index=file_index,
        )
        return
    if block_type == "thinking":
        thinking_text = str(block.get("thinking", ""))
        if policy.include_thinking and thinking_text.strip():
            yield ProjectedBlock(
                block_type="thinking",
                block=block,  # type: ignore[arg-type]
                role="assistant",
                timestamp=entry_ts,
                entry_index=entry_idx,
                file_index=file_index,
            )
        return
    if block_type == "tool_use":
        tool_name = str(block.get("name", "unknown"))
        if tool_name in policy.visible_tool_names or policy.include_tools:
            yield ProjectedBlock(
                block_type="tool_use",
                block=block,  # type: ignore[arg-type]
                role="assistant",
                timestamp=entry_ts,
                entry_index=entry_idx,
                file_index=file_index,
            )
        return
    if block_type == "tool_result" and policy.include_tool_results:
        yield ProjectedBlock(
            block_type="tool_result",
            block=block,  # type: ignore[arg-type]
            role="assistant",
            timestamp=entry_ts,
            entry_index=entry_idx,
            file_index=file_index,
        )


def _project_message_blocks(
    message: JsonDict,
    policy: VisibilityPolicy,
    *,
    entry_ts: str | None,
    entry_idx: int,
    file_index: int,
) -> Iterator[ProjectedBlock]:
    role = message.get("role")
    if not isinstance(role, str):
        logger.debug("Skipping entry with missing/non-string role at index %d", entry_idx)
        return

    content = message.get("content")
    if role == "user" and _is_user_tool_result_only_message(message):
        yield from _project_user_tool_results(
            content,
            policy,
            entry_ts=entry_ts,
            entry_idx=entry_idx,
            file_index=file_index,
        )
        return
    if role == "user" and isinstance(content, str):
        yield from _project_user_text(content, entry_ts=entry_ts, entry_idx=entry_idx, file_index=file_index)
        return
    if not isinstance(content, list):
        logger.debug("Skipping entry with non-list content at index %d (role=%s)", entry_idx, role)
        return
    if role not in ("user", "assistant"):
        logger.debug("Skipping non-user/non-assistant block-based entry at index %d (role=%s)", entry_idx, role)
        return
    for block in content:
        if isinstance(block, Mapping):
            yield from _project_content_block(
                cast(Mapping[str, object], block),
                role=role,
                policy=policy,
                entry_ts=entry_ts,
                entry_idx=entry_idx,
                file_index=file_index,
            )


def project_entries(
    entries: Iterable[object],
    policy: VisibilityPolicy,
    since: str | None = None,
    file_index: int = 0,
) -> Iterator[ProjectedBlock]:
    """Apply visibility policy to transcript entries, yielding visible projected blocks.

    Reuses normalize_transcript_entry_message() and _parse_timestamp() from
    utils.transcript. Does not load files — accepts already-loaded entry iterables.

    Supports transcript-chain traversal and incremental projection from a
    since marker (ISO 8601 string), matching the ``<=`` comparison used in
    extract_structured_messages().

    Args:
        entries: Iterable of transcript entries (already loaded).
        policy: Visibility policy controlling which block types are emitted.
        since: Optional ISO 8601 UTC timestamp; skip entries at or before this time.
        file_index: Position in the chain (passed through to ProjectedBlock).

    Yields:
        ProjectedBlock for each visible block in the entries.
    """
    since_dt = _parse_timestamp(since) if since else None
    for entry_idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            logger.debug("Skipping non-Mapping entry at index %d", entry_idx)
            continue
        entry_map = cast(Mapping[str, object], entry)

        entry_ts_str = entry_map.get("timestamp")
        entry_ts: str | None = None
        if isinstance(entry_ts_str, str):
            entry_ts = entry_ts_str
            if since_dt:
                entry_dt = _parse_timestamp(entry_ts_str)
                if entry_dt and entry_dt <= since_dt:
                    continue

        if entry_map.get("type") == "summary":
            logger.debug("Skipping summary entry at index %d", entry_idx)
            continue

        if _is_compaction_entry(entry_map, entry_idx):  # type: ignore[arg-type]
            yield _compaction_block(entry_ts, entry_idx, file_index)
            continue

        message = normalize_transcript_entry_message(entry_map)
        if not isinstance(message, dict):
            continue
        yield from _project_message_blocks(
            message,  # type: ignore[arg-type]
            policy,
            entry_ts=entry_ts,
            entry_idx=entry_idx,
            file_index=file_index,
        )


def project_conversation_chain(
    file_paths: list[str],
    agent_name: AgentName,
    policy: VisibilityPolicy,
    since: str | None = None,
) -> list[ProjectedBlock]:
    """Project all entries from a transcript chain through the canonical projection route.

    Reads files in order (oldest first) and applies visibility policy to each entry.
    Provides the stable consumer contract for history API, web live SSE, and
    future mirror/search adoption.

    Args:
        file_paths: Ordered list of transcript file paths (oldest first).
        agent_name: Agent name for iterator selection.
        policy: Visibility policy controlling which block types are emitted.
        since: Optional ISO 8601 UTC timestamp filter.

    Returns:
        List of ProjectedBlock objects in chronological order.
    """
    all_blocks: list[ProjectedBlock] = []
    for file_idx, file_path in enumerate(file_paths):
        entries = _get_entries_for_agent(file_path, agent_name)
        if entries is None:
            logger.debug("Skipping None entries for file %s (index %d)", file_path, file_idx)
            continue
        blocks = list(project_entries(entries, policy, since=since, file_index=file_idx))
        all_blocks.extend(blocks)

    return all_blocks
