"""Voice focus: which session a person's voice utterances latch to and replies play from.

The record is a durable override, not a cache of activity. Derived focus
tracks the person's most recently accepted input across the cluster;
explicit focus (set through `SetVoiceFocusCommand`, e.g. the "Listen here"
control) wins until a newer accepted input supersedes it. `resolve` is the
single query every consumer calls to latch an utterance or pick a reply
target — it never follows agent output, only accepted human input.

Records carry `focus_id` only in every emitted observation — never a person
slug, email, or platform id; those stay inside this module and the identity
owner it queries.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from instrukt_ai_logging import get_logger

from teleclaude.core.dates import ensure_utc, parse_iso_datetime
from teleclaude.core.db import db
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.models import SessionSnapshot

logger = get_logger(__name__)

_VOICE_FOCUS_DERIVED_EVENT = "voice_focus_derived"
_VOICE_FOCUS_SET_EVENT = "voice_focus_set"
_VOICE_FOCUS_RESOLVED_EVENT = "voice_focus_resolved"


class VoiceFocusBasis(StrEnum):
    """Closed vocabulary for how a voice-focus record was last set."""

    DERIVED = "derived"
    EXPLICIT = "explicit"


@dataclass(frozen=True)
class VoiceFocusRecord:
    """One person's durable voice focus. Never logged with its person_slug."""

    focus_id: str
    focused_session_id: str | None
    basis: VoiceFocusBasis
    set_at: datetime


def _latest_accepted_input(
    person_slug: str, cluster_sessions: Iterable[SessionSnapshot]
) -> tuple[str, datetime] | None:
    """Return (session_id, last_input_at) for this person's most recently active session."""
    resolver = get_identity_resolver()
    best: tuple[str, datetime] | None = None
    for session in cluster_sessions:
        if not session.human_email or not session.last_input_at:
            continue
        identity = resolver.resolve_by_email(session.human_email)
        if identity.person_slug != person_slug:
            continue
        last_input_at = parse_iso_datetime(session.last_input_at)
        if last_input_at is None:
            continue
        if best is None or last_input_at > best[1]:
            best = (session.session_id, last_input_at)
    return best


async def _load_record(person_slug: str) -> VoiceFocusRecord:
    """Return the person's durable record, creating one (derived, unfocused) if absent."""
    row = await db.get_voice_focus_row(person_slug)
    if row is not None:
        return VoiceFocusRecord(
            focus_id=row.focus_id,
            focused_session_id=row.focused_session_id,
            basis=VoiceFocusBasis(row.basis),
            set_at=ensure_utc(row.set_at) if row.set_at else datetime.now(UTC),
        )
    focus_id = str(uuid.uuid4())
    set_at = datetime.now(UTC)
    await db.upsert_voice_focus_row(
        person_slug,
        focus_id=focus_id,
        focused_session_id=None,
        basis=VoiceFocusBasis.DERIVED.value,
        set_at=set_at,
    )
    return VoiceFocusRecord(focus_id=focus_id, focused_session_id=None, basis=VoiceFocusBasis.DERIVED, set_at=set_at)


async def derive(person_slug: str, cluster_sessions: Iterable[SessionSnapshot]) -> str | None:
    """Derive focus from the person's most recently accepted input, across the cluster.

    Persists and emits `voice_focus_derived` only when the derived target
    changes; always returns the currently focused session id (or None).
    """
    record = await _load_record(person_slug)
    latest = _latest_accepted_input(person_slug, cluster_sessions)
    if latest is None:
        return record.focused_session_id
    focused_session_id, accepted_at = latest
    if record.focused_session_id != focused_session_id or record.basis is not VoiceFocusBasis.DERIVED:
        await db.upsert_voice_focus_row(
            person_slug,
            focus_id=record.focus_id,
            focused_session_id=focused_session_id,
            basis=VoiceFocusBasis.DERIVED.value,
            set_at=accepted_at,
        )
        logger.info(_VOICE_FOCUS_DERIVED_EVENT, focus_id=record.focus_id, focused_session_id=focused_session_id)
    return focused_session_id


async def set_explicit(person_slug: str, session_id: str) -> VoiceFocusRecord:
    """Durably override focus to `session_id` until a newer accepted input supersedes it."""
    record = await _load_record(person_slug)
    set_at = datetime.now(UTC)
    await db.upsert_voice_focus_row(
        person_slug,
        focus_id=record.focus_id,
        focused_session_id=session_id,
        basis=VoiceFocusBasis.EXPLICIT.value,
        set_at=set_at,
    )
    logger.info(_VOICE_FOCUS_SET_EVENT, focus_id=record.focus_id, focused_session_id=session_id, basis="explicit")
    return VoiceFocusRecord(
        focus_id=record.focus_id, focused_session_id=session_id, basis=VoiceFocusBasis.EXPLICIT, set_at=set_at
    )


async def accept_input(person_slug: str, session_id: str, accepted_at: str) -> VoiceFocusRecord | None:
    """Record a newer accepted-input transition, returning ``None`` for stale delivery."""
    record = await _load_record(person_slug)
    set_at = parse_iso_datetime(accepted_at) or datetime.now(UTC)
    if record.focused_session_id is not None and set_at <= record.set_at:
        return None
    await db.upsert_voice_focus_row(
        person_slug,
        focus_id=record.focus_id,
        focused_session_id=session_id,
        basis=VoiceFocusBasis.DERIVED.value,
        set_at=set_at,
    )
    logger.info(_VOICE_FOCUS_DERIVED_EVENT, focus_id=record.focus_id, focused_session_id=session_id)
    return VoiceFocusRecord(
        focus_id=record.focus_id,
        focused_session_id=session_id,
        basis=VoiceFocusBasis.DERIVED,
        set_at=set_at,
    )


async def resolve(person_slug: str, cluster_sessions: Iterable[SessionSnapshot]) -> VoiceFocusRecord:
    """Resolve the currently focused session: explicit wins unless a newer accepted input supersedes it.

    Emits `voice_focus_resolved` on every call — the record the non-human-focus
    invariant anchors on. Never follows agent output, only accepted input.
    """
    record = await _load_record(person_slug)
    latest = _latest_accepted_input(person_slug, cluster_sessions)

    record_is_current = record.focused_session_id is not None and (latest is None or latest[1] <= record.set_at)
    if record_is_current:
        resolved = record
    elif latest is not None:
        focused_session_id, accepted_at = latest
        if record.focused_session_id != focused_session_id or record.basis is not VoiceFocusBasis.DERIVED:
            await db.upsert_voice_focus_row(
                person_slug,
                focus_id=record.focus_id,
                focused_session_id=focused_session_id,
                basis=VoiceFocusBasis.DERIVED.value,
                set_at=accepted_at,
            )
            logger.info(_VOICE_FOCUS_DERIVED_EVENT, focus_id=record.focus_id, focused_session_id=focused_session_id)
        resolved = VoiceFocusRecord(
            focus_id=record.focus_id,
            focused_session_id=focused_session_id,
            basis=VoiceFocusBasis.DERIVED,
            set_at=accepted_at,
        )
    else:
        resolved = record

    logger.info(
        _VOICE_FOCUS_RESOLVED_EVENT,
        focus_id=resolved.focus_id,
        focused_session_id=resolved.focused_session_id,
        basis=resolved.basis.value,
    )
    return resolved
