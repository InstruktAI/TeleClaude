"""Standalone helper functions for agent_coordinator."""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from teleclaude.constants import CHECKPOINT_MESSAGE, CHECKPOINT_PREFIX

if TYPE_CHECKING:
    from teleclaude.core.models._session import Session

_NOOP_LOG_INTERVAL_SECONDS = 30.0
_MAX_FORWARDED_LINK_OUTPUT_CHARS = 12000


def transcript_expected_to_exist(session: "Session") -> bool:
    """Return True when the agent's transcript file is expected to exist on disk.

    Codex CLI doesn't write its session transcript until the first user prompt
    is submitted. Our synthetic `session_start` (used to bridge Codex's broken
    cold-launch hook) fires before the file exists, so `native_log_file` stays
    None until Codex's real `session_start` arrives — which it does combined
    with `user_prompt_submit`. Until that back-fill happens, any code that
    tries to read the transcript must gracefully degrade instead of failing.

    Claude and Gemini emit `session_start` correctly on agent launch and the
    daemon records `native_log_file` immediately, so this returns True for them
    as soon as the session_start hook has been processed.

    Callers should use this as a precondition check: when False, return empty
    or skip the cycle silently. When True but the file is genuinely missing,
    that is a real anomaly worth logging.
    """
    return session.native_log_file is not None


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
