"""Value objects for the destination-addressed delivery seam.

See docs/project/spec/session-output-routing.md#canonical-fields for the
routing contract these types implement.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class InvalidDestinationOverrideError(ValueError):
    """A caller-supplied destination override (e.g. ``metadata.channel_id``) is malformed.

    Raised instead of silently falling back to the session-derived default —
    an explicit override that cannot be honored is a caller contract error,
    not a cue to deliver somewhere else.
    """


class DeliveryScope(StrEnum):
    """Recipient policy for a delivered message.

    Closed vocabulary per project/spec/session-output-routing#allowed-values.
    """

    ORIGIN_ONLY = "ORIGIN_ONLY"
    ADMIN_ONLY = "ADMIN_ONLY"
    DUAL = "DUAL"
    CTRL = "CTRL"


MessageIntent = Literal[
    "feedback_notice_error_status",
    "last_output_summary",
    "output_stream_chunk_final_threaded",
    "input_reflection_text",
    "input_reflection_voice",
    "input_reflection_mcp",
    "reminder_lifecycle",
    "ctrl_activity",
]

# Message intent to delivery scope, per
# project/spec/session-output-routing#message-intent-to-scope-mapping.
MESSAGE_INTENT_TO_SCOPE: dict[MessageIntent, DeliveryScope] = {
    "feedback_notice_error_status": DeliveryScope.ORIGIN_ONLY,
    "last_output_summary": DeliveryScope.ORIGIN_ONLY,
    "output_stream_chunk_final_threaded": DeliveryScope.DUAL,
    "input_reflection_text": DeliveryScope.ADMIN_ONLY,
    "input_reflection_voice": DeliveryScope.ADMIN_ONLY,
    "input_reflection_mcp": DeliveryScope.ADMIN_ONLY,
    "reminder_lifecycle": DeliveryScope.DUAL,
    "ctrl_activity": DeliveryScope.CTRL,
}


@dataclass(frozen=True)
class Destination:
    """A resolved, platform-addressed delivery target.

    Carries no ``Session`` — only the concrete platform coords a UI adapter
    needs to address delivery, plus the owning session's identifier for the
    adapter's own local bookkeeping (receipt/metadata writes keyed by
    session_id, exactly as today).
    """

    platform: str
    session_id: str
    channel_id: int | None = None
    thread_id: int | None = None
    chat_id: int | None = None
    phone_number: str | None = None
    # WhatsApp-only: determines text-vs-template send eligibility (24h customer window).
    last_customer_message_at: str | None = None


@dataclass(frozen=True)
class DeliveryPlan:
    """Recipient selection for one delivery: scope, origin, and admin lane."""

    scope: DeliveryScope
    origin_endpoint: Destination | None = None
    admin_lane_destinations: tuple[Destination, ...] = field(default_factory=tuple)
