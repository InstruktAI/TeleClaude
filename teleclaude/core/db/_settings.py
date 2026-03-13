"""Mixin: DbSettingsMixin."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from .. import db_models
from ..voice_assignment import VoiceConfig

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class DbSettingsMixin:
    async def get_system_setting(self, key: str) -> str | None:
        """Get system setting value by key.

        Args:
            key: Setting key

        Returns:
            Setting value or None if not found
        """
        async with self._session() as db_session:
            row = await db_session.get(db_models.SystemSetting, key)
            return row.value if row else None

    async def set_system_setting(self, key: str, value: str) -> None:
        """Set system setting value (upsert).

        Args:
            key: Setting key
            value: Setting value
        """
        async with self._session() as db_session:
            row = await db_session.get(db_models.SystemSetting, key)
            if row is None:
                row = db_models.SystemSetting(key=key, value=value)
            else:
                row.value = value
            db_session.add(row)
            await db_session.commit()

    # Voice assignment methods

    async def assign_voice(self, voice_id: str, voice: VoiceConfig) -> None:
        """Assign a voice keyed by ID (either teleclaude_session_id or native_session_id).

        Args:
            voice_id: Either teleclaude session ID or Agent session ID
            voice: VoiceConfig to assign
        """
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        now = datetime.now(UTC)
        stmt = sqlite_insert(db_models.VoiceAssignment).values(
            id=voice_id,
            service_name=voice.service_name,
            voice=voice.voice,
            assigned_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "service_name": stmt.excluded.service_name,
                "voice": stmt.excluded.voice,
                "assigned_at": now,
            },
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()
        logger.debug("Assigned voice '%s' from service '%s' to %s", voice.voice, voice.service_name, voice_id)

    async def get_voice(self, voice_id: str) -> VoiceConfig | None:
        """Get voice assignment by ID.

        Args:
            voice_id: Either teleclaude session ID or Agent session ID

        Returns:
            VoiceConfig or None if no voice assigned
        """
        async with self._session() as db_session:
            row = await db_session.get(db_models.VoiceAssignment, voice_id)
            if not row:
                return None
            return VoiceConfig(
                service_name=row.service_name or "",
                voice=row.voice or "",
            )

    async def get_voices_in_use(self) -> set[tuple[str, str]]:
        """Get all (service_name, voice) pairs assigned to non-closed sessions.

        Returns:
            Set of (service_name, voice) tuples currently in use.
        """
        from sqlalchemy import or_
        from sqlmodel import select

        stmt = (
            select(db_models.VoiceAssignment.service_name, db_models.VoiceAssignment.voice)
            .join(db_models.Session, db_models.VoiceAssignment.id == db_models.Session.session_id)
            .where(
                db_models.Session.closed_at.is_(None),
                or_(
                    db_models.Session.lifecycle_status.is_(None),
                    db_models.Session.lifecycle_status != "closed",
                ),
                db_models.VoiceAssignment.service_name.is_not(None),
            )
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return {(row[0], row[1] or "") for row in result.all()}

    async def cleanup_stale_voice_assignments(self, max_age_days: int = 7) -> int:
        """Delete voice assignments older than max_age_days.

        Args:
            max_age_days: Maximum age in days before cleanup (default: 7)

        Returns:
            Number of records deleted
        """

        from sqlalchemy import delete

        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        stmt = delete(db_models.VoiceAssignment).where(db_models.VoiceAssignment.assigned_at < cutoff)
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            await db_session.commit()
            deleted = result.rowcount or 0
        if deleted > 0:
            logger.info(
                "Cleaned up %d stale voice assignments (older than %d days)",
                deleted,
                max_age_days,
            )
        return deleted

    # Agent availability methods (for next-machine workflow)
