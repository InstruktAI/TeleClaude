"""Standalone helper functions for agent_coordinator."""

from dataclasses import dataclass
from datetime import datetime

from teleclaude.constants import CHECKPOINT_MESSAGE, CHECKPOINT_PREFIX

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
    messages by checking known prefixes.
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

    return False


__all__ = [
    "_is_checkpoint_prompt",
]
