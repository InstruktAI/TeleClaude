"""Body-free observation for native user reflection decisions."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

if TYPE_CHECKING:
    from teleclaude.core.models import Session
    from teleclaude.utils.transcript import ClaudeTurnCommitment

logger = get_logger(__name__)

_EVENT = "user_reflection_projection_decision"
_last_decisions: dict[tuple[str, str | None, str | None], tuple[str, str, tuple[str, ...]]] = {}


class UserReflectionProjectionOutcome(StrEnum):
    SENT = "sent"
    DEFERRED = "deferred"
    SUPPRESSED = "suppressed"
    FAILED = "failed"


class UserReflectionProjectionReason(StrEnum):
    PLATFORM_RECEIPT = "platform_receipt"
    PROJECTION_WATERMARK = "projection_watermark"
    STALE_ORIGIN = "stale_origin"
    BINDING_CONFLICT = "binding_conflict"
    ACCEPTED_RECEIPT_UNBOUND = "accepted_receipt_unbound"
    DAEMON_CONTROL = "daemon_control"
    ORIGIN_ALREADY_VISIBLE = "origin_already_visible"
    TARGET_UNAVAILABLE = "target_unavailable"
    NO_REFLECTABLE_PART = "no_reflectable_part"
    TRANSPORT_FAILURE = "transport_failure"


def observe_user_reflection_projection(
    session: Session,
    *,
    native_entry_id: str | None,
    commitment: ClaudeTurnCommitment | None,
    binding_id: str | None,
    outcome: UserReflectionProjectionOutcome,
    reason: StrEnum,
    platform_message_ids: Sequence[str] = (),
) -> None:
    """Record a source-level reflection decision only when its state changes."""
    key = (session.session_id, session.native_session_id, native_entry_id)
    decision = (outcome.value, reason.value, tuple(platform_message_ids))
    if _last_decisions.get(key) == decision:
        return
    _last_decisions[key] = decision
    logger.info(
        _EVENT,
        outcome=outcome.value,
        reason=reason.value,
        session_id=session.session_id,
        native_session_id=session.native_session_id,
        parent_entry_id=commitment.parent_entry_id if commitment is not None else None,
        native_entry_id=native_entry_id,
        binding_id=binding_id,
        platform_message_ids=list(platform_message_ids),
        platform_message_count=len(platform_message_ids),
    )
