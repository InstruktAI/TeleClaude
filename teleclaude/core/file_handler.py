"""File upload handling for sessions.

A file reaches a session as ordinary input: the uploaded file's absolute path, as the file
mention an agent understands, followed by the sender's caption. The command handler accepts
that text through the durable inbound queue, which owns when it is delivered.
"""

import re
from pathlib import Path

from teleclaude.core.models import Session

_AGENT_FILE_MENTION_PREFIX = "@"


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal and special characters.

    Args:
        filename: Original filename from upload

    Returns:
        Safe filename with only alphanumeric, dash, underscore, and dot
    """
    safe = re.sub(r"[^\w\-.]", "_", filename)
    safe = safe.strip("._")
    return safe if safe else "file"


def format_file_input(session: Session, file_path: str, caption: str | None) -> str:
    """The input text an uploaded file becomes for a session.

    The absolute path is mentioned as an agent's file reference when the session runs an agent
    and as a plain path otherwise. A caption follows it.
    """
    absolute_path = Path(file_path).resolve()
    input_text = f"{_AGENT_FILE_MENTION_PREFIX}{absolute_path}" if session.active_agent else str(absolute_path)
    if caption and caption.strip():
        return f"{input_text} {caption.strip()}"
    return input_text
