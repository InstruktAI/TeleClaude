"""Session listeners for PUB-SUB notification on Stop events.

When an AI starts or sends a message to another session, it can register a listener.
When the target session stops, ALL listeners fire and notify their callers via tmux injection.
Listeners are one-shot (removed after firing) and session-scoped (cleaned up when caller exits).

Multiple callers can wait for the same target session (e.g., 4 AI workers waiting for a dependency).
Only one listener per caller-target pair is allowed (deduped by caller, not by target).

Storage is SQLite-backed so listeners survive daemon restarts.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Literal
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.config._models import AGENT_NO_SIGNAL_TIMEOUT_S, AGENT_NO_START_TIMEOUT_S
from teleclaude.constants import LOCAL_COMPUTER
from teleclaude.core.control_delivery import handoff_control_payload
from teleclaude.core.db import db
from teleclaude.core.db_models import ConversationLinkMode
from teleclaude.core.events import AgentAttentionObservation
from teleclaude.core.inbound_errors import SessionMessageRejectedError
from teleclaude.core.injected_text import EnvelopeName, occurrence_fields, semantic_envelope
from teleclaude.core.models import CleanupTrigger, MessageMetadata
from teleclaude.core.session_status import AgentStatusReason, is_session_terminal

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

# Actor name stamped on daemon-injected runner notifications.
NOTIFY_ACTOR_NAME = "system"

# Turn-completion notification copy. Inspect notices name the session in the
# command; NOOP notices name it in the sentence because they have no command.
_STOP_NOTIFICATION_TEMPLATE = "Session{location_part}{title_part} finished its turn. Use telec sessions tail {target_session_id}{computer_selector} to inspect."
_STOP_NOTIFICATION_NOOP_TEMPLATE = (
    "Session{location_part}{title_part} (id {target_session_id}) ended its turn with NOOP."
)
_STOP_NOTIFICATION_TITLE_TEMPLATE = ' "{title}"'
_STOP_NOTIFICATION_LOCATION_TEMPLATE = " on {computer}"
_STOP_NOTIFICATION_COMPUTER_SELECTOR_TEMPLATE = " --computer {computer}"
_STOP_NOTIFICATION_NO_PART = ""
_BLOCKED_NOTIFICATION_TEMPLATE = "Session{location_part}{title_part} is waiting for approval or input. Use telec sessions tail {target_session_id}{computer_selector} to inspect."
_FAILED_NOTIFICATION_TEMPLATE = "Session{location_part}{title_part} failed its turn. Use telec sessions tail {target_session_id}{computer_selector} to inspect."
_PARENT_BLOCKED_NOTIFICATION_TEMPLATE = (
    "Session{location_part}{title_part} is waiting for approval or input. Native evidence: {evidence}. "
    "Assess its current state and recover within your mandate. "
    "Use telec sessions tail {target_session_id} --pane{computer_selector} to inspect."
)
_PARENT_FAILED_NOTIFICATION_TEMPLATE = (
    "Session{location_part}{title_part} failed its turn. Native evidence: {evidence}. "
    "Assess its current state and recover within your mandate. "
    "Use telec sessions tail {target_session_id} --pane{computer_selector} to inspect."
)
_PARENT_INFERRED_STALL_NOTIFICATION_TEMPLATE = (
    "Session{location_part}{title_part} stalled. Evidence: {evidence}. "
    "Assess its current state and recover within your mandate. "
    "Use telec sessions tail {target_session_id} --pane{computer_selector} to inspect."
)
_INFERRED_STALL_HUMAN_NOTIFICATION_TEMPLATE = (
    "Session{location_part}{title_part} stalled: {evidence}. "
    "Use telec sessions tail {target_session_id}{computer_selector} to inspect."
)
_PARENT_DELIVERY_BLOCK_NOTIFICATION_TEMPLATE = (
    "Session{location_part}{title_part} shows a screen other than its composer while input waits. "
    "Evidence: {evidence}. "
    "Assess its current state and recover within your mandate. "
    "Use telec sessions tail {target_session_id} --pane{computer_selector} to inspect."
)
_DELIVERY_BLOCK_HUMAN_NOTIFICATION_TEMPLATE = (
    "Session{location_part}{title_part} shows a screen other than its composer while input waits: {evidence}. "
    "Use telec sessions tail {target_session_id}{computer_selector} to inspect."
)
_ATTENTION_EVIDENCE_PROVIDER_KEY = "provider"
_ATTENTION_EVIDENCE_NATIVE_EVENT_KEY = "native_event"
_ATTENTION_EVIDENCE_DETAILS_KEY = "details"
_ATTENTION_EVIDENCE_OBSERVED_AT_KEY = "observed_at"
_ATTENTION_EVIDENCE_INGRESS_ID_KEY = "ingress_id"
_ATTENTION_EVIDENCE_UNAVAILABLE = "unavailable"
INFERRED_STALL_EVIDENCE_METADATA_KEY: Final[Literal["inferred_stall_evidence"]] = "inferred_stall_evidence"
INFERRED_STALL_REASON_FIELD = "reason"
INFERRED_STALL_PANE_TAIL_FIELD = "pane_tail"
_INFERRED_STALL_NO_SIGNAL_TEMPLATE = "gave no agent activity for {timeout}"
_INFERRED_STALL_NO_START_TEMPLATE = "did not start within {timeout}\nPane last lines:\n{pane_tail}"
DELIVERY_BLOCK_EVIDENCE_METADATA_KEY: Final[Literal["delivery_block_evidence"]] = "delivery_block_evidence"
DELIVERY_BLOCK_PANE_TAIL_FIELD = "pane_tail"
_DELIVERY_BLOCK_PANE_TEMPLATE = "Pane last lines:\n{pane_tail}"
_INFERRED_STALL_REASON_REQUIRED_ERROR = "Inferred stall evidence requires a watchdog reason"
_INFERRED_STALL_TIMEOUTS: dict[AgentStatusReason, str] = {
    AgentStatusReason.NO_SIGNAL: f"{AGENT_NO_SIGNAL_TIMEOUT_S // 60}m",
    AgentStatusReason.NO_START: f"{AGENT_NO_START_TIMEOUT_S}s",
}
_NOTIFY_LISTENERS_LOG = "Notify listeners: target=%s callers=%s kind=%s"


@dataclass
class SessionListener:
    """A listener waiting for a target session to stop."""

    target_session_id: str  # Session being listened to
    caller_session_id: str  # Session that wants to be notified
    caller_tmux_session: str  # Tmux session name for injection
    registered_at: datetime
    one_shot: bool = False  # Remove after first fire


@dataclass(frozen=True)
class NotificationLocality:
    """One locality decision for notification prose and its actionable command."""

    location_part: str
    computer_selector: str


class NotificationKind(StrEnum):
    """Caller-facing session notification kinds."""

    TURN_END = "turn_end"
    BLOCKED = "blocked"
    TURN_FAILED = "turn_failed"


@dataclass(frozen=True)
class InferredStallEvidence:
    """Daemon-observed liveness evidence replacing a native attention payload."""

    reason: AgentStatusReason
    timeout: str
    pane_tail: str | None = None


def build_inferred_stall_evidence(
    reason: AgentStatusReason,
    pane_tail: str | None = None,
) -> InferredStallEvidence:
    """Build local evidence with the timeout contract for an inferred stall."""
    timeout = _INFERRED_STALL_TIMEOUTS.get(reason)
    if timeout is None:
        raise ValueError(_INFERRED_STALL_REASON_REQUIRED_ERROR)
    return InferredStallEvidence(reason=reason, timeout=timeout, pane_tail=pane_tail)


def _inferred_stall_summary(evidence: InferredStallEvidence) -> str:
    """Render the configured timeout and optional startup pane evidence."""
    if evidence.reason is AgentStatusReason.NO_SIGNAL:
        return _INFERRED_STALL_NO_SIGNAL_TEMPLATE.format(timeout=evidence.timeout)
    pane_tail = evidence.pane_tail or _ATTENTION_EVIDENCE_UNAVAILABLE
    return _INFERRED_STALL_NO_START_TEMPLATE.format(timeout=evidence.timeout, pane_tail=pane_tail)


@dataclass(frozen=True)
class DeliveryBlockEvidence:
    """Daemon-observed capture of the screen input delivery found in place of the composer."""

    pane_tail: str


def _delivery_block_summary(evidence: DeliveryBlockEvidence) -> str:
    """Render the captured screen as labelled data."""
    return _DELIVERY_BLOCK_PANE_TEMPLATE.format(pane_tail=evidence.pane_tail or _ATTENTION_EVIDENCE_UNAVAILABLE)


class StopNotificationVariant(StrEnum):
    """Caller-facing stop notice variants."""

    INSPECT = "inspect"
    NOOP = "noop"


async def register_listener(
    target_session_id: str,
    caller_session_id: str,
    caller_tmux_session: str,
    one_shot: bool = False,
) -> bool:
    """Register a listener for a target session's Stop event.

    Multiple callers can register for the same target.
    Only one listener per caller-target pair (deduped by caller_session_id).

    Args:
        target_session_id: The session to listen to
        caller_session_id: The session that wants notification
        caller_tmux_session: Tmux session name for message injection

    Returns:
        True if listener was newly registered, False if this caller already has one
    """
    is_new = await db.register_listener(
        target_session_id=target_session_id,
        caller_session_id=caller_session_id,
        caller_tmux_session=caller_tmux_session,
        one_shot=one_shot,
    )

    if is_new:
        listeners = await db.get_listeners_for_target(target_session_id)
        logger.info(
            "Registered listener: caller=%s -> target=%s (total: %d)",
            caller_session_id,
            target_session_id,
            len(listeners),
        )
        logger.debug(
            "Listener map snapshot: target=%s callers=%s",
            target_session_id,
            ",".join(row.caller_session_id for row in listeners),
        )
    else:
        logger.debug(
            "Listener already exists: caller=%s -> target=%s",
            caller_session_id,
            target_session_id,
        )

    return is_new


async def unregister_listener(target_session_id: str, caller_session_id: str) -> bool:
    """Unregister a specific listener for a target session.

    Removes the listener registered by a specific caller for a specific target.
    This allows an AI to stop receiving notifications from a session without ending it.

    Args:
        target_session_id: The session to stop listening to
        caller_session_id: The session that wants to unsubscribe

    Returns:
        True if listener was found and removed, False if no such listener exists
    """
    removed = await db.unregister_listener(target_session_id, caller_session_id)
    if removed:
        logger.info(
            "Unregistered listener: caller=%s -> target=%s",
            caller_session_id,
            target_session_id,
        )
    else:
        logger.debug(
            "No listener found for caller=%s -> target=%s",
            caller_session_id,
            target_session_id,
        )
    return removed


async def get_listeners(target_session_id: str) -> list[SessionListener]:
    """Get all listeners for a target session."""
    rows = await db.get_listeners_for_target(target_session_id)
    return [
        SessionListener(
            target_session_id=row.target_session_id,
            caller_session_id=row.caller_session_id,
            caller_tmux_session=row.caller_tmux_session,
            registered_at=datetime.fromisoformat(row.registered_at),
            one_shot=row.one_shot,
        )
        for row in rows
    ]


async def pop_listeners(target_session_id: str) -> list[SessionListener]:
    """Remove and return all listeners for a target session (one-shot pattern).

    Called when target session stops - all callers get notified, then listeners are removed.

    Args:
        target_session_id: The session whose listeners should be removed

    Returns:
        List of removed listeners (may be empty)
    """
    rows = await db.pop_listeners_for_target(target_session_id)
    listeners = [
        SessionListener(
            target_session_id=row.target_session_id,
            caller_session_id=row.caller_session_id,
            caller_tmux_session=row.caller_tmux_session,
            registered_at=datetime.fromisoformat(row.registered_at),
            one_shot=row.one_shot,
        )
        for row in rows
    ]
    if listeners:
        logger.info(
            "Popped %d listener(s) for target %s",
            len(listeners),
            target_session_id,
        )
    else:
        logger.debug("Pop listeners: none for target %s", target_session_id)
    return listeners


async def cleanup_caller_listeners(caller_session_id: str) -> int:
    """Remove all listeners registered by a specific caller session.

    Called when a caller session ends to clean up its listeners.

    Args:
        caller_session_id: The session whose listeners should be removed

    Returns:
        Number of listeners removed
    """
    count = await db.cleanup_caller_listeners(caller_session_id)
    if count:
        logger.info(
            "Cleaned up %d listener(s) for caller session %s",
            count,
            caller_session_id,
        )
    return count


async def get_all_listeners() -> dict[str, list[SessionListener]]:
    """Get all active listeners (for debugging/monitoring)."""
    rows = await db.get_all_listeners()
    result: dict[str, list[SessionListener]] = {}
    for row in rows:
        listener = SessionListener(
            target_session_id=row.target_session_id,
            caller_session_id=row.caller_session_id,
            caller_tmux_session=row.caller_tmux_session,
            registered_at=datetime.fromisoformat(row.registered_at),
            one_shot=row.one_shot,
        )
        result.setdefault(row.target_session_id, []).append(listener)
    return result


async def get_listeners_for_caller(caller_session_id: str) -> list[SessionListener]:
    """Get all listeners registered by a specific caller."""
    rows = await db.get_listeners_for_caller(caller_session_id)
    return [
        SessionListener(
            target_session_id=row.target_session_id,
            caller_session_id=row.caller_session_id,
            caller_tmux_session=row.caller_tmux_session,
            registered_at=datetime.fromisoformat(row.registered_at),
            one_shot=row.one_shot,
        )
        for row in rows
    ]


async def count_listeners() -> int:
    """Get total number of active listeners."""
    return await db.count_listeners()


async def get_stale_targets(max_age_minutes: int = 10) -> list[str]:
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
    threshold = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
    threshold_iso = threshold.isoformat()
    now_iso = datetime.now(UTC).isoformat()

    stale_targets = await db.get_stale_listener_targets(threshold_iso)

    if stale_targets:
        logger.info("Found %d stale target(s) for health check", len(stale_targets))
        # Reset timestamps to prevent repeated checks
        for target_id in stale_targets:
            await db.reset_listener_timestamps(target_id, now_iso)

    return stale_targets


async def _notify_listeners(
    target_session_id: str,
    message: str,
    *,
    occurrence_key: str,
    notification_kind: NotificationKind,
    occurred_at: datetime | None,
) -> set[str]:
    """Internal: notify all listeners with a pre-built message.

    Args:
        target_session_id: Session whose listeners to notify
        message: The notification message to send

    Returns:
        Number of listeners successfully notified
    """
    listeners = await get_listeners(target_session_id)
    if not listeners:
        logger.debug("No listeners for session %s", target_session_id)
        return set()

    logger.debug(
        _NOTIFY_LISTENERS_LOG,
        target_session_id,
        ",".join(listener.caller_session_id for listener in listeners),
        notification_kind,
    )
    reached: set[str] = set()
    for listener in listeners:
        if notification_kind is not NotificationKind.TURN_END and listener.one_shot:
            continue
        # Suppress delivery while the caller holds an active direct link with the
        # target. The active-conversation channel supersedes passive notification
        # for the duration of the link. The listener row is preserved — delivery
        # resumes on the next event after the link is severed. See
        # local/projects/teleclaude/spec/session-subscriptions.
        active_link = await db.get_active_link_between_sessions(
            listener.caller_session_id,
            target_session_id,
            mode=ConversationLinkMode.DIRECT,
        )
        if notification_kind is NotificationKind.TURN_END and active_link is not None:
            logger.debug(
                "Suppressing listener notify: caller=%s target=%s (active direct link %s)",
                listener.caller_session_id,
                target_session_id,
                active_link.link_id,
            )
            continue

        try:
            await handoff_control_payload(
                session_id=listener.caller_session_id,
                body=message,
                source_key=f"listener:{target_session_id}:{listener.caller_session_id}:{occurrence_key}",
                envelope=semantic_envelope(
                    EnvelopeName.NOTIFICATION, fields=occurrence_fields(occurred_at), body=message
                ),
            )
            logger.info("Notified caller %s", listener.caller_session_id)
            reached.add(listener.caller_session_id)
        except SessionMessageRejectedError:
            logger.warning("Failed to notify caller %s", listener.caller_session_id)
        if notification_kind is NotificationKind.TURN_END and listener.one_shot:
            await db.unregister_listener(
                target_session_id=target_session_id,
                caller_session_id=listener.caller_session_id,
            )
            logger.debug(
                "One-shot listener removed: caller=%s target=%s", listener.caller_session_id, target_session_id
            )

    return reached


def _notification_locality(computer: str) -> NotificationLocality:
    """Resolve the matching locality phrase and command selector once."""
    if computer == LOCAL_COMPUTER:
        return NotificationLocality(_STOP_NOTIFICATION_NO_PART, _STOP_NOTIFICATION_NO_PART)
    return NotificationLocality(
        _STOP_NOTIFICATION_LOCATION_TEMPLATE.format(computer=computer),
        _STOP_NOTIFICATION_COMPUTER_SELECTOR_TEMPLATE.format(computer=computer),
    )


def _stop_notification_message(
    target_session_id: str,
    computer: str,
    title: str | None,
    variant: StopNotificationVariant,
) -> str:
    title_part = _STOP_NOTIFICATION_TITLE_TEMPLATE.format(title=title) if title else _STOP_NOTIFICATION_NO_PART
    locality = _notification_locality(computer)
    template = (
        _STOP_NOTIFICATION_NOOP_TEMPLATE if variant is StopNotificationVariant.NOOP else _STOP_NOTIFICATION_TEMPLATE
    )
    body = template.format(
        location_part=locality.location_part,
        title_part=title_part,
        target_session_id=target_session_id,
        computer_selector=locality.computer_selector,
    )
    return body


def _distress_notification_message(
    target_session_id: str,
    computer: str,
    title: str | None,
    notification_kind: NotificationKind,
    inferred_stall_evidence: InferredStallEvidence | None = None,
    delivery_block_evidence: DeliveryBlockEvidence | None = None,
) -> str:
    title_part = _STOP_NOTIFICATION_TITLE_TEMPLATE.format(title=title) if title else _STOP_NOTIFICATION_NO_PART
    locality = _notification_locality(computer)
    if inferred_stall_evidence is not None:
        template = _INFERRED_STALL_HUMAN_NOTIFICATION_TEMPLATE
        evidence = _inferred_stall_summary(inferred_stall_evidence)
    elif delivery_block_evidence is not None:
        template = _DELIVERY_BLOCK_HUMAN_NOTIFICATION_TEMPLATE
        evidence = _delivery_block_summary(delivery_block_evidence)
    else:
        template = (
            _BLOCKED_NOTIFICATION_TEMPLATE
            if notification_kind is NotificationKind.BLOCKED
            else _FAILED_NOTIFICATION_TEMPLATE
        )
        evidence = _ATTENTION_EVIDENCE_UNAVAILABLE
    return template.format(
        location_part=locality.location_part,
        title_part=title_part,
        target_session_id=target_session_id,
        computer_selector=locality.computer_selector,
        evidence=evidence,
    )


def _attention_evidence(observation: AgentAttentionObservation | None) -> str:
    """Render native provider evidence as labelled data, never as instructions."""
    if observation is None:
        return _ATTENTION_EVIDENCE_UNAVAILABLE
    return json.dumps(
        {
            _ATTENTION_EVIDENCE_PROVIDER_KEY: observation.provider,
            _ATTENTION_EVIDENCE_NATIVE_EVENT_KEY: observation.native_event,
            _ATTENTION_EVIDENCE_DETAILS_KEY: dict(observation.details),
            _ATTENTION_EVIDENCE_OBSERVED_AT_KEY: observation.observed_at.isoformat()
            if observation.observed_at
            else None,
            _ATTENTION_EVIDENCE_INGRESS_ID_KEY: observation.ingress_id,
        },
        sort_keys=True,
    )


def _parent_attention_message(
    target_session_id: str,
    computer: str,
    title: str | None,
    notification_kind: NotificationKind,
    observation: AgentAttentionObservation | None,
    inferred_stall_evidence: InferredStallEvidence | None = None,
    delivery_block_evidence: DeliveryBlockEvidence | None = None,
) -> str:
    """Format parent-only guidance around labelled native or daemon-observed evidence."""
    title_part = _STOP_NOTIFICATION_TITLE_TEMPLATE.format(title=title) if title else _STOP_NOTIFICATION_NO_PART
    locality = _notification_locality(computer)
    if inferred_stall_evidence is not None:
        template = _PARENT_INFERRED_STALL_NOTIFICATION_TEMPLATE
        evidence = _inferred_stall_summary(inferred_stall_evidence)
    elif delivery_block_evidence is not None:
        template = _PARENT_DELIVERY_BLOCK_NOTIFICATION_TEMPLATE
        evidence = _delivery_block_summary(delivery_block_evidence)
    else:
        template = (
            _PARENT_BLOCKED_NOTIFICATION_TEMPLATE
            if notification_kind is NotificationKind.BLOCKED
            else _PARENT_FAILED_NOTIFICATION_TEMPLATE
        )
        evidence = _attention_evidence(observation)
    return template.format(
        location_part=locality.location_part,
        title_part=title_part,
        target_session_id=target_session_id,
        computer_selector=locality.computer_selector,
        evidence=evidence,
    )


async def notify_stop(
    target_session_id: str,
    computer: str,
    title: str | None = None,
    *,
    variant: StopNotificationVariant,
    occurred_at: datetime | None,
) -> set[str]:
    """Notify listeners that a session finished its turn.

    Args:
        target_session_id: Session that finished
        computer: Computer name where session runs (for actionable command)
        title: Optional title/summary of the turn

    Returns:
        Number of listeners successfully notified
    """
    message = _stop_notification_message(target_session_id, computer, title, variant)
    return await _notify_listeners(
        target_session_id,
        message,
        occurrence_key=uuid4().hex,
        notification_kind=NotificationKind.TURN_END,
        occurred_at=occurred_at,
    )


async def notify_distress(
    target_session_id: str,
    computer: str,
    notification_kind: NotificationKind,
    title: str | None = None,
    *,
    observation: AgentAttentionObservation | None = None,
    inferred_stall_evidence: InferredStallEvidence | None = None,
    delivery_block_evidence: DeliveryBlockEvidence | None = None,
    occurrence_key: str | None = None,
    occurred_at: datetime | None,
) -> set[str]:
    """Notify persistent listeners of one attention occurrence."""
    message = _parent_attention_message(
        target_session_id,
        computer,
        title,
        notification_kind,
        observation,
        inferred_stall_evidence,
        delivery_block_evidence,
    )
    reached = await _notify_listeners(
        target_session_id,
        message,
        occurrence_key=occurrence_key or uuid4().hex,
        notification_kind=notification_kind,
        occurred_at=occurred_at,
    )
    return reached


async def notify_distress_human_fallback(
    target_session_id: str,
    computer: str,
    notification_kind: NotificationKind,
    client: "AdapterClient",
    title: str | None,
    inferred_stall_evidence: InferredStallEvidence | None = None,
    delivery_block_evidence: DeliveryBlockEvidence | None = None,
) -> bool:
    """Deliver unwatched distress only to the target session's own adapter."""
    target = await db.get_session(target_session_id)
    if target is None:
        return False
    message = _distress_notification_message(
        target_session_id,
        computer,
        title,
        notification_kind,
        inferred_stall_evidence,
        delivery_block_evidence,
    )
    return (
        await client.send_message(
            target,
            message,
            metadata=MessageMetadata(target_adapter_key=target.last_input_origin),
            cleanup_trigger=CleanupTrigger.NEXT_TURN,
            ephemeral=False,
        )
    ) is not None


async def deliver_remote_stop_notification(
    caller_session_id: str,
    target_session_id: str,
    computer: str,
    title: str | None = None,
    occurrence_key: str | None = None,
    *,
    variant: StopNotificationVariant,
    occurred_at: datetime | None,
) -> bool:
    """Deliver a forwarded stop notification directly to its initiator.

    The forwarding daemon owns no listener row for `target_session_id` — that
    session was created on another computer, so registration never ran here.
    The caller's identity travels on the wire instead of a listener lookup;
    deliver straight to its host pane.
    """
    caller = await db.get_session(caller_session_id)
    if not caller:
        logger.warning(
            "remote_stop_notification_undeliverable",
            caller_session_id=caller_session_id,
            target_session_id=target_session_id,
        )
        return False
    message = _stop_notification_message(target_session_id, computer, title, variant)
    try:
        source_occurrence_key = occurrence_key or uuid4().hex
        await handoff_control_payload(
            session_id=caller_session_id,
            body=message,
            source_key=f"listener:{target_session_id}:{caller_session_id}:{source_occurrence_key}",
            envelope=semantic_envelope(EnvelopeName.NOTIFICATION, fields=occurrence_fields(occurred_at), body=message),
        )
    except SessionMessageRejectedError as exc:
        logger.warning(
            "remote_stop_notification_delivery_failed",
            caller_session_id=caller_session_id,
            target_session_id=target_session_id,
            reason=exc.reason,
        )
        return False
    return True


async def deliver_remote_distress_notification(
    caller_session_id: str,
    target_session_id: str,
    computer: str,
    notification_kind: NotificationKind,
    title: str | None = None,
    occurrence_key: str | None = None,
    observation: AgentAttentionObservation | None = None,
    inferred_stall_evidence: InferredStallEvidence | None = None,
    delivery_block_evidence: DeliveryBlockEvidence | None = None,
    *,
    occurred_at: datetime | None,
) -> bool:
    """Deliver a forwarded distress notification directly to the remote caller."""
    caller = await db.get_session(caller_session_id)
    if caller is None:
        return False
    message = _parent_attention_message(
        target_session_id,
        computer,
        title,
        notification_kind,
        observation,
        inferred_stall_evidence,
        delivery_block_evidence,
    )
    try:
        await handoff_control_payload(
            session_id=caller_session_id,
            body=message,
            source_key=f"listener:{target_session_id}:{caller_session_id}:{occurrence_key or uuid4().hex}",
            envelope=semantic_envelope(EnvelopeName.NOTIFICATION, fields=occurrence_fields(occurred_at), body=message),
        )
    except SessionMessageRejectedError:
        return False
    return True


async def notify_gate_approved(target_session_id: str, *, slug: str) -> bool:
    """Inject a human-gate approval notification into a parked runner session.

    The workflow continuation boundary invokes this only for a claimant distinct
    from the acting session, regardless of whether the authority arrived through
    a direct human entry point or a trusted relay.

    Delivers into the target session itself (not its listeners). Returns ``True``
    when the message reached a live, open session; ``False`` when no such session
    exists (already exited, closed, or never linked).
    """
    session = await db.get_session(target_session_id)
    if session is None or is_session_terminal(
        lifecycle_status=session.lifecycle_status,
        closed_at=session.closed_at,
    ):
        logger.info(
            "runner approval notify skipped", session_id=target_session_id, slug=slug, reason="session-unavailable"
        )
        return False
    body = f"The human approved the pending gate for '{slug}'. Proceed with the lifecycle from where you parked."
    message = body
    # Best-effort: the approval stamp is already committed by the caller. The session
    # can vanish between the open-check above and delivery (closed/unavailable race);
    # that typed rejection must not surface as approval failure. Unexpected errors are
    # not swallowed — they propagate so a real defect is not masked as a delivery miss.
    try:
        await handoff_control_payload(
            session_id=target_session_id,
            body=message,
            source_key=f"approval:{target_session_id}:{slug}",
            envelope=semantic_envelope(EnvelopeName.NOTIFICATION, body=message),
        )
    except SessionMessageRejectedError as exc:
        logger.warning("runner approval notify rejected", session_id=target_session_id, slug=slug, reason=exc.reason)
        return False
    logger.info("runner approval notify delivered", session_id=target_session_id, slug=slug)
    return True
