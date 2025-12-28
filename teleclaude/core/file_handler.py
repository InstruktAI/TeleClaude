"""File upload handling for terminal sessions.

Provides file upload functionality:
- Download files to persistent session storage
- Detect Claude Code and format paths appropriately
- Send file paths to terminal for processing

Extracted as adapter-agnostic utility following voice_message_handler.py pattern.
"""

import re
from pathlib import Path
from typing import Awaitable, Callable, Optional

from instrukt_ai_logging import get_logger

from teleclaude.core import terminal_bridge
from teleclaude.core.db import db
from teleclaude.core.events import FileEventContext
from teleclaude.core.models import MessageMetadata

logger = get_logger(__name__)


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


async def is_claude_code_running(tmux_session_name: str) -> bool:
    """Detect if Claude Code is running in the tmux session.

    Strategy: Check pane title for "claude" keyword

    Args:
        tmux_session_name: Name of tmux session

    Returns:
        True if Claude Code detected, False otherwise
    """
    try:
        output = await terminal_bridge.get_pane_title(tmux_session_name)
        if not output:
            return False

        title_lower = output.lower()
        return "claude" in title_lower

    except Exception as e:
        logger.warning("Failed to detect Claude Code in session %s: %s", tmux_session_name, e)
        return False


async def handle_file(
    session_id: str,
    file_path: str,
    filename: str,
    context: FileEventContext,
    send_feedback: Callable[[str, str, MessageMetadata], Awaitable[Optional[str]]],
) -> None:
    """Handle file upload (adapter-agnostic utility).

    Args:
        session_id: Session ID
        file_path: Path to downloaded file
        filename: Original filename
        context: Typed file event context
        send_feedback: Async function to send user feedback (session_id, message, metadata)
    """
    logger.info("=== FILE HANDLER CALLED ===")
    logger.info("Session ID: %s", session_id[:8])
    logger.info("File path: %s", file_path)
    logger.info("Filename: %s", filename)

    session = await db.get_session(session_id)
    if not session:
        logger.warning("Session %s not found", session_id)
        return

    is_process_running = await terminal_bridge.is_process_running(session.tmux_session_name)

    if not is_process_running:
        await send_feedback(
            session_id,
            f"📎 File upload requires an active process. File saved: {filename}",
            MessageMetadata(),
        )
        return

    # Get output_message_id from Telegram metadata (files come via Telegram regardless of origin)
    telegram_metadata = session.adapter_metadata.telegram if session.adapter_metadata else None
    current_message_id = telegram_metadata.output_message_id if telegram_metadata else None
    if current_message_id is None:
        logger.warning("No output message yet for session %s, polling may have just started", session_id[:8])
        await send_feedback(
            session_id,
            f"⚠️ File upload unavailable - output message not ready yet. File saved: {filename}",
            MessageMetadata(),
        )
        return

    is_claude_running = await is_claude_code_running(session.tmux_session_name)

    # Build input text with absolute file path (remote AIs need full path)
    absolute_path = Path(file_path).resolve()
    if is_claude_running:
        input_text = f"@{absolute_path}"
        logger.info("Claude Code detected - sending file with @ prefix: %s", input_text)
    else:
        input_text = str(absolute_path)
        logger.info("Generic process detected - sending plain path: %s", input_text)

    # Append caption text if present
    if context.caption and context.caption.strip():
        input_text = f"{input_text} {context.caption.strip()}"
        logger.info("Appending caption to file input: %s", context.caption.strip()[:50])

    # Automatic detection: if process running, no marker
    success = await terminal_bridge.send_keys(
        session.tmux_session_name,
        input_text,
        session_id=session_id,
    )

    if not success:
        logger.error("Failed to send file path to session %s", session_id[:8])
        await send_feedback(
            session_id,
            "❌ Failed to send file to terminal",
            MessageMetadata(),
        )
        return

    await db.update_last_activity(session_id)

    # Send feedback with plain text (no Markdown parsing)
    if context.file_size > 0:
        file_size_mb = context.file_size / 1_048_576
        await send_feedback(
            session_id,
            f"📎 File uploaded: {filename} ({file_size_mb:.2f} MB)",
            MessageMetadata(),
        )
    else:
        await send_feedback(
            session_id,
            f"📎 File uploaded: {filename}",
            MessageMetadata(),
        )

    logger.info("File path sent to session %s, existing poll will capture output", session_id[:8])
