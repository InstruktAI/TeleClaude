"""Characterization tests for teleclaude.cli.tui.views.sessions_actions.

SessionsViewActionsMixin methods delegate to Textual app infrastructure
(post_message, query_one, push_screen, etc.) and cannot be exercised
without a running Textual app. This file verifies the class is importable.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_sessions_view_actions_mixin_is_importable() -> None:
    from teleclaude.cli.tui.views.sessions_actions import SessionsViewActionsMixin

    assert SessionsViewActionsMixin is not None
