"""BaseAdapter no-op implementations for RedisTransport.

Redis transport does not stream session output; all channel/message
operations are no-ops or trivially return empty values.
"""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.core.models import MessageMetadata, Session

logger = get_logger(__name__)


class _AdapterNoopMixin:  # pyright: ignore[reportUnusedClass]
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
        _ = (text, metadata, multi_message)
        logger.debug(
            "send_message ignored for RedisTransport (session output streaming disabled): %s",
            session.session_id,
        )
        return ""

    async def edit_message(
        self, session: Session, message_id: str, text: str, *, metadata: MessageMetadata | None = None
    ) -> bool:
        """No-op for Redis transport."""
        _ = (message_id, text, metadata)
        logger.debug(
            "edit_message ignored for RedisTransport (session output streaming disabled): %s",
            session.session_id,
        )
        return True

    async def delete_message(self, session: Session, message_id: str) -> bool:
        """No-op for Redis transport."""
        _ = message_id
        logger.debug(
            "delete_message ignored for RedisTransport (session output streaming disabled): %s",
            session.session_id,
        )
        return True

    async def send_error_feedback(self, session_id: str, error_message: str) -> None:
        """No-op for Redis transport (errors surface via request/response)."""
        _ = error_message
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
        _ = (session, file_path, caption, metadata)
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
        _ = (text, metadata)
        logger.warning("send_general_message not supported by RedisTransport")
        return ""
