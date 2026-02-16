"""Output summary utilities for TeleClaude sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from teleclaude.core.models import Session


def get_last_output_summary(session: Session) -> Optional[str]:
    """Get the last output text, preferring the LLM summary over raw output."""
    return session.last_output_summary or session.last_output_raw
