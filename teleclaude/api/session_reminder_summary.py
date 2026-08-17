"""Session-list reminder summary composition."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.api_models import SessionDTO

if TYPE_CHECKING:
    from teleclaude.core.reminders import ReminderService

logger = get_logger(__name__)


async def attach_next_reminders(
    dtos: list[SessionDTO],
    local_session_ids: set[str],
    service: ReminderService | None,
) -> list[SessionDTO]:
    """Attach each local session's earliest concrete reminder summary."""
    if service is None:
        return dtos
    local_dtos = [dto for dto in dtos if dto.session_id in local_session_ids]
    reminders = await asyncio.gather(*(service.next_scheduled(session_id=dto.session_id) for dto in local_dtos))
    by_session = {dto.session_id: reminder for dto, reminder in zip(local_dtos, reminders, strict=True)}
    return [
        dto.model_copy(
            update={
                "next_reminder_slug": by_session[dto.session_id].slug,
                "next_reminder_at": (
                    by_session[dto.session_id].schedule.next_fire_at.isoformat()
                    if by_session[dto.session_id].schedule.next_fire_at is not None
                    else None
                ),
            }
        )
        if dto.session_id in by_session and by_session[dto.session_id] is not None
        else dto
        for dto in dtos
    ]


def observe_session_reminder_summaries(dtos: list[SessionDTO]) -> None:
    """Record body-free concrete reminder summaries from a completed listing."""
    logger.info(
        "session_listing_completed",
        outcome="success",
        reminder_summaries=[
            {
                "owner_session_id": dto.session_id,
                "next_reminder_slug": dto.next_reminder_slug,
                "next_reminder_at": dto.next_reminder_at,
            }
            for dto in dtos
            if dto.next_reminder_slug is not None
        ],
    )
