"""
Centralized logging configuration for TeleClaude.

Provides standardized log format across all modules:
[2025-10-30 12:05:31.454] INFO > teleclaude/daemon.py: message
"""

import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# Add TRACE level (below DEBUG)
TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def trace(self: logging.Logger, message: str, *args: object, **kwargs: object) -> None:
    """Log trace message."""
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)  # type: ignore[arg-type]  # pylint: disable=protected-access


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

    def __init__(self, *args: object, use_colors: bool = True, **kwargs: object) -> None:
        """Initialize formatter.

        Args:
            use_colors: Whether to use ANSI colors (True for console, False for files)
        """
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.use_colors = use_colors

    def formatTime(self, record: logging.LogRecord, datefmt: Optional[str] = None) -> str:
        """Format time with milliseconds support in UTC."""
        ct = datetime.fromtimestamp(record.created, tz=timezone.utc)
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


def setup_logging(level: Optional[str] = None) -> None:
    """
    Setup logging with standardized format and rotation.

    Args:
        level: Log level (TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL)
               Defaults to LOG_LEVEL env var or INFO
        log_file: Optional file path to write main log to.
                  If not provided, uses logs/teleclaude.log in project root.
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

    # Determine logs directory
    project_root = Path(__file__).parent.parent
    logs_dir = project_root / "logs"
    try:
        logs_dir.mkdir(exist_ok=True)
    except (PermissionError, OSError) as e:
        print(f"Warning: Could not create logs directory {logs_dir}: {e}", file=sys.stderr)
        # Fallback to /tmp if project dir is not writable
        logs_dir = Path(f"/tmp/teleclaude-{os.getpid()}-logs")
        logs_dir.mkdir(exist_ok=True)

    # Configure specific loggers (Actors)
    # Map logger name prefix -> filename
    actor_logs = {
        "teleclaude.daemon": "daemon.log",
        "teleclaude.mcp_server": "mcp_server.log",
        "teleclaude.adapters.telegram_adapter": "telegram.log",
        "teleclaude.adapters.redis_adapter": "redis.log",
        "teleclaude.core": "core.log",
        "teleclaude.mcp_wrapper": "mcp-wrapper.log",
    }

    for logger_name, filename in actor_logs.items():
        actor_logger = logging.getLogger(logger_name)
        # Prevent double logging if handler already exists (e.g. re-import)
        if not any(isinstance(h, RotatingFileHandler) for h in actor_logger.handlers):
            try:
                log_path = logs_dir / filename
                handler = RotatingFileHandler(
                    log_path,
                    maxBytes=1024 * 1024,  # 1MB
                    backupCount=5,
                    encoding="utf-8",
                )
                handler.setFormatter(file_formatter)
                actor_logger.addHandler(handler)
            except (PermissionError, OSError) as e:
                print(
                    f"Warning: Could not set up log for {logger_name}: {e}",
                    file=sys.stderr,
                )

    handlers: list[logging.Handler] = []

    # Main Log File (Root Logger)
    main_log_path = logs_dir / "teleclaude.log"

    try:
        file_handler = RotatingFileHandler(
            main_log_path,
            maxBytes=1024 * 1024,  # 1MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(file_formatter)
        handlers.append(file_handler)
    except (PermissionError, OSError) as e:
        print(f"Warning: Could not write to {main_log_path}: {e}", file=sys.stderr)

    # Console handler - only if stdout is a TTY (interactive terminal)
    if sys.stdout.isatty():  # type: ignore[misc]
        console = logging.StreamHandler()
        console.setFormatter(console_formatter)
        handlers.append(console)

    # Configure root logger
    logging.root.setLevel(level_const)
    # Clear existing handlers to avoid duplicates on reload
    logging.root.handlers = handlers
