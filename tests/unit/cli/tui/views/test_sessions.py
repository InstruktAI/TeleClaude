"""Characterization tests for teleclaude.cli.tui.views.sessions.

SessionsView is a full Textual widget. Highlight and state-export logic are
characterized in test_sessions_highlights.py. Action logic is characterized in
test_sessions_actions.py. This file verifies the class is importable.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_sessions_view_is_importable() -> None:
    from teleclaude.cli.tui.views.sessions import SessionsView

    assert SessionsView is not None
