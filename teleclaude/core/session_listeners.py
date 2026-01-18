"""Session listeners for PUB-SUB notification on Stop events.

When an AI starts or sends a message to another session, it can register a listener.
When the target session stops, ALL listeners fire and notify their callers via tmux injection.
Listeners are one-shot (removed after firing) and session-scoped (cleaned up when caller exits).

Multiple callers can wait for the same target session (e.g., 4 AI workers waiting for a dependency).
Only one listener per caller-target pair is allowed (deduped by caller, not by target).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from instrukt_ai_logging import get_logger

from teleclaude.constants import LOCAL_COMPUTER

logger = get_logger(__name__)


@dataclass
class SessionListener:
    """A one-shot listener waiting for a target session to stop."""

    target_session_id: str  # Session being listened to
    caller_session_id: str  # Session that wants to be notified
    caller_tmux_session: str  # Tmux session name for injection
    registered_at: datetime


# In-memory storage: target_session_id -> list of listeners
# Multiple callers can wait for the same target
_listeners: dict[str, list[SessionListener]] = {}


def register_listener(
    target_session_id: str,
    caller_session_id: str,
    caller_tmux_session: str,
) -> bool:
    """Register a one-shot listener for a target session's Stop event.

    Multiple callers can register for the same target.
    Only one listener per caller-target pair (deduped by caller_session_id).

    Args:
        target_session_id: The session to listen to
        caller_session_id: The session that wants notification
        caller_tmux_session: Tmux session name for message injection

    Returns:
        True if listener was registered, False if this caller already has one
    """
    if target_session_id not in _listeners:
        _listeners[target_session_id] = []

    # Check if this caller already has a listener for this target
    for existing in _listeners[target_session_id]:
        if existing.caller_session_id == caller_session_id:
            logger.debug(
                "Listener already exists: caller=%s -> target=%s",
                caller_session_id[:8],
                target_session_id[:8],
            )
            return False

    listener = SessionListener(
        target_session_id=target_session_id,
        caller_session_id=caller_session_id,
        caller_tmux_session=caller_tmux_session,
        registered_at=datetime.now(timezone.utc),
    )
    _listeners[target_session_id].append(listener)
    logger.info(
        "Registered listener: caller=%s -> target=%s (total: %d)",
        caller_session_id[:8],
        target_session_id[:8],
        len(_listeners[target_session_id]),
    )
    return True


def unregister_listener(target_session_id: str, caller_session_id: str) -> bool:
    """Unregister a specific listener for a target session.

    Removes the listener registered by a specific caller for a specific target.
    This allows an AI to stop receiving notifications from a session without ending it.

    Args:
        target_session_id: The session to stop listening to
        caller_session_id: The session that wants to unsubscribe

    Returns:
        True if listener was found and removed, False if no such listener exists
    """
    if target_session_id not in _listeners:
        logger.debug(
            "No listeners for target %s",
            target_session_id[:8],
        )
        return False

    # Find and remove the specific caller's listener
    original_len = len(_listeners[target_session_id])
    _listeners[target_session_id] = [
        listener for listener in _listeners[target_session_id] if listener.caller_session_id != caller_session_id
    ]

    # Check if we actually removed one
    if len(_listeners[target_session_id]) == original_len:
        logger.debug(
            "No listener found for caller=%s -> target=%s",
            caller_session_id[:8],
            target_session_id[:8],
        )
        return False

    # Clean up empty target list
    if not _listeners[target_session_id]:
        del _listeners[target_session_id]

    logger.info(
        "Unregistered listener: caller=%s -> target=%s",
        caller_session_id[:8],
        target_session_id[:8],
    )
    return True


def get_listeners(target_session_id: str) -> list[SessionListener]:
    """Get all listeners for a target session."""
    return _listeners.get(target_session_id, []).copy()


def pop_listeners(target_session_id: str) -> list[SessionListener]:
    """Remove and return all listeners for a target session (one-shot pattern).

    Called when target session stops - all callers get notified, then listeners are removed.

    Args:
        target_session_id: The session whose listeners should be removed

    Returns:
        List of removed listeners (may be empty)
    """
    listeners = _listeners.pop(target_session_id, [])
    if listeners:
        logger.info(
            "Popped %d listener(s) for target %s",
            len(listeners),
            target_session_id[:8],
        )
    return listeners


def cleanup_caller_listeners(caller_session_id: str) -> int:
    """Remove all listeners registered by a specific caller session.

    Called when a caller session ends to clean up its listeners.

    Args:
        caller_session_id: The session whose listeners should be removed

    Returns:
        Number of listeners removed
    """
    count = 0
    empty_targets = []

    for target_id, listeners in _listeners.items():
        original_len = len(listeners)
        _listeners[target_id] = [listener for listener in listeners if listener.caller_session_id != caller_session_id]
        removed = original_len - len(_listeners[target_id])
        count += removed

        # Mark empty lists for cleanup
        if not _listeners[target_id]:
            empty_targets.append(target_id)

    # Remove empty target entries
    for target_id in empty_targets:
        del _listeners[target_id]

    if count:
        logger.info(
            "Cleaned up %d listener(s) for caller session %s",
            count,
            caller_session_id[:8],
        )
    return count


def get_all_listeners() -> dict[str, list[SessionListener]]:
    """Get all active listeners (for debugging/monitoring)."""
    return {k: v.copy() for k, v in _listeners.items()}


def get_listeners_for_caller(caller_session_id: str) -> list[SessionListener]:
    """Get all listeners registered by a specific caller."""
    result = []
    for listeners in _listeners.values():
        for listener in listeners:
            if listener.caller_session_id == caller_session_id:
                result.append(listener)
    return result


def count_listeners() -> int:
    """Get total number of active listeners."""
    return sum(len(listeners) for listeners in _listeners.values())


def get_stale_targets(max_age_minutes: int = 10) -> list[str]:
    """Get target session IDs with listeners older than max_age_minutes.

    Returns unique target session IDs where at least one listener has been
    waiting longer than the threshold. Used for periodic health checks.

    After returning, the listener's registered_at is reset to prevent
    repeated health checks every minute.

    Args:
        max_age_minutes: Maximum age in minutes before a listener is considered stale

    Returns:
        List of target session IDs that need health checks
    """
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(minutes=max_age_minutes)
    stale_targets: list[str] = []

    for target_id, listeners in _listeners.items():
        for listener in listeners:
            if listener.registered_at < threshold:
                stale_targets.append(target_id)
                # Reset timestamp to prevent repeated checks every minute
                listener.registered_at = now
                break  # Only need one stale listener per target

    if stale_targets:
        logger.info("Found %d stale target(s) for health check", len(stale_targets))

    return stale_targets


async def _notify_listeners(target_session_id: str, message: str) -> int:
    """Internal: notify all listeners with a pre-built message.

    Args:
        target_session_id: Session whose listeners to notify
        message: The notification message to send

    Returns:
        Number of listeners successfully notified
    """
    from teleclaude.core.tmux_delivery import deliver_listener_message

    listeners = get_listeners(target_session_id)
    if not listeners:
        logger.debug("No listeners for session %s", target_session_id[:8])
        return 0

    success_count = 0
    for listener in listeners:
        delivered = await deliver_listener_message(
            listener.caller_session_id,
            listener.caller_tmux_session,
            message,
        )
        if delivered:
            logger.info("Notified caller %s", listener.caller_session_id[:8])
            success_count += 1
        else:
            logger.warning("Failed to notify caller %s", listener.caller_session_id[:8])

    return success_count


async def notify_stop(
    target_session_id: str,
    computer: str,
    title: str | None = None,
) -> int:
    """Notify listeners that a session finished its turn.

    Args:
        target_session_id: Session that finished
        computer: Computer name where session runs (for actionable command)
        title: Optional title/summary of the turn

    Returns:
        Number of listeners successfully notified
    """
    title_part = f' "{title}"' if title else ""
    location_part = f" on {computer}" if computer != LOCAL_COMPUTER else ""
    message = (
        f"Session {target_session_id[:8]}{location_part}{title_part} finished its turn. "
        f"Use teleclaude__get_session_data(computer='{computer}', "
        f"session_id='{target_session_id}') to inspect."
    )
    return await _notify_listeners(target_session_id, message)


async def notify_input_request(
    target_session_id: str,
    computer: str,
    input_message: str,
) -> int:
    """Notify listeners that a session needs input.

    Args:
        target_session_id: Session that needs input
        computer: Computer name where session runs (for actionable command)
        input_message: The input request message from the session

    Returns:
        Number of listeners successfully notified
    """
    message = (
        f"Session {target_session_id[:8]} on {computer} needs input: {input_message} "
        f"Use teleclaude__send_message(computer='{computer}', session_id='{target_session_id}', "
        f"message='your response') to respond."
    )
    return await _notify_listeners(target_session_id, message)
