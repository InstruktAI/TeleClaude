"""Abstract base class for agent log parsers.

Parsers are responsible for interpreting agent log files and extracting
TeleClaude events (start, stop, notification, etc.).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Optional


@dataclass
class LogEvent:
    """Represents a detected event from an agent log."""

    event_type: str  # "session_start", "agent_stop", "notification", "title_update"
    data: dict[str, object]  # guard: loose-dict - Generic parse result
    timestamp: float


class LogParser(ABC):
    """Abstract base class for log parsers."""

    @abstractmethod
    def can_parse(self, file_path: Path) -> bool:
        """Check if this parser can handle the given file."""
        pass

    @abstractmethod
    def parse_line(self, line: str) -> Generator[LogEvent, None, None]:
        """Parse a single line from the log file and yield events.

        Args:
            line: A single line from the log file.

        Yields:
            LogEvent: Detected events (0 or more per line).
        """
        pass

    @abstractmethod
    def extract_session_id(self, file_path: Path) -> Optional[str]:
        """Extract the native session ID from the file (if possible).

        Args:
            file_path: Path to the log file.

        Returns:
            Native session ID string if found, None otherwise.
        """
        pass

    @abstractmethod
    def extract_last_turn(self, file_path: Path) -> str:
        """Extract the text content of the last assistant/model turn.

        Used for summarization. Should return the plain text of what the agent did
        since the last user input.

        Args:
            file_path: Path to the log file.

        Returns:
            Text content of the last turn.
        """
        pass
