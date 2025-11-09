"""Base adapter interface for TeleClaude messaging platforms."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Optional

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient


class BaseAdapter(ABC):
    """Abstract base class for all messaging platform adapters.

    Adapters are responsible for platform-specific communication.
    All communication with daemon flows through AdapterClient (not direct).
    """

    # Platform identification - override in subclasses
    has_ui: bool = True  # Whether adapter has human-visible UI (False for Redis)
    client: "AdapterClient"  # Set by subclasses in __init__

    def __init__(self) -> None:
        """Initialize adapter.

        Subclasses should accept adapter_client as first parameter.
        """
        pass

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
    async def set_channel_status(
        self,
        session_id: str,
        status: str,
    ) -> bool:
        """Set channel status (e.g., active, idle, closed).

        Args:
            session_id: Session identifier
            status: Status string

        Returns:
            True if successful, False otherwise
        """

    @abstractmethod
    async def delete_channel(self, session_id: str) -> bool:
        """Delete channel/topic.

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
    ) -> bool:
        """Edit existing message (if platform supports).

        Args:
            session_id: Session identifier
            message_id: Message ID from send_message()
            text: New message text

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

    # ==================== Optional: Voice Support ====================

    async def _process_voice_input(
        self,
        session_id: str,
        audio_file_path: str,
        context: dict[str, object],
    ) -> None:
        """Shared voice processing logic (adapter-agnostic).

        Only implemented by adapters with voice support (has_ui=True).

        Default implementation uses voice_message_handler.py utility.
        Override if platform needs custom voice handling.

        Flow:
        1. Validate session and check if process is running
        2. Send "Transcribing..." feedback to user
        3. Transcribe audio using voice_message_handler.py
        4. Send transcribed text to terminal
        5. Send feedback on success/failure

        Args:
            session_id: Session ID
            audio_file_path: Path to audio file (any format supported by Whisper)
            context: Platform-specific metadata (user_id, duration, etc.)
        """
        from teleclaude.core.voice_message_handler import handle_voice

        # Delegate to utility module (keeps BaseAdapter thin)
        await handle_voice(
            session_id=session_id,
            audio_path=audio_file_path,
            context=context,
            send_feedback=lambda sid, msg, append: self.send_message(sid, msg),
            get_output_file=self._get_output_file,
        )

    # ==================== Optional: File Handling ====================

    async def get_session_file(
        self,
        session_id: str,
    ) -> Optional[str]:
        """Provide platform-specific download UI for session output.

        OPTIONAL - Only implement if adapter can offer download functionality.

        Examples:
        - TelegramAdapter: Upload file to Telegram, create download button, return message_id
        - WhatsAppAdapter: Upload to WhatsApp as media message
        - RedisAdapter: Not applicable (no UI)

        Args:
            session_id: Session identifier

        Returns:
            Platform-specific identifier/link if download UI created, None otherwise

        NOTE: This is different from _get_output_file() which returns local file PATH.
        """
        return None  # Default: no download functionality

    def _get_output_file(self, session_id: str) -> Path:
        """Get local file system PATH to session output file.

        Used internally by adapters that need to READ the output file
        (e.g., for uploading, processing, voice status appending).

        Default implementation uses standard session_output directory.
        Override if adapter stores output files in custom location.

        Args:
            session_id: Session identifier

        Returns:
            Path object pointing to local file (e.g., "session_output/abc123.txt")

        NOTE: This is different from get_session_file() which creates download UI.
        """
        # Use standard session_output directory (same as daemon)
        return Path("session_output") / f"{session_id[:8]}.txt"


class AdapterError(Exception):
    """Base exception for adapter errors."""

    pass
