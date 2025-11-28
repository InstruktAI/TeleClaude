"""Base adapter interface for TeleClaude messaging platforms."""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
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

    # ==================== Session Data Access ====================

    async def get_session_data(
        self,
        session_id: str,
        since_timestamp: Optional[str] = None,
    ) -> dict[str, object]:
        """Read session data from Claude Code session file.

        This is a shared capability for ALL adapters to serve session data
        from the standard claude_session_file location.

        Args:
            session_id: Session identifier
            since_timestamp: Optional ISO 8601 UTC timestamp to filter messages since

        Returns:
            Dict containing:
            - "status": "success" or "error"
            - "messages": Session content (markdown format)
            - "session_id": Session identifier
            - "error": Error message if status is "error"
        """
        # Get session file path
        session_file = Path("storage") / session_id / "claude_session_file"

        if not session_file.exists():
            return {
                "status": "error",
                "error": f"Session file not found for session {session_id[:8]}",
                "session_id": session_id,
            }

        # Read session file content
        try:
            content = session_file.read_text()
        except Exception as e:
            logger.error("Failed to read session file for %s: %s", session_id[:8], e)
            return {
                "status": "error",
                "error": f"Failed to read session file: {str(e)}",
                "session_id": session_id,
            }

        # If no timestamp filter, return all content
        if not since_timestamp:
            return {
                "status": "success",
                "messages": content,
                "session_id": session_id,
            }

        # Parse timestamp and filter content
        # TODO: Implement timestamp filtering logic
        # For now, return all content with note
        try:
            datetime.fromisoformat(since_timestamp)
            return {
                "status": "success",
                "messages": content,
                "session_id": session_id,
                "note": "Timestamp filtering not yet implemented",
            }
        except ValueError:
            return {
                "status": "error",
                "error": f"Invalid timestamp format: {since_timestamp}",
                "session_id": session_id,
            }

    async def _handle_session_data(
        self,
        args: str,
        session_id: str,
        metadata: Optional[dict[str, object]] = None,
    ) -> Optional[str]:
        """Handle /session_data command.

        Reads claude_session_file and returns content, optionally filtered by timestamp.

        Args:
            args: Timestamp in ISO 8601 UTC format (optional)
            session_id: Session identifier (unused - reads from request)
            metadata: Command metadata with "session_id" to read

        Returns:
            JSON response with session data
        """
        # Extract target session_id from metadata (not the command's session_id)
        target_session_id = metadata.get("session_id") if metadata else None
        if not target_session_id:
            return json.dumps(
                {
                    "status": "error",
                    "error": "session_id not provided in metadata",
                }
            )

        # Parse timestamp from args
        since_timestamp = args.strip() if args else None

        # Get session data
        result = await self.get_session_data(str(target_session_id), since_timestamp)

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
