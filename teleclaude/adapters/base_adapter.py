"""Base adapter interface for TeleClaude messaging platforms."""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import wraps
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Protocol,
    runtime_checkable,
)

from instrukt_ai_logging import get_logger

from teleclaude.core.db import db
from teleclaude.core.models import ChannelMetadata, MessageMetadata, PeerInfo

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)


@runtime_checkable
class _HasSessionId(Protocol):
    session_id: str


def with_error_feedback(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Decorator to send adapter-specific error feedback on exceptions.

    Extracts session_id from first argument (str or Session.session_id) and
    calls adapter's send_error_feedback method before re-raising.
    """

    @wraps(func)
    async def wrapper(self: Any, *args: object, **kwargs: object) -> Any:
        session_id: str | None = None
        if args:
            first_arg: object = args[0]
            if isinstance(first_arg, str):
                session_id = first_arg
            elif isinstance(first_arg, _HasSessionId):
                session_id = first_arg.session_id

        try:
            return await func(self, *args, **kwargs)
        except Exception as e:
            if session_id and hasattr(self, "send_error_feedback"):
                await self.send_error_feedback(session_id, str(e))
            raise

    return wrapper


class BaseAdapter(ABC):
    """Abstract base class for all messaging platform adapters.

    Adapters are responsible for platform-specific communication.
    All communication with daemon flows through AdapterClient (not direct).
    """

    client: "AdapterClient"  # Set by subclasses in __init__
    ADAPTER_KEY: str  # Subclasses must define this constant

    def _metadata(self, **kwargs: object) -> MessageMetadata:
        """Create MessageMetadata with origin pre-set.

        Args:
            **kwargs: Additional metadata fields (message_thread_id, title, etc.)

        Returns:
            MessageMetadata with origin set to this adapter's ADAPTER_KEY
        """
        return MessageMetadata(origin=self.ADAPTER_KEY, **kwargs)  # pyright: ignore[reportArgumentType]

    async def _get_session(self, session_id: str) -> "Session":
        """Get session from database, raise if not found.

        Args:
            session_id: Session identifier

        Returns:
            Session object

        Raises:
            ValueError: If session not found
        """
        session = await db.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        return session

    async def send_error_feedback(self, session_id: str, error_message: str) -> None:
        """Send error feedback to user (adapter-specific).

        Args:
            session_id: Session that encountered error
            error_message: Human-readable error description

        Default no-op for non-interactive adapters.
        UI adapters override to send feedback messages.
        Redis adapter overrides to publish error envelopes.
        """
        # Default: do nothing

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
        session: "Session",
        title: str,
        metadata: ChannelMetadata,
    ) -> str:
        """Create channel/topic for session.

        Args:
            session: Session object
            title: Channel title
            metadata: {
                "origin": bool,  # True if this adapter is origin
                "last_input_origin": str,  # Last input origin
            }

        Returns:
            channel_id (platform-specific identifier)
        """

    @abstractmethod
    async def update_channel_title(self, session: "Session", title: str) -> bool:
        """Update channel/topic title.

        Args:
            session: Session object
            title: New title

        Returns:
            True if successful, False otherwise
        """

    @abstractmethod
    async def close_channel(self, session: "Session") -> bool:
        """Soft-close channel (can be reopened).

        Args:
            session: Session object

        Returns:
            True if successful, False if channel doesn't exist
        """

    @abstractmethod
    async def reopen_channel(self, session: "Session") -> bool:
        """Reopen a closed channel.

        Args:
            session: Session object

        Returns:
            True if successful, False if channel doesn't exist
        """

    @abstractmethod
    async def delete_channel(self, session: "Session") -> bool:
        """Delete channel/topic (permanent, cannot be reopened).

        Args:
            session: Session object

        Returns:
            True if successful, False otherwise
        """

    # ==================== Messaging ====================

    @abstractmethod
    async def send_message(
        self,
        session: "Session",
        text: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> str:
        """Send message to channel.

        Args:
            session: Session object
            text: Message text
            metadata: Adapter-specific metadata (optional)

        Returns:
            message_id
        """

    @abstractmethod
    async def edit_message(
        self,
        session: "Session",
        message_id: str,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> bool:
        """Edit existing message (if platform supports).

        Args:
            session: Session object
            message_id: Message ID from send_message()
            text: New message text
            metadata: Platform-specific metadata (optional)

        Returns:
            True if successful, False otherwise
        """

    @abstractmethod
    async def delete_message(
        self,
        session: "Session",
        message_id: str,
    ) -> bool:
        """Delete message (if platform supports).

        Args:
            session: Session object
            message_id: Message ID to delete

        Returns:
            True if successful, False otherwise
        """

    @abstractmethod
    async def send_file(
        self,
        session: "Session",
        file_path: str,
        *,
        caption: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> str:
        """Send file to channel (if platform supports).

        Args:
            session: Session object
            file_path: Absolute path to file
            caption: Optional file caption/description
            metadata: Platform-specific metadata (optional)

        Returns:
            message_id of sent file
        """

    async def send_general_message(self, text: str, *, metadata: MessageMetadata | None = None) -> str:
        """Send message to general/default channel.

        Used for commands issued in general context (not tied to specific session).

        Args:
            text: Message text
            metadata: Platform-specific routing info (optional)

        Returns:
            message_id: Platform-specific message ID

        Note: Not abstract - adapters can override if they support general messages.
        """
        raise NotImplementedError("This adapter does not support general messages")

    # ==================== Session Data Access ====================

    # ==================== Peer Discovery ====================

    @abstractmethod
    async def discover_peers(self) -> list[PeerInfo]:
        """Discover online computers via this adapter's mechanism.

        Each adapter implements its own discovery mechanism:
        - TelegramAdapter: Polls General topic for [REGISTRY] messages
        - RedisTransport: Reads Redis heartbeat keys

        Returns:
            List of PeerInfo instances with peer computer information
        """

    # ==================== AI-to-AI Communication ====================

    @abstractmethod
    async def poll_output_stream(
        self,
        session: "Session",
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        """Poll for output chunks from remote session.

        Note: current MCP usage polls session output via get_session_data; output
        streaming is disabled in RedisTransport.

        Args:
            session: Session object
            timeout: Maximum time to wait for output (seconds)

        Yields:
            Output chunks as they arrive
        """
        raise NotImplementedError("poll_mcp_messages must be implemented by subclass")

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
