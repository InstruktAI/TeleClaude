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


def _make_view(pending_id: str, nav_items: list[object]) -> MagicMock:
    """Return a minimal mock that satisfies _apply_pending_selection's interface."""
    view = MagicMock()
    view._pending_select_session_id = pending_id
    view._nav_items = nav_items
    return view


@pytest.mark.unit
def test_apply_pending_selection_selects_without_tmux_pane() -> None:
    """Session is selected immediately even when tmux_session_name is None.

    Previously the method returned early when tmux_session_name was falsy.
    The guard was removed so the selection happens as soon as the session row
    appears in the tree — the pane bridge handles the case where no pane exists.
    """
    from teleclaude.cli.tui.messages import PreviewChanged
    from teleclaude.cli.tui.views.sessions import SessionsView

    row = _FakeSessionRow("test-123", tmux_session_name=None)
    view = _make_view("test-123", [row])

    with patch("teleclaude.cli.tui.views.sessions.SessionRow", _FakeSessionRow):
        SessionsView._apply_pending_selection(view)

    assert view._pending_select_session_id is None
    view.post_message.assert_called_once()
    msg = view.post_message.call_args[0][0]
    assert isinstance(msg, PreviewChanged)
    assert msg.session_id == "test-123"
    assert msg.request_focus is True


@pytest.mark.unit
def test_apply_pending_selection_transfers_focus() -> None:
    """PreviewChanged is posted with request_focus=True on auto-select.

    Previously request_focus was False (preview without focus transfer).
    Auto-select now requests focus so the new session pane is immediately active.
    """
    from teleclaude.cli.tui.messages import PreviewChanged
    from teleclaude.cli.tui.views.sessions import SessionsView

    row = _FakeSessionRow("sess-abc", tmux_session_name="tc_sess-abc")
    view = _make_view("sess-abc", [row])

    with patch("teleclaude.cli.tui.views.sessions.SessionRow", _FakeSessionRow):
        SessionsView._apply_pending_selection(view)

    msg = view.post_message.call_args[0][0]
    assert isinstance(msg, PreviewChanged)
    assert msg.request_focus is True


@pytest.mark.unit
def test_apply_pending_selection_noop_when_session_not_in_tree() -> None:
    """Pending ID is kept when the session is not yet in the nav tree."""
    from teleclaude.cli.tui.views.sessions import SessionsView

    other_row = _FakeSessionRow("other-session")
    view = _make_view("missing-session", [other_row])

    with patch("teleclaude.cli.tui.views.sessions.SessionRow", _FakeSessionRow):
        SessionsView._apply_pending_selection(view)

    assert view._pending_select_session_id == "missing-session"
    view.post_message.assert_not_called()


@pytest.mark.unit
def test_apply_pending_selection_noop_when_no_pending() -> None:
    """Method returns immediately when no pending selection is set."""
    from teleclaude.cli.tui.views.sessions import SessionsView

    view = _make_view("", [])
    view._pending_select_session_id = None

    with patch("teleclaude.cli.tui.views.sessions.SessionRow", _FakeSessionRow):
        SessionsView._apply_pending_selection(view)

    view.post_message.assert_not_called()
