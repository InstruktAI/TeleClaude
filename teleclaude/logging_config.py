"""
Centralized logging configuration for TeleClaude.

Provides standardized log format across all modules:
[2025-10-30 12:05:31.454] INFO > teleclaude/daemon.py: message
"""

import logging
import os
import sys
from datetime import datetime
from typing import Any, Optional

# Add TRACE level (below DEBUG)
TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def trace(self: logging.Logger, message: str, *args: Any, **kwargs: Any) -> None:
    """Log trace message."""
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)  # pylint: disable=protected-access


# Add custom methods to Logger class
logging.Logger.trace = trace  # type: ignore[attr-defined]


# ANSI color codes
class Colors:
    """ANSI color codes for terminal output."""

    RESET = "\033[0m"
    GRAY = "\033[90m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"


# Level to color mapping
LEVEL_COLORS = {
    "TRACE": Colors.GRAY,
    "DEBUG": Colors.CYAN,
    "INFO": Colors.GREEN,
    "WARNING": Colors.YELLOW,
    "ERROR": Colors.RED,
    "CRITICAL": Colors.MAGENTA,
}


class PathFormatter(logging.Formatter):
    """Custom formatter that shows relative file paths, milliseconds, and colors."""

    def __init__(self, *args: Any, use_colors: bool = True, **kwargs: Any) -> None:
        """Initialize formatter.

        Args:
            use_colors: Whether to use ANSI colors (True for console, False for files)
        """
        super().__init__(*args, **kwargs)
        self.use_colors = use_colors

    def formatTime(self, record: logging.LogRecord, datefmt: Optional[str] = None) -> str:
        """Format time with milliseconds support."""
        ct = datetime.fromtimestamp(record.created)
        if datefmt:
            # Remove .%f from format (strftime outputs 6-digit microseconds, we want 3-digit milliseconds)
            if ".%f" in datefmt:
                datefmt_no_frac = datefmt.replace(".%f", "")
                return ct.strftime(datefmt_no_frac) + f".{int(record.msecs):03d}"
            return ct.strftime(datefmt)
        return ct.strftime("%Y-%m-%d %H:%M:%S") + f".{int(record.msecs):03d}"

    def format(self, record: logging.LogRecord) -> str:
        # Convert module name (teleclaude.core.session_manager) to path (teleclaude/core/session_manager.py)
        if record.name != "__main__":
            pathname = record.name.replace(".", "/") + ".py"
        else:
            # For __main__, use actual file path relative to project root
            pathname = os.path.relpath(record.pathname)

        # Create custom format with relative path
        record.custom_pathname = pathname

        # Format the message
        formatted = super().format(record)

        # Add colors if enabled
        if self.use_colors:
            color = LEVEL_COLORS.get(record.levelname, Colors.WHITE)
            formatted = f"{color}{formatted}{Colors.RESET}"

        return formatted


def setup_logging(level: Optional[str] = None, log_file: Optional[str] = None) -> None:
    """
    Setup logging with standardized format.

    Args:
        level: Log level (TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL)
               Defaults to LOG_LEVEL env var or INFO
        log_file: Optional file path to write logs to (in addition to console)
    """
    level = level or os.getenv("LOG_LEVEL", "INFO").upper()

    # Convert string to level constant
    if level == "TRACE":
        level_const = TRACE
    else:
        level_const = getattr(logging, level, logging.INFO)

    # Formatter with colors for console
    console_formatter = PathFormatter(
        "%(asctime)s %(levelname)s > %(custom_pathname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S.%f",
        use_colors=True,
    )

    # Formatter without colors for file
    file_formatter = PathFormatter(
        "%(asctime)s %(levelname)s > %(custom_pathname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S.%f",
        use_colors=False,
    )

    handlers: list[logging.Handler] = []

    # File handler (if specified) - ALWAYS use this
    if log_file:
        # Ensure log directory exists
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(file_formatter)
        handlers.append(file_handler)

    # Console handler - only if stdout is a TTY (interactive terminal)
    # This avoids duplicates when launchd/nohup redirects stdout to the log file
    if sys.stdout.isatty():
        console = logging.StreamHandler()
        console.setFormatter(console_formatter)
        handlers.append(console)

    # Configure root logger
    logging.root.setLevel(level_const)
    logging.root.handlers = handlers
