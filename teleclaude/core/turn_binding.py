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
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.db import InboundQueueRow, NativeReference, TurnAuthoredPartInput, db
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.models import JsonDict, MessageAuthor, MessageAuthorKind
from teleclaude.utils.transcript import (
    _get_entries_for_agent,
    extract_real_user_text_from_entry,
    is_real_user_turn_entry,
)

if TYPE_CHECKING:
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_TURN_BINDING_AMBIGUOUS_SPAN_EVENT = "turn_binding_ambiguous_injected_span"
_TURN_BINDING_CREATED_EVENT = "turn_binding_created"
_TURN_BINDING_NO_LOCAL_AUTHOR_EVENT = "turn_binding_no_local_author"


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


async def bind_pending_native_turns(session: Session) -> None:
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

    Scope: only rows with a durable accepted-row correlation (adapter input,
    peer bundles, session-to-session sends) are bound here. Pure local
    terminal typing with no accepted receipt is not bound by this pass.
    """
    if not session.native_log_file or not session.active_agent or not session.native_session_id:
        return
    try:
        agent_name = AgentName.from_str(session.active_agent)
    except ValueError:
        return

    pending_rows = await db.get_unbound_delivered_inbound(session_id=session.session_id)
    if not pending_rows:
        return

    entries = await asyncio.to_thread(_get_entries_for_agent, session.native_log_file, agent_name)
    if not entries:
        return

    already_bound = await db.get_bound_native_entry_ids(
        native_runtime=agent_name.value, native_session_id=session.native_session_id
    )
    candidates: list[tuple[str, str, object]] = []  # (entry_id, text, timestamp)
    for entry in entries:
        if not is_real_user_turn_entry(entry, agent_name):
            continue
        text = extract_real_user_text_from_entry(entry, agent_name)
        if text is None:
            continue
        timestamp = entry.get("timestamp")
        entry_id = _native_entry_id(entry, agent_name, timestamp=timestamp, text=text)
        if entry_id in already_bound:
            continue
        candidates.append((entry_id, text, timestamp))

    local_author = _resolve_local_human_author(session)

    for row in pending_rows:
        content = row["content"]
        matches = [c for c in candidates if content in c[1]]
        if not matches:
            continue  # not in the transcript yet — try again next poll
        if len(matches) > 1:
            logger.error(
                _TURN_BINDING_AMBIGUOUS_SPAN_EVENT,
                session_id=session.session_id,
                inbound_row_id=row["id"],
                candidate_count=len(matches),
            )
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
            logger.error(
                _TURN_BINDING_AMBIGUOUS_SPAN_EVENT,
                session_id=session.session_id,
                inbound_row_id=row["id"],
                candidate_count=occurrence_count,
            )
            continue
        span_start = entry_text.index(content)
        span_end = span_start + len(content)

        caller_author = _caller_author_from_row(row)
        injected_original_source = row["caller_session_id"] or session.session_id
        injected_author = caller_author or local_author
        if injected_author is None:
            logger.warning(_TURN_BINDING_NO_LOCAL_AUTHOR_EVENT, session_id=session.session_id, inbound_row_id=row["id"])
            continue

        parts: list[TurnAuthoredPartInput] = []
        if span_start > 0:
            if local_author is None:
                continue
            parts.append(
                TurnAuthoredPartInput(
                    part_kind="local",
                    span_start=0,
                    span_end=span_start,
                    original_source_session_id=session.session_id,
                    author=local_author,
                )
            )
        parts.append(
            TurnAuthoredPartInput(
                part_kind="injected_peer" if caller_author is not None else "local",
                span_start=span_start,
                span_end=span_end,
                original_source_session_id=injected_original_source,
                author=injected_author,
                author_job_role=row["caller_job_role"],
            )
        )
        if span_end < len(entry_text):
            if local_author is None:
                continue
            parts.append(
                TurnAuthoredPartInput(
                    part_kind="local",
                    span_start=span_end,
                    span_end=len(entry_text),
                    original_source_session_id=session.session_id,
                    author=local_author,
                )
            )

        binding_id = f"{session.session_id}:{entry_id}"
        generation_id = f"gen:{binding_id}"
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
        logger.debug(
            _TURN_BINDING_CREATED_EVENT,
            session_id=session.session_id,
            inbound_row_id=row["id"],
            binding_id=binding_id,
            generation_id=generation_id,
            part_count=len(parts),
            injected_original_source_session_id=injected_original_source,
        )
