"""Feedback utilities for TeleClaude sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from teleclaude.core.models import Session


def get_last_feedback(session: Session) -> Optional[str]:
    """Get the last feedback text, preferring the LLM summary over raw output."""
    return session.last_feedback_summary or session.last_feedback_received
