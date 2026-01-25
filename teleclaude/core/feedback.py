"""Feedback utilities for TeleClaude sessions.

Provides helper functions for accessing session feedback based on configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from teleclaude.config import config

if TYPE_CHECKING:
    from teleclaude.core.models import Session


def get_last_feedback(session: Session) -> Optional[str]:
    """Get the appropriate last feedback text based on summarizer config.

    If summarizer.enabled is True, returns the LLM-generated summary.
    If False, returns the raw agent output (last_feedback_received).

    Args:
        session: Session object with feedback fields populated.

    Returns:
        The summary or raw output depending on config, or None if neither available.
    """
    if config.summarizer.enabled:
        # Prefer summary, fall back to raw if summary not available
        return session.last_feedback_summary or session.last_feedback_received
    # Summarizer disabled - use raw agent output
    return session.last_feedback_received
