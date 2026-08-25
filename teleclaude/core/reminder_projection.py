"""Merge typed reminder entries into the existing per-session projection pass."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.core.db import db
from teleclaude.core.reminders.models import ReminderEntry, ReminderEntryReadFailure, ReminderEntryReadItem
from teleclaude.core.reminders.observability import observe_projection_failure
from teleclaude.core.reminders.ordering import (
    ProjectionOrderKey,
    ProjectionSourceKind,
    projection_order_key,
    projection_source_key,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)
_PROJECTION_BATCH_EVENT = "session_projection_batch_committed"
_TERMINAL_FAILURE_OCCURRENCE = datetime.max.replace(tzinfo=UTC)


@dataclass(frozen=True)
class NativeProjectionCandidate:
    """One already-rendered native output candidate for source-order merging."""

    occurred_at: datetime
    stable_id: str
    deliver: Callable[[], Awaitable[None]]


async def project_session_sources(
    session: Session,
    adapter_client: AdapterClient,
    *,
    native_candidate: NativeProjectionCandidate | None,
) -> None:
    """Deliver native and reminder candidates in one deterministic source order."""
    projection_pass_id = str(uuid4())
    after_entry_id = await adapter_client.reminder_projection_after_entry_id(session)
    reminders: list[ReminderEntryReadItem] = []
    if after_entry_id is not None:
        try:
            reminders = await db.list_reminder_entries(session_id=session.session_id, after_entry_id=after_entry_id)
        except Exception as exc:
            observe_projection_failure(
                session_id=session.session_id,
                projection_pass_id=projection_pass_id,
                stage="read",
                error_type=type(exc).__name__,
            )
    candidates: list[
        tuple[
            ProjectionOrderKey,
            ProjectionSourceKind,
            str | int,
            ReminderEntry | ReminderEntryReadFailure | NativeProjectionCandidate,
        ]
    ] = [
        (
            projection_order_key(
                occurred_at=entry.occurred_at or _TERMINAL_FAILURE_OCCURRENCE,
                source_kind=ProjectionSourceKind.REMINDER,
                stable_id=entry.entry_id,
            ),
            ProjectionSourceKind.REMINDER,
            entry.entry_id,
            entry,
        )
        for entry in reminders
    ]
    if native_candidate is not None:
        candidates.append(
            (
                projection_order_key(
                    occurred_at=native_candidate.occurred_at,
                    source_kind=ProjectionSourceKind.NATIVE,
                    stable_id=native_candidate.stable_id,
                ),
                ProjectionSourceKind.NATIVE,
                native_candidate.stable_id,
                native_candidate,
            )
        )

    reminder_blocked = False
    permanent_skip_count = 0
    for _order_key, _source_kind, _stable_id, candidate in sorted(candidates, key=lambda item: item[0]):
        if isinstance(candidate, NativeProjectionCandidate):
            await candidate.deliver()
        elif not reminder_blocked:
            try:
                if isinstance(candidate, ReminderEntryReadFailure):
                    await adapter_client.skip_reminder_entry_read_failure(
                        session,
                        candidate,
                        projection_pass_id=projection_pass_id,
                    )
                    permanent_skip_count += 1
                elif not await adapter_client.send_reminder_entry(
                    session,
                    candidate,
                    projection_pass_id=projection_pass_id,
                ):
                    reminder_blocked = True
            except Exception as exc:
                observe_projection_failure(
                    session_id=session.session_id,
                    projection_pass_id=projection_pass_id,
                    stage="settlement",
                    reminder_entry_id=candidate.entry_id,
                    error_type=type(exc).__name__,
                )
                reminder_blocked = True

    # The batch record exists to witness reminder ordering; a pass carrying
    # only the routine native candidate is not a reminder batch and stays
    # silent — logging it every poll drowned the log in no-op noise.
    if reminders:
        logger.info(
            _PROJECTION_BATCH_EVENT,
            outcome="blocked" if reminder_blocked else "committed",
            session_id=session.session_id,
            projection_pass_id=projection_pass_id,
            permanent_skip_count=permanent_skip_count,
            ordered_source_keys=[
                projection_source_key(source_kind=source_kind, stable_id=stable_id)
                for _order_key, source_kind, stable_id, _candidate in sorted(candidates, key=lambda item: item[0])
            ],
        )
