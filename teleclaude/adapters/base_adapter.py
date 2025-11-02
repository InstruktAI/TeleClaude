"""Base adapter interface for TeleClaude messaging platforms."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Message:
    """Represents an outgoing message."""

    session_id: str
    text: str
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class File:
    """Represents a file to send."""

    session_id: str
    file_path: str
    caption: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class BaseAdapter(ABC):
    """Abstract base class for all messaging platform adapters."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize adapter with configuration.

        Args:
            config: Adapter-specific configuration
        """
        self.config = config
        self._message_callbacks: List[Callable[..., Any]] = []
        self._file_callbacks: List[Callable[..., Any]] = []
        self._voice_callbacks: List[Callable[..., Any]] = []
        self._command_callbacks: List[Callable[..., Any]] = []
        self._topic_closed_callbacks: List[Callable[..., Any]] = []

    # ==================== Lifecycle Methods ====================

    @abstractmethod
    async def start(self) -> None:
        """Initialize adapter and start listening for incoming messages."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop adapter and cleanup resources."""
        pass

    # ==================== Outgoing Messages ====================

    @abstractmethod
    async def send_message(self, session_id: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Send a text message to the channel associated with session_id.

        Args:
            session_id: Unique session identifier
            text: Message text
            metadata: Optional adapter-specific metadata

        Returns:
            message_id: Platform-specific message ID
        """
        pass

    @abstractmethod
    async def edit_message(
        self, session_id: str, message_id: str, text: str, metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Edit an existing message.

        Args:
            session_id: Session identifier
            message_id: Message ID from send_message()
            text: New message text
            metadata: Optional adapter-specific metadata

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    async def delete_message(self, session_id: str, message_id: str) -> bool:
        """Delete a message.

        Args:
            session_id: Session identifier
            message_id: Message ID to delete

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    async def send_file(
        self, session_id: str, file_path: str, caption: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Upload and send a file.

        Args:
            session_id: Session identifier
            file_path: Local path to file
            caption: Optional caption
            metadata: Optional adapter-specific metadata

        Returns:
            message_id: Message ID of the file message
        """
        pass

    @abstractmethod
    async def send_general_message(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Send message to general/default channel.

        Used for commands issued in general context (not tied to specific session).

        Args:
            text: Message text
            metadata: Platform-specific routing info (thread_id, channel_id, etc.)

        Returns:
            message_id: Platform-specific message ID
        """
        pass

    # ==================== Channel Management ====================

    @abstractmethod
    async def create_channel(self, session_id: str, title: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Create a new channel/topic/thread for the session.

        Args:
            session_id: Session identifier
            title: Channel title
            metadata: Optional adapter-specific metadata

        Returns:
            channel_id: Platform-specific channel identifier
        """
        pass

    @abstractmethod
    async def update_channel_title(self, channel_id: str, title: str) -> bool:
        """Update the title of an existing channel.

        Args:
            channel_id: Channel identifier
            title: New title

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    async def set_channel_status(self, channel_id: str, status: str) -> bool:
        """Update status indicator in channel title.

        Args:
            channel_id: Channel identifier
            status: Status ('active', 'waiting', 'slow', 'stalled', 'idle', 'dead')

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    async def delete_channel(self, channel_id: str) -> bool:
        """Delete a channel/topic/thread.

        Args:
            channel_id: Channel identifier

        Returns:
            True if successful, False otherwise
        """
        pass

    # ==================== Callback Registration ====================

    def on_message(self, callback: Callable[..., Any]) -> None:
        """Register callback for incoming text messages.

        Callback signature:
            async def callback(session_id: str, text: str, context: Dict) -> None
        """
        self._message_callbacks.append(callback)

    def on_file(self, callback: Callable[..., Any]) -> None:
        """Register callback for incoming file uploads.

        Callback signature:
            async def callback(session_id: str, file_path: str, context: Dict) -> None
        """
        self._file_callbacks.append(callback)

    def on_voice(self, callback: Callable[..., Any]) -> None:
        """Register callback for incoming voice messages.

        Callback signature:
            async def callback(session_id: str, audio_path: str, context: Dict) -> None
        """
        self._voice_callbacks.append(callback)

    def on_command(self, callback: Callable[..., Any]) -> None:
        """Register callback for bot commands.

        Callback signature:
            async def callback(command: str, args: List[str], context: Dict) -> None
        """
        self._command_callbacks.append(callback)

    def on_topic_closed(self, callback: Callable[..., Any]) -> None:
        """Register callback for topic/channel closure.

        Callback signature:
            async def callback(session_id: str, context: Dict) -> None
        """
        self._topic_closed_callbacks.append(callback)

    # ==================== Helper Methods ====================

    async def _emit_message(self, session_id: str, text: str, context: Dict[str, Any]) -> None:
        """Emit message event to all registered callbacks."""
        for callback in self._message_callbacks:
            await callback(session_id, text, context)

    async def _emit_file(self, session_id: str, file_path: str, context: Dict[str, Any]) -> None:
        """Emit file event to all registered callbacks."""
        for callback in self._file_callbacks:
            await callback(session_id, file_path, context)

    async def _emit_voice(self, session_id: str, audio_path: str, context: Dict[str, Any]) -> None:
        """Emit voice event to all registered callbacks."""
        for callback in self._voice_callbacks:
            await callback(session_id, audio_path, context)

    async def _emit_command(self, command: str, args: List[str], context: Dict[str, Any]) -> None:
        """Emit command event to all registered callbacks."""
        for callback in self._command_callbacks:
            await callback(command, args, context)

    async def _emit_topic_closed(self, session_id: str, context: Dict[str, Any]) -> None:
        """Emit topic closed event to all registered callbacks."""
        for callback in self._topic_closed_callbacks:
            await callback(session_id, context)


class AdapterError(Exception):
    """Base exception for adapter errors."""

    pass
