"""Base adapter interface for TeleClaude messaging platforms."""

import json
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, AsyncIterator, Optional

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = logging.getLogger(__name__)


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

    async def send_feedback(
        self,
        session_id: str,
        message: str,
        metadata: Optional[dict[str, object]] = None,
    ) -> Optional[str]:
        """Send feedback message to user (UI adapters only).

        Feedback messages are temporary UI notifications that:
        - Appear in UI platforms (Telegram, Slack, etc.)
        - Do NOT appear in terminal/tmux output
        - Auto-delete on next user input (UI adapters handle this)

        Base implementation does nothing (for transport adapters like Redis).
        UI adapters (UiAdapter subclasses) override to send feedback.

        Args:
            session_id: Session identifier
            message: Feedback message text
            metadata: Optional adapter-specific metadata

        Returns:
            message_id if sent (UI adapters), None if not a UI adapter
        """
        return None  # Default no-op for non-UI adapters (Redis, etc.)

    # ==================== Session Data Access ====================

    async def get_session_data(
        self,
        session_id: str,
        since_timestamp: Optional[str] = None,
    ) -> dict[str, object]:
        """Read session data from Claude Code session file.

        NOTE: This method is not currently used. The actual implementation
        is in teleclaude.core.command_handlers.handle_get_session_data() which
        is called via event routing when /get_session_data command is received.

        Kept for interface compatibility but not the active code path.

        Args:
            session_id: Session identifier
            since_timestamp: Optional ISO 8601 UTC timestamp to filter messages since

        Returns:
            Dict with error (not implemented via this path)
        """
        return {
            "status": "error",
            "error": "get_session_data should be called via command_handlers, not directly",
            "session_id": session_id,
        }

    async def _handle_get_session_data(
        self,
        args: str,
        session_id: str,
        metadata: Optional[dict[str, object]] = None,
    ) -> Optional[str]:
        """Handle /get_session_data command.

        Reads claude_session_file and returns content, optionally filtered by timestamp.

        Args:
            args: Timestamp in ISO 8601 UTC format (optional)
            session_id: Session identifier (unused - reads from request)
            metadata: Command metadata with "session_id" to read

        Returns:
            JSON response with session data
        """
        logger.debug("_handle_get_session_data called with args=%s, metadata=%s", args, metadata)

        # Extract target session_id from metadata (not the command's session_id)
        target_session_id = metadata.get("session_id") if metadata else None
        if not target_session_id:
            logger.warning("get_session_data: no session_id in metadata")
            return json.dumps(
                {
                    "status": "error",
                    "error": "session_id not provided in metadata",
                }
            )

        # Parse timestamp from args
        since_timestamp = args.strip() if args else None
        logger.debug("get_session_data: target_session=%s, since=%s", target_session_id[:8] if isinstance(target_session_id, str) else target_session_id, since_timestamp)

        # Get session data
        result = await self.get_session_data(str(target_session_id), since_timestamp)
        logger.debug("get_session_data: result has %d messages", result.get("message_count", 0) if isinstance(result, dict) else 0)

        return json.dumps(result)

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
