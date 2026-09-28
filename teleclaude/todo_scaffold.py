"""Todo scaffolding helpers: the acting session's declared paths."""

from __future__ import annotations

from teleclaude.session_identity import get_session_id as _get_session_id
from teleclaude.session_scoping import live_declarations


def collect_declared_paths(project_path: str) -> set[str]:
    """Return this session's live declared paths.

    An empty result is the ordinary case — nothing declared yet — never an
    error state.
    """
    del project_path
    session_id = _get_session_id()
    if not session_id:
        return set()
    return {declaration.path for declaration in live_declarations(session_id)}
