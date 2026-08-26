"""Canonical conversation projection route.

Applies visibility policy to transcript entries and yields ProjectedBlock objects.
Reuses existing normalization infrastructure from utils.transcript.

Included parts (yielded as ProjectedBlock):
    - user ``text`` (plain string or block-based)
    - assistant ``text``, ``input_text``, ``output_text`` (normalized to block_type="text")
    - assistant ``thinking`` (when policy.include_thinking is True)
    - assistant ``pre_tool_use`` (when policy.include_tools or tool name in visible_tool_names)
    - assistant ``tool_result`` (when policy.include_tool_results; user tool_result-only
      messages are re-roled to assistant per Claude's transcript convention)
    - ``compaction`` markers (system role, always emitted)

Input sanitization rules (applied to user text before emission):
    - Agent-CLI runtime artifacts (hook feedback prefixes, ``<system-reminder>``
      and ``<task-notification>`` wrappers, XML-style tag prefixes) are stripped.
      ``[TeleClaude …]`` and ``[Orchestrator …]`` bracket headers are NOT
      stripped — brackets are identity markers, receivers parse the role.
    - User messages emptied by sanitization are dropped from the public stream.

Authorship: every emitted ``ProjectedBlock`` carries a resolved ``author``.
User-channel text is classified once — an ordinary turn (no recognized
machine bracket) is stamped ``HUMAN``; a recognized bracket (a machine role,
a TeleClaude notification, or a peer-bridge header) is stamped ``MACHINE``
with that bracket's own label. Assistant text is stamped ``AGENT``. Authorship
travels with the block from this classification and is never re-derived
downstream from the transcript channel role.

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

from collections.abc import Iterable, Iterator, Mapping
from typing import cast

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.injected_text import (
    UNSEEN_ENTRY_KINDS,
    TranscriptEntryKind,
    TranscriptTextClassification,
    cut_transcript_entry,
)
from teleclaude.core.models import JsonDict
from teleclaude.output_projection.models import ProjectedAuthor, ProjectedAuthorKind, ProjectedBlock, VisibilityPolicy
from teleclaude.output_projection.visibility import resolve_projected_text_author
from teleclaude.utils.transcript._iterators import _get_entries_for_agent
from teleclaude.utils.transcript._parsers import normalize_transcript_entry_message
from teleclaude.utils.transcript._tool_calls import (  # type: ignore[attr-defined]
    _is_compaction_entry,
    _is_user_tool_result_only_message,
)
from teleclaude.utils.transcript._utils import _parse_timestamp

logger = get_logger(__name__)


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
    policy: VisibilityPolicy,
    *,
    entry_ts: str | None,
    entry_idx: int,
    file_index: int,
) -> Iterator[ProjectedBlock]:
    for segment in cut_transcript_entry(content, is_user_entry=True):
        segment_text = content[segment.body_span[0] : segment.body_span[1]] if segment.body_span else segment.text
        classification, visible, author = _classify_user_text(segment.opening or segment_text, policy)
        if segment.kind is not None:
            classification = TranscriptTextClassification(segment.kind)
        if classification.kind in UNSEEN_ENTRY_KINDS:
            continue
        if classification.kind is TranscriptEntryKind.IDENTITY_CONTENT:
            visible = policy.include_system_messages or (segment.opening or "").startswith("[Peer ")
            author = ProjectedAuthor(kind=ProjectedAuthorKind.MACHINE, label="Peer")
        if not visible or not segment_text.strip():
            continue
        yield ProjectedBlock(
            block_type="text",
            block={"type": "text", "text": segment_text},
            role="user",
            timestamp=entry_ts,
            entry_index=entry_idx,
            file_index=file_index,
            author=author,
        )


def _classify_user_text(
    text: str, policy: VisibilityPolicy
) -> tuple[TranscriptTextClassification, bool, ProjectedAuthor]:
    """Classify user text once and derive its visibility and author from that category.

    Returns the category, the keep/drop decision, and the resolved author so
    callers stamp the emitted block with the same classification used for the
    visibility gate — one classification pass per block, never two. The
    returned author is meaningless when ``visible`` is False; callers that
    drop the block never read it.
    """
    classification, label = resolve_projected_text_author(text)
    if classification.kind in UNSEEN_ENTRY_KINDS:
        visible = False
    elif classification.kind is TranscriptEntryKind.IDENTITY_CONTENT and label != "Peer":
        visible = policy.include_system_messages
    else:
        visible = True
    if classification.kind is TranscriptEntryKind.ORDINARY:
        author = ProjectedAuthor(kind=ProjectedAuthorKind.HUMAN)
    elif label is not None:
        author = ProjectedAuthor(kind=ProjectedAuthorKind.MACHINE, label=label)
    else:
        # SIDE_CHANNEL: never visible, no label resolved, author is unused.
        author = ProjectedAuthor(kind=ProjectedAuthorKind.AGENT)
    return classification, visible, author


def _project_user_text_block(
    block: Mapping[str, object],
    policy: VisibilityPolicy,
    *,
    entry_ts: str | None,
    entry_idx: int,
    file_index: int,
) -> Iterator[ProjectedBlock]:
    text = str(block.get("text", ""))
    classification, visible, author = _classify_user_text(text, policy)
    if not visible:
        if classification.kind is not TranscriptEntryKind.ORDINARY:
            logger.debug("Sanitized side-channel user text block", entry_index=entry_idx)
        return
    yield ProjectedBlock(
        block_type="text",
        block=block,  # type: ignore[arg-type]
        role="user",
        timestamp=entry_ts,
        entry_index=entry_idx,
        file_index=file_index,
        author=author,
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
        if role == "user":
            yield from _project_user_text_block(
                block,
                policy,
                entry_ts=entry_ts,
                entry_idx=entry_idx,
                file_index=file_index,
            )
            return
        yield ProjectedBlock(
            block_type="text",
            block=block,  # type: ignore[arg-type]
            role=role,
            timestamp=entry_ts,
            entry_index=entry_idx,
            file_index=file_index,
            author=ProjectedAuthor(kind=ProjectedAuthorKind.AGENT),
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
    if block_type == "pre_tool_use":
        tool_name = str(block.get("name", "unknown"))
        if tool_name in policy.visible_tool_names or policy.include_tools:
            yield ProjectedBlock(
                block_type="pre_tool_use",
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
        logger.debug("Skipping entry with missing/non-string role", entry_index=entry_idx)
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
        yield from _project_user_text(
            content,
            policy,
            entry_ts=entry_ts,
            entry_idx=entry_idx,
            file_index=file_index,
        )
        return
    if not isinstance(content, list):
        logger.debug("Skipping entry with non-list content", entry_index=entry_idx, role=role)
        return
    if role not in ("user", "assistant"):
        logger.debug("Skipping non-user/non-assistant block-based entry", entry_index=entry_idx, role=role)
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
            logger.debug("Skipping non-Mapping entry", entry_index=entry_idx)
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
            logger.debug("Skipping summary entry", entry_index=entry_idx)
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
            logger.debug("Skipping None entries for file", file_path=file_path, file_index=file_idx)
            continue
        blocks = list(project_entries(entries, policy, since=since, file_index=file_idx))
        all_blocks.extend(blocks)

    return all_blocks
