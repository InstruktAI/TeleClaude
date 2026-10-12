"""Mixin: pending platform-message deletions."""

from enum import StrEnum

from instrukt_ai_logging import get_logger
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from .. import db_models

logger = get_logger(__name__)

_ADD_PENDING_DELETION_FAILED_EVENT = "pending_deletion.add_failed"


class PendingDeletionType(StrEnum):
    """When a tracked platform message is cleaned: on the next user input or when the next feedback is sent."""

    USER_INPUT = "user_input"
    FEEDBACK = "feedback"


class DbPendingDeletionsMixin:
    """Pending platform-message deletions recorded per session and owning adapter, read and removed as cleanup succeeds."""

    async def get_pending_deletions(
        self,
        session_id: str,
        adapter_key: str,
        deletion_type: str = PendingDeletionType.USER_INPUT,
    ) -> list[str]:
        """Get list of pending deletion message IDs for session.

        Args:
            session_id: Session identifier
            adapter_key: UI adapter that owns the platform message identifier
            deletion_type: Type of deletion - 'user_input' (cleaned on next user input)
                          or 'feedback' (cleaned when next feedback is sent)

        Returns:
            List of message IDs to delete (empty list if none)
        """
        deletion_type = PendingDeletionType(deletion_type)
        stmt = select(db_models.PendingMessageDeletion.message_id).where(
            db_models.PendingMessageDeletion.session_id == session_id,
            db_models.PendingMessageDeletion.adapter_key == adapter_key,
            db_models.PendingMessageDeletion.deletion_type == deletion_type,
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            rows = result.all()
            return [str(row) for row in rows]

    async def add_pending_deletion(
        self,
        session_id: str,
        adapter_key: str,
        message_id: str,
        deletion_type: str = PendingDeletionType.USER_INPUT,
    ) -> None:
        """Add message ID to pending deletions for session.

        Args:
            session_id: Session identifier
            adapter_key: UI adapter that owns the platform message identifier
            message_id: Message ID to delete later
            deletion_type: Type of deletion - 'user_input' (cleaned on next user input)
                          or 'feedback' (cleaned when next feedback is sent)
        """
        deletion_type = PendingDeletionType(deletion_type)
        try:
            async with self._session() as db_session:
                db_session.add(
                    db_models.PendingMessageDeletion(
                        session_id=session_id,
                        adapter_key=adapter_key,
                        message_id=message_id,
                        deletion_type=deletion_type,
                    )
                )
                await db_session.commit()
        except SQLAlchemyError as exc:
            # Callers record the row after the platform message already exists, so a failed tracking write
            # costs one uncleaned message; raising would fail the delivery or input path over cleanup bookkeeping.
            logger.error(
                _ADD_PENDING_DELETION_FAILED_EVENT,
                session_id=session_id,
                adapter_key=adapter_key,
                message_id=message_id,
                deletion_type=deletion_type,
                error=str(exc),
            )

    async def clear_pending_deletions(
        self,
        session_id: str,
        adapter_key: str,
        deletion_type: str = PendingDeletionType.USER_INPUT,
    ) -> None:
        """Clear all pending deletions for session.

        Args:
            session_id: Session identifier
            adapter_key: UI adapter that owns the platform message identifier
            deletion_type: Type of deletion to clear
        """
        deletion_type = PendingDeletionType(deletion_type)
        stmt = (
            db_models.PendingMessageDeletion.__table__.delete()
            .where(db_models.PendingMessageDeletion.session_id == session_id)
            .where(db_models.PendingMessageDeletion.adapter_key == adapter_key)
            .where(db_models.PendingMessageDeletion.deletion_type == deletion_type)
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)  # type: ignore[arg-type]
            await db_session.commit()

    async def remove_pending_deletion(
        self,
        session_id: str,
        adapter_key: str,
        message_id: str,
        deletion_type: str = PendingDeletionType.USER_INPUT,
    ) -> None:
        """Remove one successfully deleted platform message from the pending set."""
        deletion_type = PendingDeletionType(deletion_type)
        stmt = (
            db_models.PendingMessageDeletion.__table__.delete()
            .where(db_models.PendingMessageDeletion.session_id == session_id)
            .where(db_models.PendingMessageDeletion.adapter_key == adapter_key)
            .where(db_models.PendingMessageDeletion.message_id == message_id)
            .where(db_models.PendingMessageDeletion.deletion_type == deletion_type)
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)  # type: ignore[arg-type]
            await db_session.commit()
