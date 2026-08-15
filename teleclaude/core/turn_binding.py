"""Bind accepted inbound receipts to their native transcript turns.

Per the Turn provenance invariant "injected spans are known, never parsed":
the daemon already holds the exact injected payload verbatim (a delivered
``inbound_queue`` row's ``content``) before injection, so binding is an exact
substring search for that known content within the freshly observed native
transcript entry — never a fuzzy or positional match. A unique match yields
the exact injected span and the surrounding local-human text as ordered
authored parts; no match means the entry has not appeared in the transcript
yet; more than one match is an unresolved input conflict that surfaces rather
than guesses. A durable binding cuts the turn's output generation.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.conversation_messages import (
    ParsedPeerSegment,
    format_peer_message,
    peer_segment_from_authored_span,
)
from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.db import InboundQueueRow, NativeReference, TurnAuthoredPartInput, db
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.models import HumanFacingMessage, JsonDict, MessageAuthor, MessageAuthorKind
from teleclaude.output_projection.visibility import is_internal_user_text
from teleclaude.utils.transcript import (
    _get_entries_for_agent,
    extract_real_user_text_from_entry,
    is_real_user_turn_entry,
)

if TYPE_CHECKING:
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_BINDING_ID_SEPARATOR = ":"
_GENERATION_ID_PREFIX = "gen:"
_INJECTED_PEER_PART_KIND = "injected_peer"
_LOCAL_PART_KIND = "local"
_TURN_BINDING_AMBIGUOUS_SPAN_EVENT = "turn_binding_ambiguous_injected_span"
_TURN_BINDING_CREATED_EVENT = "turn_binding_created"
_TURN_BINDING_NO_LOCAL_AUTHOR_EVENT = "turn_binding_no_local_author"
_ACCEPTED_TURN_PARTS_BOUND_EVENT = "accepted_turn_parts_bound"
_PEER_SECTION_SEPARATOR = "\n\n"
_BUNDLE_BACKED_REASON = "bundle_backed"
_LOCAL_PARTS_REASON = "local"
_RENDER_MISMATCH_REASON = "render_mismatch"
_BOUND_OUTCOME = "bound"
_ACCEPTED_TURN_ORIGIN_RECORDED_EVENT = "accepted_turn_origin_recorded"
_UI_SURFACE_OUTCOME = "ui_surface"
_CALLER_SESSION_OUTCOME = "caller_session"
_UI_ACTOR_RESOLVED_REASON = "ui_actor_resolved"
_CALLER_RESOLVED_REASON = "caller_resolved"

type NativeTurnCandidate = tuple[str, str, object]


async def _bundle_backed_parts(
    *,
    row: InboundQueueRow,
    entry_text: str,
) -> list[TurnAuthoredPartInput] | None:
    """Reconstruct per-segment peer spans from durable authorship, never text search."""
    if not row["source_message_id"]:
        return []
    records = await db.get_peer_bundle_segments(bundle_key=row["source_message_id"])
    if not records:
        return []
    rendered_segments = [
        peer_segment_from_authored_span(
            original_source_session_id=record.original_source_session_id,
            author=record.author,
            occurred_at=record.occurred_at,
            body=record.body,
            author_job_role=record.author_job_role,
        )
        for record in records
    ]
    rendered_content = format_peer_message(
        messages=cast(list[HumanFacingMessage | ParsedPeerSegment], rendered_segments)
    )
    if rendered_content != entry_text:
        return None
    parts: list[TurnAuthoredPartInput] = []
    offset = 0
    for record, rendered_segment in zip(records, rendered_segments, strict=True):
        header_end = rendered_segment.rendered_segment.index(_PEER_SECTION_SEPARATOR)
        body_start = offset + header_end + len(_PEER_SECTION_SEPARATOR)
        body_end = body_start + len(record.body.strip())
        parts.append(
            TurnAuthoredPartInput(
                part_kind=_INJECTED_PEER_PART_KIND,
                span_start=body_start,
                span_end=body_end,
                original_source_session_id=record.original_source_session_id,
                author=record.author,
                author_job_role=record.author_job_role,
            )
        )
        offset += len(rendered_segment.rendered_segment) + len(_PEER_SECTION_SEPARATOR)
    return parts


def _caller_author_from_row(row: InboundQueueRow) -> MessageAuthor | None:
    """Rebuild the typed caller author from an accepted row's flat caller columns."""
    if not row["caller_session_id"] or not row["caller_author_kind"] or not row["caller_author_display"]:
        return None
    return MessageAuthor(
        kind=MessageAuthorKind(row["caller_author_kind"]),
        display=row["caller_author_display"],
        session_id=row["caller_session_id"],
        agent_runtime=row["caller_agent_runtime"],
        thinking_mode=row["caller_thinking_mode"],
        machine_role=row["caller_machine_role"],
    )


def _ui_author_from_row(row: InboundQueueRow) -> MessageAuthor | None:
    """Resolve a UI actor whose accepted turn has no session source."""
    if not row["actor_name"]:
        return None
    return MessageAuthor(kind=MessageAuthorKind.HUMAN, display=row["actor_name"])


def _resolve_local_human_author(session: Session) -> MessageAuthor | None:
    """Resolve this session's own local-human author, or ``None`` when unresolvable."""
    if not session.human_email:
        return None
    try:
        display_name = get_identity_resolver().resolve_by_email(session.human_email).display_name
    except ValueError:
        return None
    return MessageAuthor.for_human(session_id=session.session_id, display_name=display_name)


def _native_entry_id(entry: JsonDict, agent_name: AgentName, *, timestamp: object, text: str) -> str:
    """Return the runtime's own stable per-entry id, or a deterministic fallback.

    Claude Code's JSONL entries carry a genuine per-entry ``uuid``. Codex and
    Gemini currently expose no per-message stable id at all (verified against
    live transcripts on this computer) — never a positional index per the
    Turn provenance invariant, so a deterministic hash of the entry's own
    timestamp and text stands in: stable across re-reads of the same
    transcript, unlike an array position.
    """
    if agent_name == AgentName.CLAUDE:
        native_uuid = entry.get("uuid")
        if isinstance(native_uuid, str) and native_uuid:
            return native_uuid
    digest_input = f"{timestamp}␟{text}".encode()
    return hashlib.sha256(digest_input).hexdigest()


async def _disposition_binding_conflict(
    *,
    session: Session,
    agent_name: AgentName,
    row: InboundQueueRow,
    candidates: list[NativeTurnCandidate],
    candidate_count: int,
) -> bool:
    """Persist one ambiguity terminal state and emit its sole error event."""
    candidate_references = [
        NativeReference(
            runtime=agent_name.value,
            native_session_id=session.native_session_id,
            entry_id=entry_id,
        )
        for entry_id, _entry_text, _entry_timestamp in candidates
    ]
    dispositioned = await db.mark_inbound_binding_conflict(
        inbound_queue_id=row["id"],
        candidates=candidate_references,
    )
    if dispositioned:
        logger.error(
            _TURN_BINDING_AMBIGUOUS_SPAN_EVENT,
            session_id=session.session_id,
            inbound_row_id=row["id"],
            candidate_count=candidate_count,
        )
    return dispositioned


async def _bind_local_terminal_candidates(
    *,
    session: Session,
    agent_name: AgentName,
    candidates: list[NativeTurnCandidate],
    pending_rows: list[InboundQueueRow],
    local_author: MessageAuthor | None,
) -> None:
    """Create receipt-less bindings for post-cutover terminal entries not owned by a pending receipt."""
    binding_cutover = await db.get_turn_binding_cutover()
    if binding_cutover is None:
        return
    if not candidates:
        return
    if local_author is None:
        logger.warning(_TURN_BINDING_NO_LOCAL_AUTHOR_EVENT, session_id=session.session_id, inbound_row_id=None)
        return

    for entry_id, entry_text, entry_timestamp in candidates:
        entry_dt = parse_iso_datetime(entry_timestamp)
        if entry_dt is None or entry_dt < binding_cutover:
            continue
        if any(row["content"] in entry_text for row in pending_rows):
            continue
        binding_id = f"{session.session_id}{_BINDING_ID_SEPARATOR}{entry_id}"
        generation_id = f"{_GENERATION_ID_PREFIX}{binding_id}"
        created = await db.create_turn_binding(
            binding_id=binding_id,
            session_id=session.session_id,
            inbound_queue_id=None,
            injected_span=None,
            native_reference=NativeReference(
                runtime=agent_name.value,
                native_session_id=session.native_session_id,
                entry_id=entry_id,
            ),
            parts=[
                TurnAuthoredPartInput(
                    part_kind=_LOCAL_PART_KIND,
                    span_start=0,
                    span_end=len(entry_text),
                    original_source_session_id=session.session_id,
                    author=local_author,
                )
            ],
            generation_id=generation_id,
        )
        if not created:
            continue
        logger.debug(
            _TURN_BINDING_CREATED_EVENT,
            session_id=session.session_id,
            inbound_row_id=None,
            binding_id=binding_id,
            generation_id=generation_id,
            part_count=1,
            injected_original_source_session_id=None,
        )


async def bind_pending_native_turns(session: Session) -> None:  # noqa: C901
    """Bind delivered-but-unbound accepted rows to their native transcript turns.

    Exact-substring correlation, per the Turn provenance invariant "injected
    spans are known, never parsed": a delivered row's content is searched for
    as an exact substring within each not-yet-consumed native user entry's
    text, in acceptance order. A unique match yields the exact injected span
    and the surrounding local-human text as ordered authored parts; no match
    means the entry has not appeared in the transcript yet (retried next
    poll); more than one match is an unresolved input conflict — the row
    stays unbound rather than guessed. Binding a turn cuts its output
    generation.

    Receipt-correlated entries retain exact injected spans. Genuine terminal
    entries bind directly with a receipt-less local part after the durable
    binding cutover, so every composed native turn cuts one generation.
    """
    if not session.native_log_file or not session.active_agent or not session.native_session_id:
        return
    try:
        agent_name = AgentName.from_str(session.active_agent)
    except ValueError:
        return

    pending_rows = await db.get_unbound_delivered_inbound(session_id=session.session_id)

    entries = await asyncio.to_thread(_get_entries_for_agent, session.native_log_file, agent_name)
    if not entries:
        return

    already_bound = await db.get_bound_native_entry_ids(
        native_runtime=agent_name.value, native_session_id=session.native_session_id
    )
    conflicted_entry_ids = await db.get_conflicted_native_entry_ids(
        native_runtime=agent_name.value, native_session_id=session.native_session_id
    )
    candidates: list[NativeTurnCandidate] = []
    for entry in entries:
        if not is_real_user_turn_entry(entry, agent_name):
            continue
        text = extract_real_user_text_from_entry(entry, agent_name)
        if text is None:
            continue
        if is_internal_user_text(text):
            continue
        timestamp = entry.get("timestamp")
        entry_id = _native_entry_id(entry, agent_name, timestamp=timestamp, text=text)
        if entry_id in already_bound or entry_id in conflicted_entry_ids:
            continue
        candidates.append((entry_id, text, timestamp))

    local_author = _resolve_local_human_author(session)

    remaining_pending_rows = list(pending_rows)
    for row in pending_rows:
        content = row["content"]
        matches = [c for c in candidates if content in c[1]]
        if not matches:
            continue  # not in the transcript yet — try again next poll
        if len(matches) > 1:
            if await _disposition_binding_conflict(
                session=session,
                agent_name=agent_name,
                row=row,
                candidates=matches,
                candidate_count=len(matches),
            ):
                candidates[:] = [candidate for candidate in candidates if candidate not in matches]
                remaining_pending_rows.remove(row)
            continue

        entry_id, entry_text, _entry_timestamp = matches[0]
        # Exact-substring match only, never fuzzy/positional (Turn provenance
        # invariant): a repeated occurrence of the injected content *within*
        # the sole candidate entry — e.g. a local body that happens to
        # contain the same text — is exactly as ambiguous as multiple
        # candidate entries, and must surface the same input-conflict
        # refusal rather than silently binding the first occurrence.
        occurrence_count = entry_text.count(content)
        if occurrence_count != 1:
            if await _disposition_binding_conflict(
                session=session,
                agent_name=agent_name,
                row=row,
                candidates=matches,
                candidate_count=occurrence_count,
            ):
                candidates.remove(matches[0])
                remaining_pending_rows.remove(row)
            continue
        span_start = entry_text.index(content)
        span_end = span_start + len(content)

        bundle_parts = await _bundle_backed_parts(row=row, entry_text=entry_text)
        if bundle_parts is None:
            binding_id = f"{session.session_id}{_BINDING_ID_SEPARATOR}{entry_id}"
            logger.info(
                _ACCEPTED_TURN_PARTS_BOUND_EVENT,
                outcome=_BOUND_OUTCOME,
                reason=_RENDER_MISMATCH_REASON,
                binding_id=binding_id,
                inbound_queue_id=row["id"],
                session_id=session.session_id,
                bundle_key=row["source_message_id"],
                segment_count=0,
                part_count=0,
                render_equals_content=False,
            )
            if await _disposition_binding_conflict(
                session=session,
                agent_name=agent_name,
                row=row,
                candidates=matches,
                candidate_count=1,
            ):
                candidates.remove(matches[0])
                remaining_pending_rows.remove(row)
            continue

        bundle_backed = bool(bundle_parts)
        caller_author = _caller_author_from_row(row)
        ui_author = _ui_author_from_row(row)
        injected_original_source = row["caller_session_id"] or session.session_id
        injected_author = caller_author or ui_author or local_author
        parts = list(bundle_parts)
        if not parts:
            if injected_author is None:
                logger.warning(
                    _TURN_BINDING_NO_LOCAL_AUTHOR_EVENT, session_id=session.session_id, inbound_row_id=row["id"]
                )
                continue
            if span_start > 0:
                if local_author is None:
                    continue
                parts.append(
                    TurnAuthoredPartInput(
                        part_kind=_LOCAL_PART_KIND,
                        span_start=0,
                        span_end=span_start,
                        original_source_session_id=session.session_id,
                        author=local_author,
                    )
                )
            is_ui_origin = caller_author is None and ui_author is not None
            parts.append(
                TurnAuthoredPartInput(
                    part_kind=_INJECTED_PEER_PART_KIND if caller_author is not None else _LOCAL_PART_KIND,
                    span_start=span_start,
                    span_end=span_end,
                    original_source_session_id=None if is_ui_origin else injected_original_source,
                    author=injected_author,
                    author_job_role=row["caller_job_role"],
                    origin_surface=row["origin"] if is_ui_origin else None,
                )
            )
            if span_end < len(entry_text):
                if local_author is None:
                    continue
                parts.append(
                    TurnAuthoredPartInput(
                        part_kind=_LOCAL_PART_KIND,
                        span_start=span_end,
                        span_end=len(entry_text),
                        original_source_session_id=session.session_id,
                        author=local_author,
                    )
                )

        binding_id = f"{session.session_id}{_BINDING_ID_SEPARATOR}{entry_id}"
        generation_id = f"{_GENERATION_ID_PREFIX}{binding_id}"
        created = await db.create_turn_binding(
            binding_id=binding_id,
            session_id=session.session_id,
            inbound_queue_id=row["id"],
            injected_span=(span_start, span_end),
            native_reference=NativeReference(
                runtime=agent_name.value,
                native_session_id=session.native_session_id,
                entry_id=entry_id,
            ),
            parts=parts,
            generation_id=generation_id,
        )
        if not created:
            continue
        candidates.remove(matches[0])
        remaining_pending_rows.remove(row)
        logger.debug(
            _TURN_BINDING_CREATED_EVENT,
            session_id=session.session_id,
            inbound_row_id=row["id"],
            binding_id=binding_id,
            generation_id=generation_id,
            part_count=len(parts),
            injected_original_source_session_id=injected_original_source,
        )
        logger.info(
            _ACCEPTED_TURN_PARTS_BOUND_EVENT,
            outcome=_BOUND_OUTCOME,
            reason=_BUNDLE_BACKED_REASON if bundle_backed else _LOCAL_PARTS_REASON,
            binding_id=binding_id,
            inbound_queue_id=row["id"],
            session_id=session.session_id,
            bundle_key=row["source_message_id"],
            segment_count=len(bundle_parts),
            part_count=len(parts),
            render_equals_content=bundle_backed,
        )
        logger.info(
            _ACCEPTED_TURN_ORIGIN_RECORDED_EVENT,
            outcome=_UI_SURFACE_OUTCOME if ui_author is not None and caller_author is None else _CALLER_SESSION_OUTCOME,
            reason=_UI_ACTOR_RESOLVED_REASON
            if ui_author is not None and caller_author is None
            else _CALLER_RESOLVED_REASON,
            inbound_queue_id=row["id"],
            binding_id=binding_id,
            session_id=session.session_id,
            surface=row["origin"] if ui_author is not None and caller_author is None else None,
            author_kind=injected_author.kind.value if injected_author is not None else None,
            original_source_present=bool(caller_author),
        )

    await _bind_local_terminal_candidates(
        session=session,
        agent_name=agent_name,
        candidates=candidates,
        pending_rows=remaining_pending_rows,
        local_author=local_author,
    )
