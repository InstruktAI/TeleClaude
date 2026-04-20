"""Command context types for TeleClaude."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:

    class InlineKeyboardMarkup(Protocol):
        """Telegram inline keyboard marker interface for type checking."""


@dataclass
class BaseCommandContext:
    """Base context - all session-based commands have session_id."""

    session_id: str


@dataclass
class SessionCommandContext(BaseCommandContext):
    """Context for commands operating on an existing session."""


@dataclass
class NewSessionContext(BaseCommandContext):
    """Context for creating a new session."""

    project_path: str
    title: str
    message: str


@dataclass
class MessageContext(BaseCommandContext):
    """Context for message commands."""

    text: str


@dataclass
class VoiceContext(BaseCommandContext):
    """Context for voice commands."""

    audio_path: str


@dataclass
class FileContext(BaseCommandContext):
    """Context for file upload commands."""

    file_path: str
    mime_type: str | None = None


@dataclass
class SystemCommandContext:
    """Context for system commands (no session_id required)."""

    command: str = ""
    from_computer: str = "unknown"
