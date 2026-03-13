"""BaseAdapter no-op implementations for RedisTransport.

Redis transport does not stream session output; all channel/message
operations are no-ops or trivially return empty values.
"""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.core.db import db
from teleclaude.core.models import ChannelMetadata, MessageMetadata, Session

logger = get_logger(__name__)


class _AdapterNoopMixin:
    """Mixin: BaseAdapter no-op overrides for Redis transport."""

    async def send_message(
        self,
        session: Session,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> str:
        """Redis transport does not stream session output; noop for compatibility."""
        logger.debug(
            "send_message ignored for RedisTransport (session output streaming disabled): %s",
            session.session_id,
        )
        return ""

    async def edit_message(
        self, session: Session, message_id: str, text: str, *, metadata: MessageMetadata | None = None
    ) -> bool:
        """No-op for Redis transport."""
        logger.debug(
            "edit_message ignored for RedisTransport (session output streaming disabled): %s",
            session.session_id,
        )
        return True

    async def delete_message(self, session: Session, message_id: str) -> bool:
        """No-op for Redis transport."""
        logger.debug(
            "delete_message ignored for RedisTransport (session output streaming disabled): %s",
            session.session_id,
        )
        return True

    async def send_error_feedback(self, session_id: str, error_message: str) -> None:
        """No-op for Redis transport (errors surface via request/response)."""
        logger.debug(
            "send_error_feedback ignored for RedisTransport (session output streaming disabled): %s",
            session_id,
        )

    async def send_file(
        self,
        session: Session,
        file_path: str,
        *,
        caption: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> str:
        """Send file - not supported by Redis adapter.

        Args:
            session: Session object
            file_path: Path to file
            metadata: Optional metadata
            caption: Optional caption

        Returns:
            Empty string (not supported)
        """
        logger.warning("send_file not supported by RedisTransport")
        return ""

    async def send_general_message(self, text: str, *, metadata: MessageMetadata | None = None) -> str:
        """Send general message (not implemented for Redis).

        Redis adapter is session-specific, no general channel.

        Args:
            text: Message text
            metadata: Optional metadata

        Returns:
            Empty string
        """
        logger.warning("send_general_message not supported by RedisTransport")
        return ""

    async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
        """Record transport metadata for AI-to-AI sessions (no Redis output streams)."""

        redis_meta = session.get_metadata().get_transport().get_redis()

        if metadata.target_computer:
            redis_meta.target_computer = metadata.target_computer
            logger.info(
                "Recorded Redis target for AI-to-AI session %s: target=%s",
                session.session_id,
                metadata.target_computer,
            )

        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        return ""

    async def update_channel_title(self, session: Session, title: str) -> bool:
        """Update channel title (no-op for Redis).

        Args:
            session: Session object
            title: New title

        Returns:
            True
        """
        return True

    async def close_channel(self, session: Session) -> bool:
        """No-op: Redis has no persistent channels to close.

        Args:
            session: Session object

        Returns:
            True (always succeeds)
        """
        return True

    async def reopen_channel(self, session: Session) -> bool:
        """No-op: Redis has no persistent channels to reopen.

        Args:
            session: Session object

        Returns:
            True (always succeeds)
        """
        return True

    async def delete_channel(self, session: Session) -> bool:
        """No-op: Redis transport does not create per-session output streams."""
        return True
