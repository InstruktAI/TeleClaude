"""Characterization tests for teleclaude.cli.tui.views.sessions.

SessionsView is a full Textual widget. Highlight and state-export logic are
characterized in test_sessions_highlights.py. Action logic is characterized in
test_sessions_actions.py. This file verifies the class is importable and
characterizes pure-logic methods that do not require a running Textual app.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
def test_sessions_view_is_importable() -> None:
    from teleclaude.cli.tui.views.sessions import SessionsView

    assert SessionsView is not None


class _FakeSessionRow:
    """Duck-typed stand-in for SessionRow — compatible with isinstance via patch."""

    def __init__(self, session_id: str, tmux_session_name: str | None = None) -> None:
        self.session_id = session_id
        self.session = MagicMock()
        self.session.tmux_session_name = tmux_session_name


def _make_view(pending_id: str | None, nav_items: list[object], *, request_focus: bool = False) -> MagicMock:
    """Return a minimal mock that satisfies _apply_pending_selection's interface."""
    from teleclaude.cli.tui.views.sessions import _PendingSelect

    view = MagicMock()
    if pending_id is not None:
        view._pending_select = _PendingSelect(pending_id, request_focus)
    else:
        view._pending_select = None
    view._nav_items = nav_items
    return view


@pytest.mark.unit
def test_apply_pending_selection_waits_for_tmux_pane() -> None:
    """Pending ID is kept when session is in the tree but has no tmux pane.

    The method waits for tmux_session_name to be set before consuming the
    pending ID, so the layout can actually render the pane.
    """
    from teleclaude.cli.tui.views.sessions import SessionsView

    row = _FakeSessionRow("test-123", tmux_session_name=None)
    view = _make_view("test-123", [row])

    with patch("teleclaude.cli.tui.views.sessions.SessionRow", _FakeSessionRow):
        SessionsView._apply_pending_selection(view)

    # Pending state kept — not consumed yet
    assert view._pending_select is not None
    assert view._pending_select.session_id == "test-123"
    view.post_message.assert_not_called()


@pytest.mark.unit
def test_apply_pending_selection_selects_when_tmux_ready() -> None:
    """Session is selected and previewed once tmux_session_name is available."""
    from teleclaude.cli.tui.messages import PreviewChanged
    from teleclaude.cli.tui.views.sessions import SessionsView

    row = _FakeSessionRow("sess-abc", tmux_session_name="tc_sess-abc")
    view = _make_view("sess-abc", [row])

    with patch("teleclaude.cli.tui.views.sessions.SessionRow", _FakeSessionRow):
        SessionsView._apply_pending_selection(view)

    assert view._pending_select is None
    msg = view.post_message.call_args[0][0]
    assert isinstance(msg, PreviewChanged)
    assert msg.session_id == "sess-abc"
    assert msg.request_focus is False


@pytest.mark.unit
def test_apply_pending_selection_noop_when_session_not_in_tree() -> None:
    """Pending ID is kept when the session is not yet in the nav tree."""
    from teleclaude.cli.tui.views.sessions import SessionsView

    other_row = _FakeSessionRow("other-session")
    view = _make_view("missing-session", [other_row])

    with patch("teleclaude.cli.tui.views.sessions.SessionRow", _FakeSessionRow):
        SessionsView._apply_pending_selection(view)

    assert view._pending_select is not None
    assert view._pending_select.session_id == "missing-session"
    view.post_message.assert_not_called()


@pytest.mark.unit
def test_apply_pending_selection_noop_when_no_pending() -> None:
    """Method returns immediately when no pending selection is set."""
    from teleclaude.cli.tui.views.sessions import SessionsView

    view = _make_view(None, [])

    with patch("teleclaude.cli.tui.views.sessions.SessionRow", _FakeSessionRow):
        SessionsView._apply_pending_selection(view)

    view.post_message.assert_not_called()
