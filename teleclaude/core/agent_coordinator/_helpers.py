"""Standalone helper functions for agent_coordinator.

Contains pure/stateless functions used by AgentCoordinator and its mixins,
plus the _SuppressionState dataclass and module-level constants.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from teleclaude.constants import (
    CHECKPOINT_MESSAGE,
    CHECKPOINT_PREFIX,
)

if TYPE_CHECKING:
    from teleclaude.core.models import Session

_NOOP_LOG_INTERVAL_SECONDS = 30.0
_MAX_FORWARDED_LINK_OUTPUT_CHARS = 12000


@dataclass
class _SuppressionState:  # pyright: ignore[reportUnusedClass]
    """Tracks repeated no-op events so logs can be sampled."""

    signature: str
    started_at: datetime
    last_log_at: datetime
    suppressed: int = 0


def _is_checkpoint_prompt(
    prompt: str,
    *,
    raw_payload: object = None,
) -> bool:
    """Return True when prompt text is our system checkpoint message.

    Matches both the generic Phase 1 message and context-aware Phase 2
    messages by checking known prefixes.  Codex synthetic input detection
    truncates captured prompt text, so we also accept 40-char prefixes of
    the generic constant for synthetic events.
    """
    prompt_clean = (prompt or "").strip()
    if not prompt_clean:
        return False

    # Canonical prefix match covers all checkpoint variants.
    if prompt_clean.startswith(CHECKPOINT_PREFIX):
        return True

    # Exact match for the generic constant (backward compat).
    checkpoint_clean = CHECKPOINT_MESSAGE.strip()
    if prompt_clean == checkpoint_clean:
        return True

    # Truncated Codex synthetic prompt (from output polling / fast-poll)
    is_codex_synthetic = False
    if isinstance(raw_payload, dict):
        source = raw_payload.get("source")
        is_codex_synthetic = (
            bool(raw_payload.get("synthetic")) and isinstance(source, str) and source.startswith("codex_")
        )

    if is_codex_synthetic and len(prompt_clean) >= 40 and checkpoint_clean.startswith(prompt_clean):
        return True

    return False


def _is_codex_synthetic_prompt_event(raw_payload: object) -> bool:
    """Return True for Codex synthetic prompt events derived from output polling."""
    if not isinstance(raw_payload, Mapping):
        return False
    source = raw_payload.get("source")
    return bool(raw_payload.get("synthetic")) and isinstance(source, str) and source.startswith("codex_")


async def has_active_output_message(session: "Session") -> bool:
    """Check if any adapter has an active output message in metadata.

    Fetches fresh session from DB to avoid stale in-memory origin_metadata
    that caused missed output on turn 2+ (the staleness regression).
    Checks all origin_metadata sections dynamically rather than hardcoding
    adapter keys.
    """
    from teleclaude.core.db import db  # pylint: disable=import-outside-toplevel

    fresh = await db.get_session(session.session_id)
    s = fresh if fresh else session
    for section in s.origin_metadata.values():
        if isinstance(section, dict) and section.get("output_message_id"):
            return True
    return False


# Backward-compatible alias for existing internal callers.
_has_active_output_message = has_active_output_message


def _to_utc(ts: datetime) -> datetime:
    """Normalize naive datetimes to UTC for stable comparisons."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _is_codex_input_already_recorded(
    session: "Session | None",
    prompt_text: str,
) -> bool:
    """Return True when session state already reflects this Codex prompt turn."""
    if not session:
        return False

    existing_prompt = (session.last_message_sent or "").strip()
    candidate_prompt = (prompt_text or "").strip()
    if not existing_prompt or not candidate_prompt:
        return False
    prompts_match = (
        existing_prompt == candidate_prompt
        or existing_prompt.startswith(candidate_prompt)
        or candidate_prompt.startswith(existing_prompt)
    )
    if not prompts_match:
        return False
    if not isinstance(session.last_message_sent_at, datetime):
        return False

    message_at = _to_utc(session.last_message_sent_at)
    if not isinstance(session.last_output_at, datetime):
        return True
    feedback_at = _to_utc(session.last_output_at)
    return message_at > feedback_at


__all__ = [
    "_has_active_output_message",
    "_is_checkpoint_prompt",
    "_is_codex_input_already_recorded",
    "_is_codex_synthetic_prompt_event",
    "has_active_output_message",
]
