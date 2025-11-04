"""Daemon runtime state management.

Module-level state for tracking active polling, exit markers, notifications, and message cleanup.
State is shared across the daemon process - direct access without class wrapper.
"""

from typing import List, Optional

# Module-level state (singleton by nature of Python modules)
_active_polling_sessions: set[str] = set()
_exit_markers: dict[str, bool] = {}
_idle_notifications: dict[str, str] = {}
_pending_deletions: dict[str, list[str]] = {}  # session_id -> list of message IDs to delete


# Polling state management
def is_polling(session_id: str) -> bool:
    """Check if session has active polling.

    Args:
        session_id: Session identifier

    Returns:
        True if polling is active for this session
    """
    return session_id in _active_polling_sessions


def mark_polling(session_id: str) -> None:
    """Mark session as having active polling.

    Args:
        session_id: Session identifier
    """
    _active_polling_sessions.add(session_id)


def unmark_polling(session_id: str) -> None:
    """Mark session as no longer polling.

    Args:
        session_id: Session identifier
    """
    _active_polling_sessions.discard(session_id)


# Exit marker management
def has_exit_marker(session_id: str) -> bool:
    """Check if exit marker status is set for session.

    Args:
        session_id: Session identifier

    Returns:
        True if exit marker tracking exists for this session
    """
    return session_id in _exit_markers


def get_exit_marker(session_id: str, default: Optional[bool] = None) -> Optional[bool]:
    """Get exit marker status for session.

    Args:
        session_id: Session identifier
        default: Default value if not found

    Returns:
        True if exit marker was appended, False if not, default if not tracked
    """
    return _exit_markers.get(session_id, default)


def set_exit_marker(session_id: str, appended: bool) -> None:
    """Set exit marker status for session.

    Args:
        session_id: Session identifier
        appended: Whether exit marker was appended to command
    """
    _exit_markers[session_id] = appended


def remove_exit_marker(session_id: str) -> None:
    """Remove exit marker tracking for session.

    Args:
        session_id: Session identifier
    """
    _exit_markers.pop(session_id, None)


# Idle notification management
def has_idle_notification(session_id: str) -> bool:
    """Check if session has idle notification.

    Args:
        session_id: Session identifier

    Returns:
        True if idle notification exists for this session
    """
    return session_id in _idle_notifications


def get_idle_notification(session_id: str) -> Optional[str]:
    """Get idle notification message ID for session.

    Args:
        session_id: Session identifier

    Returns:
        Message ID of idle notification, or None if not set
    """
    return _idle_notifications.get(session_id)


def set_idle_notification(session_id: str, message_id: str) -> None:
    """Set idle notification message ID for session.

    Args:
        session_id: Session identifier
        message_id: Message ID of the idle notification
    """
    _idle_notifications[session_id] = message_id


def remove_idle_notification(session_id: str) -> Optional[str]:
    """Remove and return idle notification message ID for session.

    Args:
        session_id: Session identifier

    Returns:
        Message ID that was removed, or None if not set
    """
    return _idle_notifications.pop(session_id, None)


# Pending deletion management (for message cleanup during active processes)
def add_pending_deletion(session_id: str, message_id: str) -> None:
    """Add message ID to pending deletions for session.

    When a process is running and messages are sent (user commands, feedback messages),
    these message IDs are tracked for deletion when the next accepted input is sent.

    Args:
        session_id: Session identifier
        message_id: Message ID to delete later
    """
    if session_id not in _pending_deletions:
        _pending_deletions[session_id] = []
    _pending_deletions[session_id].append(message_id)


def get_pending_deletions(session_id: str) -> List[str]:
    """Get list of pending deletion message IDs for session.

    Args:
        session_id: Session identifier

    Returns:
        List of message IDs to delete (empty list if none)
    """
    return _pending_deletions.get(session_id, [])


def clear_pending_deletions(session_id: str) -> None:
    """Clear all pending deletions for session.

    Should be called after deleting all pending messages, or when polling stops.

    Args:
        session_id: Session identifier
    """
    _pending_deletions.pop(session_id, None)
