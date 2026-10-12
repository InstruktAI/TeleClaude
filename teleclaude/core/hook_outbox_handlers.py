"""Daemon-side handlers for outbox events that mutate session state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

from teleclaude.core.models import Session
from teleclaude.core.session_transcript_chain import native_log_binding_updates

if TYPE_CHECKING:

    class SessionMutationDb(Protocol):
        """Protocol for the DB methods used by outbox session-mutation handlers."""

        async def get_session(self, session_id: str) -> Session | None:
            """Return the current session row for a TeleClaude session id."""

        async def update_session(self, session_id: str, **fields: object) -> Session | None:
            """Persist field updates for a TeleClaude session id."""


def optional_payload_str_value(data: Mapping[str, object], key: str) -> str | None:
    """Return a non-empty string value from a loose outbox payload."""
    value = data.get(key)
    return value if isinstance(value, str) and value else None


async def handle_checkpoint_seen(
    db_handle: SessionMutationDb,
    *,
    session_id: str,
    payload: Mapping[str, object],
) -> None:
    """Apply a checkpoint_seen outbox event to session state."""
    checkpoint_at = optional_payload_str_value(payload, "checkpoint_at")
    if checkpoint_at:
        await db_handle.update_session(session_id, last_checkpoint_at=checkpoint_at)


async def handle_native_metadata_update(
    db_handle: SessionMutationDb,
    *,
    session_id: str,
    payload: Mapping[str, object],
) -> None:
    """Apply native metadata updates while preserving transcript history."""
    session = await db_handle.get_session(session_id)
    if session is None:
        return

    updates: dict[str, object] = {}  # guard: loose-dict - Session update payload is field-addressed at runtime.
    native_session_id = optional_payload_str_value(payload, "native_session_id")
    if native_session_id and session.native_session_id != native_session_id:
        updates["native_session_id"] = native_session_id

    updates.update(
        native_log_binding_updates(
            current_log_file=session.native_log_file,
            current_chain=session.transcript_files,
            new_log_file=optional_payload_str_value(payload, "native_log_file"),
        )
    )

    if updates:
        await db_handle.update_session(session_id, **updates)


async def handle_native_session_refresh(
    db_handle: SessionMutationDb,
    *,
    session_id: str,
    payload: Mapping[str, object],
) -> None:
    """Apply a native_session_refresh outbox event to session state."""
    if "native_session_id" not in payload:
        return

    raw_native_session_id = payload.get("native_session_id")
    if raw_native_session_id is None:
        await db_handle.update_session(session_id, native_session_id=None)
        return

    if isinstance(raw_native_session_id, str) and raw_native_session_id:
        await db_handle.update_session(session_id, native_session_id=raw_native_session_id)
