"""Bind accepted inbound receipts to their native transcript turns.

Each native entry is composed once from closed envelope delimiters and durable
accepted receipts. The scanner supplies exact framing/body spans; receipt
order supplies occurrence correlation. Rendered payload text never participates
in that decision. A durable binding cuts the turn's output generation.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from enum import StrEnum
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.conversation_messages import peer_segment_from_authored_span
from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.db import InboundQueueRow, NativeReference, TurnAuthoredPartInput, TurnReceiptEnvelopeInput, db
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.inbound_types import TurnPartKind
from teleclaude.core.injected_text import (
    InjectedEnvelopeCandidate,
    InjectedTextSourceFeature,
    TranscriptEntryKind,
    classify_transcript_text,
    scan_injected_envelopes,
)
from teleclaude.core.models import JsonDict, MessageAuthor, MessageAuthorKind
from teleclaude.utils.transcript import (
    ClaudeTurnCommitment,
    ClaudeTurnCommitmentOutcome,
    ClaudeTurnCommitmentResolver,
    _get_entries_for_agent,
    extract_real_user_text_from_entry,
    is_real_user_turn_entry,
)

if TYPE_CHECKING:
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_BINDING_ID_SEPARATOR = ":"
_GENERATION_ID_PREFIX = "gen:"
_REMINDER_ROLE_LABEL = "Reminder"
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
_CLAUDE_CANDIDATE_OBSERVED_EVENT = "claude_receiptless_candidate_observed"
_CLAUDE_COMMITMENT_EVENT = "claude_receiptless_turn_commitment"
_USER_REFLECTION_PROJECTION_EVENT = "user_reflection_projection_decision"
_NATIVE_ENTRY_CLASSIFICATION_EVENT = "native_entry_classification_committed"
_CONVERSATION_TEXT_EXTRACTION_EVENT = "conversation_text_extraction_committed"
_BINDING_CONFLICT_EVENT = "native_injected_envelope_correlation_conflict"


class UserReflectionProjectionOutcome(StrEnum):
    """Closed source-level user-reflection projection outcomes."""

    SENT = "sent"
    DEFERRED = "deferred"
    SUPPRESSED = "suppressed"
    FAILED = "failed"


class UserReflectionProjectionReason(StrEnum):
    """Stable reasons for user-reflection projection outcomes."""

    PLATFORM_RECEIPT = "platform_receipt"
    PROJECTION_WATERMARK = "projection_watermark"
    STALE_ORIGIN = "stale_origin"
    BINDING_CONFLICT = "binding_conflict"
    ACCEPTED_RECEIPT_UNBOUND = "accepted_receipt_unbound"
    DAEMON_CONTROL = "daemon_control"
    ORIGIN_ALREADY_VISIBLE = "origin_already_visible"
    TARGET_UNAVAILABLE = "target_unavailable"
    NO_REFLECTABLE_PART = "no_reflectable_part"
    TRANSPORT_FAILURE = "transport_failure"


type NativeTurnCandidate = tuple[str, str, object]
type _CandidateObservationKey = tuple[str, str | None, str]
type _ProjectionObservationKey = tuple[str, str | None, str | None]

_observed_claude_candidates: set[_CandidateObservationKey] = set()
_last_claude_commitments: dict[_CandidateObservationKey, tuple[str, str]] = {}
_last_user_reflection_decisions: dict[_ProjectionObservationKey, tuple[str, str, str | None, tuple[str, ...]]] = {}


def observe_user_reflection_projection(
    session: Session,
    *,
    native_entry_id: str | None,
    commitment: ClaudeTurnCommitment | None,
    binding_id: str | None,
    outcome: UserReflectionProjectionOutcome,
    reason: StrEnum,
    platform_message_ids: Sequence[str] = (),
) -> None:
    """Record a body-free source-level decision only when its state changes."""
    observation_key = (session.session_id, session.native_session_id, native_entry_id)
    decision = (outcome.value, reason.value, binding_id, tuple(platform_message_ids))
    if _last_user_reflection_decisions.get(observation_key) == decision:
        return
    _last_user_reflection_decisions[observation_key] = decision
    logger.info(
        _USER_REFLECTION_PROJECTION_EVENT,
        outcome=outcome.value,
        reason=reason.value,
        session_id=session.session_id,
        native_session_id=session.native_session_id,
        parent_entry_id=commitment.parent_entry_id if commitment is not None else None,
        native_entry_id=native_entry_id,
        binding_id=binding_id,
        platform_message_ids=list(platform_message_ids),
        platform_message_count=len(platform_message_ids),
    )


async def _bundle_backed_parts(
    *,
    row: InboundQueueRow,
    envelope_start: int,
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
    parts: list[TurnAuthoredPartInput] = []
    offset = envelope_start
    for record, rendered_segment in zip(records, rendered_segments, strict=True):
        header_end = rendered_segment.rendered_segment.index(_PEER_SECTION_SEPARATOR)
        body_start = offset + header_end + len(_PEER_SECTION_SEPARATOR)
        body_end = body_start + len(record.body.strip())
        parts.append(
            TurnAuthoredPartInput(
                part_kind=TurnPartKind.INJECTED_PEER,
                span_start=body_start,
                span_end=body_end,
                original_source_session_id=record.original_source_session_id,
                author=record.author,
                author_job_role=record.author_job_role,
            )
        )
        offset += len(rendered_segment.rendered_segment) + len(_PEER_SECTION_SEPARATOR)
    return parts


async def _envelope_count_for_receipt(row: InboundQueueRow) -> int:
    """Return the number of canonical envelopes a receipt durably owns."""
    if not row["source_message_id"]:
        return 1
    records = await db.get_peer_bundle_segments(bundle_key=row["source_message_id"])
    return len(records) if records else 1


def _source_feature_for_envelope(envelope: InjectedEnvelopeCandidate) -> InjectedTextSourceFeature | None:
    """Return an envelope's structurally declared producer when its grammar names one."""
    if envelope.opening.startswith("[Peer "):
        return InjectedTextSourceFeature.PEER_BUNDLE
    if envelope.opening.startswith("[Reminder "):
        return InjectedTextSourceFeature.REMINDER
    if envelope.kind is TranscriptEntryKind.IDENTITY_CONTENT:
        return InjectedTextSourceFeature.CALLER_SEND
    return None


def _receipt_matches_envelope(row: InboundQueueRow, envelope: InjectedEnvelopeCandidate) -> bool:
    """Require every structural fact available in an envelope before correlating it."""
    if TranscriptEntryKind(row["text_kind"]) is not envelope.kind:
        return False
    envelope_source_feature = _source_feature_for_envelope(envelope)
    return envelope_source_feature is None or row["source_feature"] == envelope_source_feature.value


async def _match_receipts_in_acceptance_order(
    *,
    rows: list[InboundQueueRow],
    envelopes: list[InjectedEnvelopeCandidate],
) -> list[tuple[InboundQueueRow, int, InjectedEnvelopeCandidate]] | None:
    """Correlate one entry only when receipt order determines every envelope uniquely."""
    matched: list[tuple[InboundQueueRow, int, InjectedEnvelopeCandidate]] = []
    envelope_offset = 0
    for row in rows:
        occurrence_key = row["occurrence_key"]
        if not occurrence_key:
            return None
        count = await _envelope_count_for_receipt(row)
        if envelope_offset + count > len(envelopes):
            return None
        row_envelopes = envelopes[envelope_offset : envelope_offset + count]
        if not all(_receipt_matches_envelope(row, envelope) for envelope in row_envelopes):
            return None
        matched.extend((row, envelope_index, envelope) for envelope_index, envelope in enumerate(row_envelopes))
        envelope_offset += count
        if envelope_offset == len(envelopes):
            return matched
    return None


async def _receipt_rows_covering_envelopes(
    rows: list[InboundQueueRow],
    envelope_count: int,
) -> list[InboundQueueRow] | None:
    """Take an exact acceptance-ordered receipt prefix for one native entry."""
    selected: list[InboundQueueRow] = []
    covered = 0
    for row in rows:
        covered += await _envelope_count_for_receipt(row)
        selected.append(row)
        if covered == envelope_count:
            return selected
        if covered > envelope_count:
            return None
    return None


async def _record_binding_conflict(
    *,
    rows: list[InboundQueueRow],
    session: Session,
    agent_name: AgentName,
    entry_id: str,
) -> None:
    """Persist a body-free ambiguity disposition instead of guessing a receipt."""
    candidate = NativeReference(
        runtime=agent_name.value,
        native_session_id=session.native_session_id,
        entry_id=entry_id,
    )
    for row in rows:
        if await db.mark_inbound_binding_conflict(inbound_queue_id=row["id"], candidates=[candidate]):
            logger.warning(
                _BINDING_CONFLICT_EVENT,
                session_id=session.session_id,
                native_session_id=session.native_session_id,
                native_entry_id=entry_id,
                inbound_queue_id=row["id"],
                occurrence_key=row["occurrence_key"],
                source_feature=row["source_feature"],
                text_kind=row["text_kind"],
            )


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


async def _bind_local_terminal_candidates(
    *,
    session: Session,
    agent_name: AgentName,
    entries: list[JsonDict],
    candidates: list[NativeTurnCandidate],
    pending_rows: list[InboundQueueRow],
    local_author: MessageAuthor | None,
) -> None:
    """Create receipt-less bindings for post-cutover terminal entries not owned by a pending receipt.

    A candidate reaching this point has no durable receipt behind it — the
    main pass already removed every candidate matched to a pending row. That
    absence is the only case where a daemon-control header is excluded by its
    rendered shape rather than by structural provenance: a receipt-backed
    candidate (peer, caller-origin, or otherwise) never reaches this function
    at all, so shape matching here can only ever affect genuinely receipt-less
    text (via ``classify_transcript_text``).
    """
    binding_cutover = await db.get_turn_binding_cutover()
    if binding_cutover is None:
        return
    if not candidates:
        return
    if local_author is None:
        logger.warning(_TURN_BINDING_NO_LOCAL_AUTHOR_EVENT, session_id=session.session_id, inbound_row_id=None)
        return

    commitment_resolver = ClaudeTurnCommitmentResolver(entries) if agent_name is AgentName.CLAUDE else None

    for entry_id, entry_text, entry_timestamp in candidates:
        entry_dt = parse_iso_datetime(entry_timestamp)
        if entry_dt is None or entry_dt < binding_cutover:
            continue
        if any(
            TranscriptEntryKind(row["text_kind"]) is envelope.kind
            for row in pending_rows
            for envelope in scan_injected_envelopes(entry_text)
        ):
            continue
        if classify_transcript_text(entry_text).kind is not TranscriptEntryKind.ORDINARY:
            continue
        if commitment_resolver is not None:
            commitment = commitment_resolver.resolve(entry_id)
            observation_key = (session.session_id, session.native_session_id, entry_id)
            if observation_key not in _observed_claude_candidates:
                _observed_claude_candidates.add(observation_key)
                logger.info(
                    _CLAUDE_CANDIDATE_OBSERVED_EVENT,
                    session_id=session.session_id,
                    native_session_id=session.native_session_id,
                    parent_entry_id=commitment.parent_entry_id,
                    native_entry_id=entry_id,
                    alternative_entry_ids=list(commitment.alternative_entry_ids),
                    same_parent_candidate_count=len(commitment.alternative_entry_ids) + 1,
                )
            commitment_state = (commitment.outcome.value, commitment.reason.value)
            if _last_claude_commitments.get(observation_key) != commitment_state:
                _last_claude_commitments[observation_key] = commitment_state
                logger.info(
                    _CLAUDE_COMMITMENT_EVENT,
                    outcome=commitment.outcome.value,
                    reason=commitment.reason.value,
                    session_id=session.session_id,
                    native_session_id=session.native_session_id,
                    parent_entry_id=commitment.parent_entry_id,
                    native_entry_id=entry_id,
                    alternative_entry_ids=list(commitment.alternative_entry_ids),
                    same_parent_candidate_count=len(commitment.alternative_entry_ids) + 1,
                )
            if commitment.outcome is not ClaudeTurnCommitmentOutcome.COMMITTED:
                continue
        binding_id = f"{session.session_id}{_BINDING_ID_SEPARATOR}{entry_id}"
        generation_id = f"{_GENERATION_ID_PREFIX}{binding_id}"
        created = await db.create_turn_binding(
            binding_id=binding_id,
            session_id=session.session_id,
            native_reference=NativeReference(
                runtime=agent_name.value,
                native_session_id=session.native_session_id,
                entry_id=entry_id,
            ),
            parts=[
                TurnAuthoredPartInput(
                    part_kind=TurnPartKind.LOCAL,
                    span_start=0,
                    span_end=len(entry_text),
                    original_source_session_id=session.session_id,
                    author=local_author,
                )
            ],
            receipt_envelopes=[],
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
        logger.info(
            _NATIVE_ENTRY_CLASSIFICATION_EVENT,
            outcome=_BOUND_OUTCOME,
            session_id=session.session_id,
            native_runtime=agent_name.value,
            native_session_id=session.native_session_id,
            native_entry_id=entry_id,
            binding_id=binding_id,
            text_kinds=[TranscriptEntryKind.ORDINARY.value],
            envelope_count=0,
        )
        logger.info(
            _CONVERSATION_TEXT_EXTRACTION_EVENT,
            outcome=_BOUND_OUTCOME,
            session_id=session.session_id,
            native_runtime=agent_name.value,
            native_session_id=session.native_session_id,
            native_entry_id=entry_id,
            binding_id=binding_id,
            authored_part_count=1,
        )


async def bind_pending_native_turns(session: Session) -> None:  # noqa: C901
    """Bind delivered-but-unbound accepted rows to their native transcript turns.

    Closed envelope delimiters are scanned once per entry, then correlated to
    delivered receipts in acceptance order. The body's rendered value is never
    consulted. Every correlated envelope contributes an association and only
    its body can become an injected authored part; uncorrelated lookalikes stay
    local-human text.

    Receipt-correlated entries retain exact injected spans. Genuine terminal
    entries bind directly with a receipt-less local part after the durable
    binding cutover, so every composed native turn cuts one generation.

    Daemon-control and runtime-artifact text are excluded by the canonical classifier
    only in the receipt-less fallback (``_bind_local_terminal_candidates``),
    after this pass has already tried to correlate every candidate against a
    durable receipt. A candidate carrying a receipt — peer or caller-origin,
    even one whose rendered text happens to start with a control-header
    string — is never excluded by shape; only text with no receipt behind it
    is ever shape-tested, because none exists for that case to consult.
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
        timestamp = entry.get("timestamp")
        entry_id = _native_entry_id(entry, agent_name, timestamp=timestamp, text=text)
        if entry_id in already_bound or entry_id in conflicted_entry_ids:
            continue
        candidates.append((entry_id, text, timestamp))

    local_author = _resolve_local_human_author(session)

    remaining_pending_rows = list(pending_rows)
    for entry_id, entry_text, _entry_timestamp in list(candidates):
        envelopes = scan_injected_envelopes(entry_text)
        if not envelopes:
            continue
        candidate_rows = await _receipt_rows_covering_envelopes(remaining_pending_rows, len(envelopes))
        if candidate_rows is None:
            continue
        matched = await _match_receipts_in_acceptance_order(rows=candidate_rows, envelopes=envelopes)
        if matched is None:
            await _record_binding_conflict(
                rows=candidate_rows,
                session=session,
                agent_name=agent_name,
                entry_id=entry_id,
            )
            conflicting_ids = {row["id"] for row in candidate_rows}
            remaining_pending_rows = [row for row in remaining_pending_rows if row["id"] not in conflicting_ids]
            candidates.remove((entry_id, entry_text, _entry_timestamp))
            continue
        matched_row_ids = {row["id"] for row, _envelope_index, _envelope in matched}
        remaining_pending_rows = [row for row in remaining_pending_rows if row["id"] not in matched_row_ids]

        correlated_spans = sorted(envelope.envelope_span for _row, _envelope_index, envelope in matched)
        has_local_gap = correlated_spans[0][0] > 0 or correlated_spans[-1][1] < len(entry_text)
        if has_local_gap and local_author is None:
            remaining_pending_rows.extend(candidate_rows)
            continue
        parts: list[TurnAuthoredPartInput] = []
        cursor = 0
        for span_start, span_end in correlated_spans:
            if cursor < span_start:
                assert local_author is not None
                parts.append(
                    TurnAuthoredPartInput(
                        part_kind=TurnPartKind.LOCAL,
                        span_start=cursor,
                        span_end=span_start,
                        original_source_session_id=session.session_id,
                        author=local_author,
                    )
                )
            cursor = span_end
        if cursor < len(entry_text):
            assert local_author is not None
            parts.append(
                TurnAuthoredPartInput(
                    part_kind=TurnPartKind.LOCAL,
                    span_start=cursor,
                    span_end=len(entry_text),
                    original_source_session_id=session.session_id,
                    author=local_author,
                )
            )
        matched_by_row: dict[int, list[tuple[int, InjectedEnvelopeCandidate]]] = {}
        for row, envelope_index, envelope in matched:
            matched_by_row.setdefault(row["id"], []).append((envelope_index, envelope))
        for row in candidate_rows:
            row_envelopes = matched_by_row[row["id"]]
            text_kind = TranscriptEntryKind(row["text_kind"])
            if text_kind is TranscriptEntryKind.PLATFORM_CONTROL:
                continue
            bundle_parts = await _bundle_backed_parts(row=row, envelope_start=row_envelopes[0][1].envelope_span[0])
            if bundle_parts:
                parts.extend(bundle_parts)
                continue
            caller_author = _caller_author_from_row(row)
            ui_author = _ui_author_from_row(row)
            reminder_author = (
                MessageAuthor.for_machine(session_id=session.session_id, role_label=_REMINDER_ROLE_LABEL)
                if text_kind is TranscriptEntryKind.REMINDER
                else None
            )
            injected_author = reminder_author or caller_author or ui_author or local_author
            if injected_author is None:
                continue
            is_ui_origin = reminder_author is None and caller_author is None and ui_author is not None
            for _envelope_index, envelope in row_envelopes:
                parts.append(
                    TurnAuthoredPartInput(
                        part_kind=TurnPartKind.INJECTED_REMINDER if reminder_author else TurnPartKind.INJECTED_PEER,
                        span_start=envelope.body_span[0],
                        span_end=envelope.body_span[1],
                        original_source_session_id=None
                        if is_ui_origin
                        else row["caller_session_id"] or session.session_id,
                        author=injected_author,
                        author_job_role=row["caller_job_role"],
                        origin_surface=row["origin"] if is_ui_origin else None,
                    )
                )
        parts.sort(key=lambda part: part.span_start)
        receipt_envelopes = [
            TurnReceiptEnvelopeInput(
                inbound_queue_id=row["id"],
                envelope_index=envelope_index,
                occurrence_key=row["occurrence_key"],
                text_kind=TranscriptEntryKind(row["text_kind"]),
                envelope_span=envelope.envelope_span,
                body_span=envelope.body_span,
                authored_part_id=next(
                    (
                        index
                        for index, part in enumerate(parts)
                        if part.span_start == envelope.body_span[0] and part.span_end == envelope.body_span[1]
                    ),
                    None,
                ),
            )
            for row, envelope_index, envelope in matched
        ]
        binding_id = f"{session.session_id}{_BINDING_ID_SEPARATOR}{entry_id}"
        created = await db.create_turn_binding(
            binding_id=binding_id,
            session_id=session.session_id,
            native_reference=NativeReference(
                runtime=agent_name.value,
                native_session_id=session.native_session_id,
                entry_id=entry_id,
            ),
            parts=parts,
            receipt_envelopes=receipt_envelopes,
            generation_id=f"{_GENERATION_ID_PREFIX}{binding_id}",
        )
        if not created:
            remaining_pending_rows.extend(candidate_rows)
            continue
        candidates.remove((entry_id, entry_text, _entry_timestamp))
        logger.debug(
            _TURN_BINDING_CREATED_EVENT,
            session_id=session.session_id,
            binding_id=binding_id,
            generation_id=f"{_GENERATION_ID_PREFIX}{binding_id}",
            part_count=len(parts),
        )
        logger.info(
            _NATIVE_ENTRY_CLASSIFICATION_EVENT,
            outcome=_BOUND_OUTCOME,
            session_id=session.session_id,
            native_runtime=agent_name.value,
            native_session_id=session.native_session_id,
            native_entry_id=entry_id,
            binding_id=binding_id,
            text_kinds=sorted({row["text_kind"] for row, _envelope_index, _envelope in matched}),
            envelope_count=len(matched),
        )
        logger.info(
            _CONVERSATION_TEXT_EXTRACTION_EVENT,
            outcome=_BOUND_OUTCOME,
            session_id=session.session_id,
            native_runtime=agent_name.value,
            native_session_id=session.native_session_id,
            native_entry_id=entry_id,
            binding_id=binding_id,
            authored_part_count=len(parts),
        )
        for row, _envelope_index, envelope in matched:
            logger.info(
                "native_injected_envelope_correlated",
                correlation_method="receipt_occurrence",
                session_id=session.session_id,
                native_runtime=agent_name.value,
                native_session_id=session.native_session_id,
                native_entry_id=entry_id,
                binding_id=binding_id,
                inbound_queue_id=row["id"],
                occurrence_key=row["occurrence_key"],
                source_feature=row["source_feature"],
                text_kind=row["text_kind"],
                envelope_span_start=envelope.envelope_span[0],
                envelope_span_end=envelope.envelope_span[1],
                body_span_start=envelope.body_span[0],
                body_span_end=envelope.body_span[1],
            )

    await _bind_local_terminal_candidates(
        session=session,
        agent_name=agent_name,
        entries=entries,
        candidates=candidates,
        pending_rows=remaining_pending_rows,
        local_author=local_author,
    )
