"""Persistence for accepted inbound message metadata."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from teleclaude.core.db import db
from teleclaude.core.injected_text import visible_input_update
from teleclaude.core.models import SessionField
from teleclaude.core.session_listeners import record_startup_work_accepted


async def record_accepted_input_metadata(
    *,
    session_id: str,
    origin: str,
    message_text: str,
    origin_metadata: Mapping[str, object] | None,
    visible_source_text: str | None,
    caller_session_id: str | None,
) -> None:
    """Persist accepted-input state, retaining origin on control-only turns."""
    visible_updates = visible_input_update(message_text, visible_source_text=visible_source_text)
    if visible_updates:
        visible_updates[SessionField.LAST_INPUT_ORIGIN.value] = origin
    await db.update_session(
        session_id,
        last_message_sent=message_text[:200],
        last_message_sent_at=datetime.now(UTC).isoformat(),
        **visible_updates,
    )
    if origin_metadata:
        await db.update_origin_metadata(session_id, origin, dict(origin_metadata))
    await record_startup_work_accepted(session_id, caller_session_id)
