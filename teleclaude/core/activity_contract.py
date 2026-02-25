"""Canonical outbound activity contract for TeleClaude.

Defines the canonical outbound activity event vocabulary, routing metadata,
and shared serializer/validator utilities. All activity event producers must
route through this module before fan-out to ensure schema consistency.

Canonical activity event types (outbound vocabulary):
  - user_prompt_submit  — user turn start signal
  - agent_output_update — agent working (tool call initiated or completed)
  - agent_output_stop   — agent turn complete

See docs/project/spec/event-vocabulary.md for the full vocabulary and
hook-to-canonical mapping.
"""

from dataclasses import dataclass
from typing import Literal

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Canonical outbound activity event types (R1)
# ---------------------------------------------------------------------------

CanonicalActivityEventType = Literal[
    "user_prompt_submit",
    "agent_output_update",
    "agent_output_stop",
]

# Routing intent for all activity control events (CTRL scope, no UI content)
ACTIVITY_MESSAGE_INTENT: str = "ctrl_activity"
ACTIVITY_DELIVERY_SCOPE: Literal["CTRL"] = "CTRL"

# ---------------------------------------------------------------------------
# Hook-to-canonical mapping (R1)
# ---------------------------------------------------------------------------

HOOK_TO_CANONICAL: dict[str, CanonicalActivityEventType] = {
    "user_prompt_submit": "user_prompt_submit",
    "tool_use": "agent_output_update",
    "tool_done": "agent_output_update",
    "agent_stop": "agent_output_stop",
}

# ---------------------------------------------------------------------------
# Canonical event dataclass (R2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CanonicalActivityEvent:
    """Canonical outbound activity event for all consumer adapters.

    Carries all required identity/routing fields plus event-specific payload.
    Produced by serialize_activity_event() from internal hook-level events.
    """

    # Required identity/routing fields
    session_id: str
    canonical_type: CanonicalActivityEventType
    hook_event_type: str  # preserved for consumer compatibility during migration
    timestamp: str
    message_intent: str
    delivery_scope: str

    # Optional event-specific payload
    tool_name: str | None = None
    tool_preview: str | None = None
    summary: str | None = None


# ---------------------------------------------------------------------------
# Validation (R3)
# ---------------------------------------------------------------------------

_CANONICAL_TYPES: frozenset[str] = frozenset({"user_prompt_submit", "agent_output_update", "agent_output_stop"})
_DELIVERY_SCOPES: frozenset[str] = frozenset({"ORIGIN_ONLY", "DUAL", "CTRL"})


def _validate_canonical_event(event: CanonicalActivityEvent) -> list[str]:
    """Validate canonical event fields. Returns a list of error strings."""
    errors: list[str] = []
    if not event.session_id:
        errors.append("session_id is required and must be non-empty")
    if not event.canonical_type:
        errors.append("canonical_type is required and must be non-empty")
    elif event.canonical_type not in _CANONICAL_TYPES:
        errors.append(f"invalid canonical_type: {event.canonical_type!r}")
    if not event.timestamp:
        errors.append("timestamp is required and must be non-empty")
    if not event.message_intent:
        errors.append("message_intent is required and must be non-empty")
    if event.delivery_scope not in _DELIVERY_SCOPES:
        errors.append(f"invalid delivery_scope: {event.delivery_scope!r}")
    return errors


# ---------------------------------------------------------------------------
# Serializer (R3)
# ---------------------------------------------------------------------------


def serialize_activity_event(
    session_id: str,
    hook_event_type: str,
    timestamp: str,
    *,
    tool_name: str | None = None,
    tool_preview: str | None = None,
    summary: str | None = None,
) -> CanonicalActivityEvent | None:
    """Serialize an internal hook-level activity event to the canonical outbound form.

    Returns None if serialization or validation fails. Failures are logged
    explicitly but never crash the output flow (R3).

    Args:
        session_id: TeleClaude session identifier.
        hook_event_type: Internal hook event type (e.g. 'tool_use', 'agent_stop').
        timestamp: ISO 8601 UTC timestamp string.
        tool_name: Optional tool name (for tool_use events).
        tool_preview: Optional UI preview text (for tool_use events).
        summary: Optional output summary (for agent_stop events).

    Returns:
        CanonicalActivityEvent on success, None on unmapped or invalid input.
    """
    canonical_type = HOOK_TO_CANONICAL.get(hook_event_type)
    if canonical_type is None:
        logger.warning(
            "activity_contract: unknown hook event type %r, skipping canonical serialization",
            hook_event_type,
            extra={"session_id": session_id[:8] if session_id else ""},
        )
        return None

    event = CanonicalActivityEvent(
        session_id=session_id,
        canonical_type=canonical_type,
        hook_event_type=hook_event_type,
        timestamp=timestamp,
        message_intent=ACTIVITY_MESSAGE_INTENT,
        delivery_scope=ACTIVITY_DELIVERY_SCOPE,
        tool_name=tool_name,
        tool_preview=tool_preview,
        summary=summary,
    )

    errors = _validate_canonical_event(event)
    if errors:
        logger.error(
            "activity_contract: canonical event validation failed: %s",
            errors,
            extra={"session_id": session_id[:8] if session_id else "", "hook_event_type": hook_event_type},
        )
        return None

    return event
