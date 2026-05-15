"""Standalone helper functions for agent_coordinator."""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import CHECKPOINT_MESSAGE, CHECKPOINT_PREFIX
from teleclaude.core.agents import AgentName
from teleclaude.core.models import JsonDict
from teleclaude.utils.transcript._iterators import _get_entries_for_agent

if TYPE_CHECKING:
    from teleclaude.core.models._session import Session

logger = get_logger(__name__)

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


async def wait_for_transcript_ready(
    session: "Session",
    *,
    content_predicate: Callable[[list[JsonDict]], bool],
    timeout_s: float = 10.0,
    poll_interval_s: float = 0.25,
) -> bool:
    """Block until the session's native transcript file satisfies a predicate.

    Background work blocks that depend on the agent transcript file (slow
    runner summary, etc.) call this once at the top of their work, then
    proceed against the now-ready file via the existing synchronous extract
    helpers. The point is to gate the entire dependent chain on file
    readiness in a single place, not to scatter polling into every leaf
    helper.

    Behavior:
      - If ``transcript_expected_to_exist(session)`` is False, return True
        immediately. The absence is semantically expected (e.g. Codex
        pre-prompt-submit) and the caller's chain typically no-ops.
      - Otherwise poll ``_get_entries_for_agent`` at ``poll_interval_s``
        intervals until ``content_predicate(entries)`` returns True or the
        ``timeout_s`` budget elapses.
      - Returns True if the predicate held within the budget; False on
        timeout (caller should log + degrade).

    The predicate is supplied by the caller so the helper stays generic.
    Examples:
      - "at least one assistant entry" — for agent_stop summary
      - "at least one user entry" — for user-prompt projection
    """
    if not transcript_expected_to_exist(session):
        return True

    transcript_path = session.native_log_file
    if transcript_path is None:
        # transcript_expected_to_exist was True but native_log_file is now
        # None — torn read between predicate and field access; treat as a
        # contract failure surface caller can degrade against.
        logger.warning(
            "transcript expected but native_log_file missing",
            session_id=session.session_id,
        )
        return False

    active_agent = session.active_agent
    if not active_agent:
        # transcript_expected_to_exist gates on native_log_file presence —
        # a present log file with no active_agent means we cannot pick a
        # transcript iterator, so downstream extraction is guaranteed to
        # silently fail. Fail loudly here instead of returning a false
        # "ready" signal.
        logger.warning(
            "transcript expected but active_agent missing",
            session_id=session.session_id,
            transcript_path=transcript_path,
        )
        return False
    try:
        agent_name = AgentName.from_str(active_agent)
    except ValueError:
        logger.warning(
            "transcript expected but active_agent invalid",
            session_id=session.session_id,
            transcript_path=transcript_path,
            active_agent=active_agent,
        )
        return False

    deadline = time.monotonic() + timeout_s
    while True:
        entries = await asyncio.to_thread(_get_entries_for_agent, transcript_path, agent_name)
        if entries is not None and content_predicate(entries):
            return True
        if time.monotonic() >= deadline:
            logger.warning(
                "transcript not ready within timeout",
                session_id=session.session_id,
                transcript_path=transcript_path,
                timeout_s=timeout_s,
            )
            return False
        await asyncio.sleep(poll_interval_s)


def transcript_has_assistant_entry(entries: list[JsonDict]) -> bool:
    """Predicate: transcript contains at least one assistant message entry.

    Used by ``wait_for_transcript_ready`` to detect *file readiness* — i.e.
    that the agent has flushed its turn-final response to disk. Content
    semantics (empty vs non-empty text) are NOT considered here: codex
    legitimately emits ``final_answer`` with empty text when its turn
    produced no chat reply (file write, no commentary, exit). That is a
    completed turn, not a flush-pending state. Downstream extraction
    decides whether to summarize based on the actual text.
    """
    for entry in entries:
        message_field = entry.get("message")
        if isinstance(message_field, dict):
            role = message_field.get("role")
        else:
            payload = entry.get("payload")
            if not isinstance(payload, dict):
                continue
            role = payload.get("role")
        if role == "assistant":
            return True
    return False


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
    "transcript_expected_to_exist",
    "transcript_has_assistant_entry",
    "wait_for_transcript_ready",
]
