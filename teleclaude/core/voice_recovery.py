"""Startup recovery for durable voice transcriptions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import (
    VOICE_TRANSCRIPTION_RECOVERY_MAX_ATTEMPTS,
    VOICE_TRANSCRIPTION_STATE_FAILED,
)
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata
from teleclaude.types.commands import HandleVoiceCommand

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.command_service import CommandService
    from teleclaude.core.db_models import VoiceTranscription

logger = get_logger(__name__)


async def _edit_or_send_recovery_notice(
    *,
    client: AdapterClient,
    row: VoiceTranscription,
    message: str,
) -> None:
    session = await db.get_session(row.session_id)
    if session is None:
        logger.warning("Voice recovery skipped notice for missing session %s", row.session_id)
        return
    if row.origin:
        await db.update_session(row.session_id, last_input_origin=row.origin)
        refreshed = await db.get_session(row.session_id)
        session = refreshed or session
    if row.notice_message_id:
        await client.edit_message(session, row.notice_message_id, message)
        return
    await client.send_message(session, message, metadata=MessageMetadata(parse_mode=None))


async def _fail_voice_recovery(
    *,
    client: AdapterClient,
    row: VoiceTranscription,
    reason: str,
    message: str,
) -> None:
    if row.id is None:
        return
    await db.update_voice_transcription_state(row.id, VOICE_TRANSCRIPTION_STATE_FAILED, last_error=reason)
    await _edit_or_send_recovery_notice(client=client, row=row, message=message)


def _thread_id_as_int(row: VoiceTranscription) -> int | None:
    if row.thread_id is None:
        return None
    return int(row.thread_id)


async def _recover_voice_transcription_row(
    *,
    client: AdapterClient,
    command_service: CommandService,
    row: VoiceTranscription,
) -> bool:
    if row.id is None:
        return False
    await db.increment_voice_transcription_attempts(row.id)
    refreshed = await db.get_voice_transcription(row.id)
    if refreshed is None:
        return False
    if refreshed.attempts > VOICE_TRANSCRIPTION_RECOVERY_MAX_ATTEMPTS:
        await _fail_voice_recovery(
            client=client,
            row=refreshed,
            reason="voice transcription recovery retry cap exceeded",
            message="❌ Transcription failed after repeated restart recovery attempts. Please re-record.",
        )
        return True
    if not Path(refreshed.audio_path).is_file():
        await _fail_voice_recovery(
            client=client,
            row=refreshed,
            reason="voice transcription audio missing during recovery",
            message="❌ Audio file lost during restart. Please re-record.",
        )
        return True
    await command_service.handle_voice(
        HandleVoiceCommand(
            session_id=refreshed.session_id,
            file_path=refreshed.audio_path,
            duration=refreshed.duration,
            message_thread_id=_thread_id_as_int(refreshed),
            origin=refreshed.origin,
            actor_id=refreshed.actor_id,
            actor_name=refreshed.actor_name,
            actor_avatar_url=refreshed.actor_avatar_url,
            voice_transcription_id=refreshed.id,
            notice_message_id=refreshed.notice_message_id,
        )
    )
    return True


async def recover_voice_transcriptions(*, client: AdapterClient, command_service: CommandService) -> int:
    """Recover pending or interrupted voice transcriptions after daemon startup."""
    rows = await db.list_recoverable_voice_transcriptions()
    processed = 0
    for row in rows:
        try:
            if await _recover_voice_transcription_row(client=client, command_service=command_service, row=row):
                processed += 1
        except Exception as exc:
            logger.exception("Voice transcription recovery failed for row %s: %s", row.id, exc)
            continue
    if processed:
        logger.info("Processed %d voice transcription recovery row(s)", processed)
    return processed
