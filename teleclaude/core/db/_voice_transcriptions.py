"""Mixin: DbVoiceTranscriptionsMixin."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, update
from sqlmodel import select

from teleclaude.constants import (
    VOICE_TRANSCRIPTION_RECOVERABLE_STATES,
    VOICE_TRANSCRIPTION_STATE_FAILED,
    VOICE_TRANSCRIPTION_STATE_IN_PROGRESS,
    VOICE_TRANSCRIPTION_STATE_INTERRUPTED,
    VOICE_TRANSCRIPTION_STATE_PENDING,
    VOICE_TRANSCRIPTION_STATE_SUCCEEDED,
    VOICE_TRANSCRIPTION_TERMINAL_STATES,
)

from .. import db_models

if TYPE_CHECKING:
    pass

VOICE_TRANSCRIPTION_STATES = frozenset(
    {
        VOICE_TRANSCRIPTION_STATE_PENDING,
        VOICE_TRANSCRIPTION_STATE_IN_PROGRESS,
        VOICE_TRANSCRIPTION_STATE_SUCCEEDED,
        VOICE_TRANSCRIPTION_STATE_FAILED,
        VOICE_TRANSCRIPTION_STATE_INTERRUPTED,
    }
)


def _voice_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class DbVoiceTranscriptionsMixin:
    """Durable voice transcription recovery persistence helpers."""

    @staticmethod
    def _validate_voice_transcription_state(state: str) -> None:
        if state not in VOICE_TRANSCRIPTION_STATES:
            raise ValueError(f"Invalid voice transcription state: {state}")

    async def create_voice_transcription(
        self,
        *,
        session_id: str,
        audio_path: str,
        origin: str,
        notice_message_id: str | None = None,
        thread_id: str | None = None,
        actor_id: str | None = None,
        actor_name: str | None = None,
        actor_avatar_url: str | None = None,
        duration: float | None = None,
        language: str | None = None,
    ) -> db_models.VoiceTranscription:
        """Insert a durable voice transcription row in pending state."""
        now = _voice_now_iso()
        row = db_models.VoiceTranscription(
            session_id=session_id,
            audio_path=audio_path,
            origin=origin,
            notice_message_id=notice_message_id,
            thread_id=thread_id,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_avatar_url=actor_avatar_url,
            duration=duration,
            language=language,
            state=VOICE_TRANSCRIPTION_STATE_PENDING,
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        async with self._session() as db_session:
            db_session.add(row)
            await db_session.commit()
            await db_session.refresh(row)
            if row.id is None:
                raise RuntimeError("Failed to insert voice_transcriptions row")
            return row

    async def get_voice_transcription(self, transcription_id: int) -> db_models.VoiceTranscription | None:
        """Fetch a durable voice transcription row by id."""
        async with self._session() as db_session:
            return await db_session.get(db_models.VoiceTranscription, transcription_id)

    async def set_voice_transcription_notice_message_id(
        self,
        transcription_id: int,
        notice_message_id: str | None,
    ) -> bool:
        """Persist the platform message id for the editable transcription notice."""
        stmt = (
            update(db_models.VoiceTranscription)
            .where(db_models.VoiceTranscription.id == transcription_id)
            .values(notice_message_id=notice_message_id, updated_at=_voice_now_iso())
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) == 1

    async def update_voice_transcription_state(
        self,
        transcription_id: int,
        state: str,
        *,
        last_error: str | None = None,
    ) -> bool:
        """Transition a durable voice transcription row to a new state."""
        self._validate_voice_transcription_state(state)
        stmt = (
            update(db_models.VoiceTranscription)
            .where(db_models.VoiceTranscription.id == transcription_id)
            .values(state=state, last_error=last_error, updated_at=_voice_now_iso())
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) == 1

    async def increment_voice_transcription_attempts(self, transcription_id: int) -> bool:
        """Increment recovery attempts for a durable voice transcription row."""
        stmt = (
            update(db_models.VoiceTranscription)
            .where(db_models.VoiceTranscription.id == transcription_id)
            .values(
                attempts=db_models.VoiceTranscription.attempts + 1,
                updated_at=_voice_now_iso(),
            )
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return (result.rowcount or 0) == 1

    async def list_recoverable_voice_transcriptions(self) -> list[db_models.VoiceTranscription]:
        """List voice transcription rows that need restart recovery."""
        stmt = (
            select(db_models.VoiceTranscription)
            .where(db_models.VoiceTranscription.state.in_(VOICE_TRANSCRIPTION_RECOVERABLE_STATES))
            .order_by(db_models.VoiceTranscription.id.asc())  # type: ignore[arg-type]
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return list(result.all())

    async def list_live_voice_transcription_audio_paths(self) -> set[str]:
        """Return audio paths still referenced by non-terminal voice transcription rows."""
        stmt = (
            select(db_models.VoiceTranscription.audio_path)
            .where(db_models.VoiceTranscription.state.in_(VOICE_TRANSCRIPTION_RECOVERABLE_STATES))
            .where(db_models.VoiceTranscription.audio_path.is_not(None))
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return {str(path) for path in result.all() if path}

    async def cleanup_terminal_voice_transcriptions(self, older_than_iso: str) -> int:
        """Delete terminal voice transcription rows older than runtime retention."""
        stmt = (
            delete(db_models.VoiceTranscription)
            .where(db_models.VoiceTranscription.state.in_(VOICE_TRANSCRIPTION_TERMINAL_STATES))
            .where(db_models.VoiceTranscription.updated_at < older_than_iso)
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            return result.rowcount or 0
