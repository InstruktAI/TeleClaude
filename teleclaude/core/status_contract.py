"""Canonical lifecycle status contract for TeleClaude sessions.

Defines the canonical outbound lifecycle status vocabulary, transition rules,
timing thresholds, and shared serializer/validator utilities. All lifecycle
status transition producers must route through this module before fan-out to
ensure schema consistency.

Canonical lifecycle status values (outbound vocabulary):
  - accepted        — user prompt accepted, agent response imminent
  - awaiting_output — optimistic accepted window expired, still waiting
  - active_output   — agent is actively producing output
  - stalled         — extended inactivity, no output evidence
  - completed       — agent turn finished successfully
  - error           — agent encountered an error
  - closed          — session closed

Required outbound fields (R2):
  session_id, status, reason, timestamp, last_activity_at (when known)

See requirements.md R1-R4 for the full contract specification.
"""

from dataclasses import dataclass, field
from typing import Literal

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Canonical lifecycle status vocabulary (R2)
# ---------------------------------------------------------------------------

LifecycleStatus = Literal[
    "accepted",
    "awaiting_output",
    "active_output",
    "stalled",
    "completed",
    "error",
    "closed",
]

# Allowed status values as a frozenset for O(1) validation
LIFECYCLE_STATUSES: frozenset[str] = frozenset(
    {
        "accepted",
        "awaiting_output",
        "active_output",
        "stalled",
        "completed",
        "error",
        "closed",
    }
)

# ---------------------------------------------------------------------------
# Core-owned stall timing thresholds (R4, deterministic across all adapters)
# ---------------------------------------------------------------------------

# After user_prompt_submit: transition from `accepted` to `awaiting_output`
AWAITING_OUTPUT_THRESHOLD_SECONDS: float = 30.0

# After `awaiting_output`: transition to `stalled` when no output arrives
STALL_THRESHOLD_SECONDS: float = 120.0

# ---------------------------------------------------------------------------
# Routing metadata for status events
# ---------------------------------------------------------------------------

STATUS_MESSAGE_INTENT: str = "ctrl_status"
STATUS_DELIVERY_SCOPE: Literal["CTRL"] = "CTRL"

# ---------------------------------------------------------------------------
# Canonical reason codes
# ---------------------------------------------------------------------------

StatusReason = Literal[
    "user_prompt_accepted",
    "awaiting_output_timeout",
    "stall_timeout",
    "output_observed",
    "output_resumed",
    "agent_turn_complete",
    "agent_error",
    "session_closed",
]

# ---------------------------------------------------------------------------
# Canonical status event dataclass (R2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CanonicalStatusEvent:
    """Canonical outbound lifecycle status event for all consumer adapters.

    Carries all required fields for status fanout per R2. Produced by
    serialize_status_event() from internal lifecycle signals.
    """

    # Required fields (R2)
    session_id: str
    status: LifecycleStatus
    reason: str
    timestamp: str

    # Optional fields (R2 — "when known")
    last_activity_at: str | None = None

    # Routing metadata
    message_intent: str = field(default=STATUS_MESSAGE_INTENT)
    delivery_scope: str = field(default=STATUS_DELIVERY_SCOPE)


# ---------------------------------------------------------------------------
# Validation (R2)
# ---------------------------------------------------------------------------


def _validate_status_event(event: CanonicalStatusEvent) -> list[str]:
    """Validate canonical status event fields. Returns a list of error strings."""
    errors: list[str] = []
    if not event.session_id:
        errors.append("session_id is required and must be non-empty")
    if not event.status:
        errors.append("status is required and must be non-empty")
    elif event.status not in LIFECYCLE_STATUSES:
        errors.append(f"invalid status: {event.status!r}")
    if not event.reason:
        errors.append("reason is required and must be non-empty")
    if not event.timestamp:
        errors.append("timestamp is required and must be non-empty")
    return errors


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


def serialize_status_event(
    session_id: str,
    status: str,
    reason: str,
    timestamp: str,
    *,
    last_activity_at: str | None = None,
) -> "CanonicalStatusEvent | None":
    """Serialize a lifecycle status transition to the canonical outbound form.

    Returns None if validation fails. Failures are logged but never crash
    the transition flow (parallel to activity_contract.serialize_activity_event).

    Args:
        session_id: TeleClaude session identifier.
        status: Target lifecycle status value (must be in LIFECYCLE_STATUSES).
        reason: Reason code describing why this transition occurred.
        timestamp: ISO 8601 UTC timestamp string.
        last_activity_at: ISO 8601 UTC timestamp of last observed activity (optional).

    Returns:
        CanonicalStatusEvent on success, None on invalid input.
    """
    event = CanonicalStatusEvent(
        session_id=session_id,
        status=status,  # type: ignore[arg-type]
        reason=reason,
        timestamp=timestamp,
        last_activity_at=last_activity_at,
    )

    errors = _validate_status_event(event)
    if errors:
        logger.error(
            "status_contract: canonical status event validation failed: %s",
            errors,
            extra={"session_id": session_id[:8] if session_id else "", "status": status},
        )
        return None

    return event
