"""Read the session-selection disposition published by agent runtime."""

from __future__ import annotations

from teleclaude.api_models import SessionDTO
from teleclaude.core.session_status import SessionSelectionDisposition


def is_headless_session(session: SessionDTO) -> bool:
    """Whether runtime explicitly permits the sanctioned headless adoption gesture."""
    return session.selection_disposition == SessionSelectionDisposition.ADOPT_HEADLESS


def is_attachable_session(session: SessionDTO) -> bool:
    """Whether runtime permits ordinary preview selection for this session."""
    return session.selection_disposition == SessionSelectionDisposition.PREVIEW
