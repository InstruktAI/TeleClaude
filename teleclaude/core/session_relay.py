"""Session relay — monitors participant output and delivers it to peers.

Given a list of participant sessions, monitors each session's tmux output
via capture_pane and relays new content (delta beyond baseline) to all other
participants with attribution. Supports N participants for 1:1 and future
gathering use.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge

logger = get_logger(__name__)

POLL_INTERVAL_SECONDS = 1.0


@dataclass
class RelayParticipant:
    """A session participating in a relay."""

    session_id: str
    tmux_session_name: str
    name: str
    number: int


@dataclass
class SessionRelay:
    """An active relay between participant sessions."""

    relay_id: str
    participants: list[RelayParticipant]
    baselines: dict[str, str] = field(default_factory=dict)
    active: bool = True
    _monitor_tasks: dict[str, asyncio.Task[None]] = field(init=False, default_factory=dict, repr=False)


# Module-level state — same pattern as polling_coordinator._active_pollers
_relays: dict[str, SessionRelay] = {}
_relay_by_session: dict[str, str] = {}  # session_id -> relay_id (for lookup)
_relay_lock = asyncio.Lock()


async def create_relay(participants: list[RelayParticipant]) -> str:
    """Create a relay between participants and start monitoring.

    Initializes baseline snapshots for each participant's pane, then
    starts async monitor tasks that poll for output changes.

    Returns:
        The relay_id for the new relay.
    """
    relay_id = str(uuid.uuid4())
    relay = SessionRelay(relay_id=relay_id, participants=participants)

    # Initialize baselines from current pane content
    for p in participants:
        relay.baselines[p.session_id] = await tmux_bridge.capture_pane(p.tmux_session_name)

    async with _relay_lock:
        # Prevent enrolling sessions already in another relay
        for p in participants:
            if p.session_id in _relay_by_session:
                existing_relay_id = _relay_by_session[p.session_id]
                raise ValueError(f"Session {p.session_id[:8]} already in relay {existing_relay_id[:8]}")
        _relays[relay_id] = relay
        for p in participants:
            _relay_by_session[p.session_id] = relay_id

    # Start monitor tasks for each participant
    for p in participants:
        task = asyncio.create_task(
            _monitor_output(relay, p),
            name=f"relay-monitor-{relay_id[:8]}-{p.session_id[:8]}",
        )
        relay._monitor_tasks[p.session_id] = task

    participant_names = ", ".join(f"{p.name} ({p.number})" for p in participants)
    logger.info(
        "Relay %s started with %d participants: %s",
        relay_id[:8],
        len(participants),
        participant_names,
    )
    return relay_id


async def stop_relay(relay_id: str) -> bool:
    """Stop a relay and cancel all monitor tasks.

    Returns:
        True if the relay was found and stopped, False if not found.
    """
    async with _relay_lock:
        relay = _relays.pop(relay_id, None)
        if relay is None:
            return False
        relay.active = False
        for p in relay.participants:
            _relay_by_session.pop(p.session_id, None)

    # Cancel monitor tasks outside the lock
    for task in relay._monitor_tasks.values():
        task.cancel()
    for task in relay._monitor_tasks.values():
        try:
            await task
        except asyncio.CancelledError:
            pass

    logger.info("Relay %s stopped", relay_id[:8])
    return True


async def get_relay_for_session(session_id: str) -> str | None:
    """Look up relay_id by participant session_id."""
    async with _relay_lock:
        return _relay_by_session.get(session_id)


async def get_relay(relay_id: str) -> SessionRelay | None:
    """Get a relay by ID."""
    async with _relay_lock:
        return _relays.get(relay_id)


async def _monitor_output(relay: SessionRelay, participant: RelayParticipant) -> None:
    """Poll a participant's tmux pane and relay new output to peers.

    Runs as a background asyncio task. Exits when the relay is deactivated
    or the tmux session disappears (indicating the agent exited).
    """
    session_id = participant.session_id
    tmux_name = participant.tmux_session_name

    while relay.active:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        if not relay.active:
            break

        try:
            current = await tmux_bridge.capture_pane(tmux_name)
        except Exception:
            # Session likely gone — clean up the relay
            logger.info(
                "Relay %s: session %s pane capture failed, stopping relay",
                relay.relay_id[:8],
                session_id[:8],
            )
            await stop_relay(relay.relay_id)
            return

        if not current:
            # Empty capture means session ended
            logger.info(
                "Relay %s: session %s returned empty pane, stopping relay",
                relay.relay_id[:8],
                session_id[:8],
            )
            await stop_relay(relay.relay_id)
            return

        baseline = relay.baselines.get(session_id, "")
        delta = _compute_delta(baseline, current)

        if delta.strip():
            await _fanout(relay, participant, delta)
            # Update baseline to include everything up to now
            relay.baselines[session_id] = current


def _compute_delta(baseline: str, current: str) -> str:
    """Compute new content beyond the baseline.

    Simple suffix-based diffing: if current starts with (or contains)
    the baseline, the delta is the remaining content. Falls back to
    returning all of current if baseline is not a prefix.
    """
    if not baseline:
        return current

    # Find where current diverges from baseline
    # The baseline should be a prefix of current (since pane content grows)
    if current.startswith(baseline):
        return current[len(baseline) :]

    # Baseline may have been trimmed by scrollback — find overlap
    # Use the last N chars of baseline as an anchor
    anchor_len = min(200, len(baseline))
    anchor = baseline[-anchor_len:]
    pos = current.find(anchor)
    if pos >= 0:
        return current[pos + len(anchor) :]

    # No overlap found — baseline drifted too far. Return empty to avoid
    # re-delivering old content. The next cycle with updated baseline
    # will pick up new content.
    return ""


async def _fanout(relay: SessionRelay, sender: RelayParticipant, delta: str) -> None:
    """Deliver delta content to all participants except the sender.

    Formats with attribution and injects via send_keys into each
    recipient's tmux session. Updates recipient baselines after injection
    to prevent feedback loops.
    """
    attributed = f"[{sender.name}] ({sender.number}):\n\n{delta.strip()}\n"

    for recipient in relay.participants:
        if recipient.session_id == sender.session_id:
            continue

        success = await tmux_bridge.send_keys_existing_tmux(
            session_name=recipient.tmux_session_name,
            text=attributed,
            send_enter=False,
        )

        if success:
            # Update recipient baseline to include the injected content
            # so it won't be re-captured as "new output" from the recipient
            try:
                new_baseline = await tmux_bridge.capture_pane(recipient.tmux_session_name)
                relay.baselines[recipient.session_id] = new_baseline
            except Exception:
                logger.warning(
                    "Relay %s: failed to update baseline for %s after injection",
                    relay.relay_id[:8],
                    recipient.session_id[:8],
                )
        else:
            logger.warning(
                "Relay %s: failed to deliver to %s, stopping relay",
                relay.relay_id[:8],
                recipient.session_id[:8],
            )
            await stop_relay(relay.relay_id)
            return
