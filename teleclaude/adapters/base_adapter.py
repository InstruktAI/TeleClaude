"""Base adapter interface for TeleClaude messaging platforms."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, AsyncIterator, Optional

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient


class BaseAdapter(ABC):
    """Abstract base class for all messaging platform adapters.

    Adapters are responsible for platform-specific communication.
    All communication with daemon flows through AdapterClient (not direct).
    """

    client: "AdapterClient"  # Set by subclasses in __init__

    # ==================== Lifecycle Methods ====================

    @abstractmethod
    async def start(self) -> None:
        """Initialize adapter and start listening for incoming messages.

        Each adapter manages its own event loop (push or pull based).
        """

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop adapter and cleanup resources."""

    # ==================== Channel Management ====================

    @abstractmethod
    async def create_channel(
        self,
        session_id: str,
        title: str,
        metadata: dict[str, object],
    ) -> str:
        """Create channel/topic for session.

        Args:
            session_id: Session ID
            title: Channel title
            metadata: {
                "origin": bool,  # True if this adapter is origin
                "origin_adapter": str,  # Which adapter is origin
            }

        Returns:
            channel_id (platform-specific identifier)
        """

    @abstractmethod
    async def update_channel_title(self, session_id: str, title: str) -> bool:
        """Update channel/topic title.

        Args:
            session_id: Session identifier
            title: New title

        Returns:
            True if successful, False otherwise
        """

    @abstractmethod
    async def close_channel(self, session_id: str) -> bool:
        """Soft-close channel (can be reopened).

        Args:
            session_id: Session identifier

        Returns:
            True if successful, False if channel doesn't exist
        """

    @abstractmethod
    async def reopen_channel(self, session_id: str) -> bool:
        """Reopen a closed channel.

        Args:
            session_id: Session identifier

        Returns:
            True if successful, False if channel doesn't exist
        """

    @abstractmethod
    async def delete_channel(self, session_id: str) -> bool:
        """Delete channel/topic (permanent, cannot be reopened).

        Args:
            session_id: Session identifier

        Returns:
            True if successful, False otherwise
        """

    # ==================== Messaging ====================

    @abstractmethod
    async def send_message(
        self,
        session_id: str,
        text: str,
        metadata: Optional[dict[str, object]] = None,
    ) -> str:
        """Send message to channel.

        Used for:
        - Terminal output
        - User feedback (status, errors)
        - System notifications

        Args:
            session_id: Session identifier
            text: Message text
            metadata: Optional adapter-specific metadata

        Returns:
            message_id
        """

    @abstractmethod
    async def edit_message(
        self,
        session_id: str,
        message_id: str,
        text: str,
        metadata: Optional[dict[str, object]] = None,
    ) -> bool:
        """Edit existing message (if platform supports).

        Args:
            session_id: Session identifier
            message_id: Message ID from send_message()
            text: New message text
            metadata: Optional platform-specific metadata (e.g., reply_markup for buttons)

        Returns:
            True if successful, False otherwise
        """

    @abstractmethod
    async def delete_message(
        self,
        session_id: str,
        message_id: str,
    ) -> bool:
        """Delete message (if platform supports).

        Args:
            session_id: Session identifier
            message_id: Message ID to delete

        Returns:
            True if successful, False otherwise
        """

    @abstractmethod
    async def send_file(
        self,
        session_id: str,
        file_path: str,
        caption: Optional[str] = None,
        metadata: Optional[dict[str, object]] = None,
    ) -> str:
        """Send file to channel (if platform supports).

        Args:
            session_id: Session identifier
            file_path: Absolute path to file
            caption: Optional file caption/description
            metadata: Optional platform-specific metadata

        Returns:
            message_id of sent file
        """

    async def send_general_message(self, text: str, metadata: Optional[dict[str, object]] = None) -> str:
        """Send message to general/default channel.

        Used for commands issued in general context (not tied to specific session).

        Args:
            text: Message text
            metadata: Platform-specific routing info (thread_id, channel_id, etc.)

        Returns:
            message_id: Platform-specific message ID

        Note: Not abstract - adapters can override if they support general messages.
        """
        raise NotImplementedError("This adapter does not support general messages")

    # ==================== Peer Discovery ====================

    @abstractmethod
    async def discover_peers(self) -> list[dict[str, object]]:
        """Discover online computers via this adapter's mechanism.

        Each adapter implements its own discovery mechanism:
        - TelegramAdapter: Polls General topic for [REGISTRY] messages
        - RedisAdapter: Reads Redis heartbeat keys

        Returns:
            List of dicts with:
            - name: Computer name
            - status: "online" or "offline"
            - last_seen: datetime
            - adapter_type: Which adapter discovered this
        """

    # ==================== AI-to-AI Communication ====================

    @abstractmethod
    async def poll_output_stream(
        self,
        session_id: str,
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        """Poll for output chunks from remote session.

        Used for bidirectional AI-to-AI communication.

        Implementations:
        - RedisAdapter: XREAD output:{session_id} stream
        - TelegramAdapter: Not applicable (no AI-to-AI support)

        Args:
            session_id: Session identifier
            timeout: Maximum time to wait for output (seconds)

        Yields:
            Output chunks as they arrive
        """
        raise NotImplementedError("poll_mcp_messages must be implemented by subclass")
        yield  # Make mypy happy about async generator type

    # ==================== Platform-Specific Parameters ====================

    def get_max_message_length(self) -> int:
        """Get platform's max message length for chunking.

        Returns:
            Maximum characters per message (platform-specific).
            Used for AI-to-AI output chunking.
        """
        raise NotImplementedError

    def get_ai_session_poll_interval(self) -> float:
        """Get polling interval for AI-to-AI sessions (seconds).

        Returns:
            Optimal polling frequency for this platform.
            Faster than human mode for real-time AI communication.
        """
        raise NotImplementedError


class AdapterError(Exception):
    """Base exception for adapter errors."""

    pass
