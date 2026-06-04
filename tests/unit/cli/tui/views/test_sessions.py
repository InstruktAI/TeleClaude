"""Characterization tests for teleclaude.cli.tui.views.sessions.

SessionsView is a full Textual widget. Highlight and state-export logic are
characterized in test_sessions_highlights.py. Action logic is characterized in
test_sessions_actions.py. This file verifies the class is importable and
characterizes pure-logic methods that do not require a running Textual app.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from textual.app import App, ComposeResult

from teleclaude.api_models import ComputerDTO, ProjectDTO, SessionDTO
from teleclaude.cli.tui.messages import PreviewChanged
from teleclaude.cli.tui.views.sessions import SessionsView, _PendingSelect
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.session_row import SessionRow


@pytest.mark.unit
def test_sessions_view_is_importable() -> None:
    assert SessionsView is not None


class _SessionsHarness(App[None]):
    """Minimal app harness for exercising SessionsView folding."""

    def compose(self) -> ComposeResult:
        yield SessionsView(id="sessions-view")

    def on_mount(self) -> None:
        self.query_one(SessionsView).focus()


def _computers() -> list[ComputerDTO]:
    return [ComputerDTO(name="c1", status="online", user="u", host="h", is_local=True)]


def _projects() -> list[ProjectDTO]:
    return [ProjectDTO(computer="c1", name="proj", path="/repo", description=None)]


def _sessions() -> list[SessionDTO]:
    return [SessionDTO(session_id="s1", title="root", status="idle", project_path="/repo", computer="c1")]


def _cursor_to(view: SessionsView, widget_type: type) -> None:
    view.cursor_index = next(i for i, w in enumerate(view._nav_items) if isinstance(w, widget_type))


@pytest.mark.unit
async def test_sessions_collapse_project_hides_sessions_and_expand_restores() -> None:
    app = _SessionsHarness()
    async with app.run_test() as pilot:
        view = app.query_one(SessionsView)
        view.update_data(_computers(), _projects(), _sessions())
        await pilot.pause()

        _cursor_to(view, ProjectHeader)
        assert any(isinstance(w, SessionRow) for w in view._nav_items)

        view.action_collapse()
        await pilot.pause()
        assert not any(isinstance(w, SessionRow) for w in view._nav_items)
        assert "/repo" in view._collapsed_projects

        view.action_expand()
        await pilot.pause()
        assert any(isinstance(w, SessionRow) for w in view._nav_items)
        assert "/repo" not in view._collapsed_projects


@pytest.mark.unit
async def test_sessions_collapse_computer_hides_projects_but_keeps_header() -> None:
    app = _SessionsHarness()
    async with app.run_test() as pilot:
        view = app.query_one(SessionsView)
        view.update_data(_computers(), _projects(), _sessions())
        await pilot.pause()

        _cursor_to(view, ComputerHeader)
        view.action_collapse()
        await pilot.pause()

        assert any(isinstance(w, ComputerHeader) for w in view._nav_items)
        assert not any(isinstance(w, ProjectHeader) for w in view._nav_items)
        assert not any(isinstance(w, SessionRow) for w in view._nav_items)
        assert "c1" in view._collapsed_computers


@pytest.mark.unit
async def test_sessions_structure_keys_toggle_structure_without_touching_leaves() -> None:
    app = _SessionsHarness()
    async with app.run_test() as pilot:
        view = app.query_one(SessionsView)
        view.update_data(_computers(), _projects(), _sessions())
        await pilot.pause()
        leaf_before = set(view._collapsed_sessions)

        view.action_collapse_structure()
        await pilot.pause()
        assert view._collapsed_computers == {"c1"}
        assert view._collapsed_projects == {"/repo"}
        assert not any(isinstance(w, (ProjectHeader, SessionRow)) for w in view._nav_items)
        assert view._collapsed_sessions == leaf_before

        view.action_expand_structure()
        await pilot.pause()
        assert view._collapsed_computers == set()
        assert view._collapsed_projects == set()
        assert any(isinstance(w, SessionRow) for w in view._nav_items)


@pytest.mark.unit
def test_sessions_load_persisted_collapsed_structure() -> None:
    view = SessionsView()
    view.load_persisted_state({"collapsed_computers": ["c1"], "collapsed_projects": ["/repo"]})
    assert view._collapsed_computers == {"c1"}
    assert view._collapsed_projects == {"/repo"}


@pytest.mark.unit
def test_sessions_load_persisted_ignores_malformed_collapsed_structure() -> None:
    view = SessionsView()
    view.load_persisted_state({"collapsed_computers": "c1", "collapsed_projects": 5})
    assert view._collapsed_computers == set()
    assert view._collapsed_projects == set()


class _FakeSessionRow:
    """Duck-typed stand-in for SessionRow — compatible with isinstance via patch."""

    def __init__(self, session_id: str, tmux_session_name: str | None = None) -> None:
        self.session_id = session_id
        self.session = MagicMock()
        self.session.tmux_session_name = tmux_session_name


def _make_view(pending_id: str | None, nav_items: list[object], *, request_focus: bool = False) -> MagicMock:
    """Return a minimal mock that satisfies _apply_pending_selection's interface."""
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
    view = _make_view(None, [])

    with patch("teleclaude.cli.tui.views.sessions.SessionRow", _FakeSessionRow):
        SessionsView._apply_pending_selection(view)

    view.post_message.assert_not_called()
