"""Regression tests for optimistic kill reconciliation in SessionsView."""

from teleclaude.cli.models import ComputerInfo, ProjectInfo, SessionInfo
from teleclaude.cli.tui.messages import PreviewChanged, StickyChanged
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.core.origins import InputOrigin


def _computer() -> ComputerInfo:
    return ComputerInfo(
        name="local",
        status="online",
        user="tester",
        host="localhost",
        is_local=True,
        tmux_binary="tmux",
    )


def _project() -> ProjectInfo:
    return ProjectInfo(computer="local", name="project", path="/tmp/project", description=None)


def _session(session_id: str, *, status: str = "active", title: str = "Session") -> SessionInfo:
    return SessionInfo(
        session_id=session_id,
        last_input_origin=InputOrigin.TELEGRAM.value,
        title=title,
        project_path="/tmp/project",
        thinking_mode="slow",
        active_agent=None,
        status=status,
        created_at=None,
        last_activity=None,
        last_input=None,
        last_input_at=None,
        last_output_summary=None,
        last_output_summary_at=None,
        tmux_session_name="tc_test",
        initiator_session_id=None,
        computer="local",
    )


def test_optimistically_hide_session_removes_row_and_prunes_view_state(monkeypatch) -> None:
    """A successful local kill should hide the session immediately and clear preview/sticky state."""
    view = SessionsView()
    monkeypatch.setattr(view, "_rebuild_tree", lambda: None)
    view._computers = [_computer()]
    view._projects = [_project()]
    target = _session("sess-1")
    other = _session("sess-2", title="Other")
    view.update_data(view._computers, view._projects, [target, other])
    view.preview_session_id = "sess-1"
    view._sticky_session_ids = ["sess-1"]

    posted = []
    monkeypatch.setattr(view, "post_message", posted.append)

    view.optimistically_hide_session("sess-1")

    assert "sess-1" in view._optimistically_hidden_session_ids
    assert [session.session_id for session in view._sessions] == ["sess-2"]
    assert view.preview_session_id is None
    assert view._sticky_session_ids == []
    assert any(isinstance(message, PreviewChanged) for message in posted)
    assert any(isinstance(message, StickyChanged) for message in posted)


def test_update_data_reveals_hidden_session_when_authoritative_snapshot_keeps_it() -> None:
    """A later authoritative snapshot should re-show a session that did not actually disappear."""
    view = SessionsView()
    view._rebuild_tree = lambda: None
    view._computers = [_computer()]
    view._projects = [_project()]
    hidden = _session("sess-1")
    other = _session("sess-2", title="Other")
    view.update_data(view._computers, view._projects, [hidden, other])

    view.optimistically_hide_session("sess-1")
    view.update_data(view._computers, view._projects, [hidden, other])

    assert "sess-1" not in view._optimistically_hidden_session_ids
    assert {session.session_id for session in view._sessions} == {"sess-1", "sess-2"}


def test_update_data_keeps_hidden_session_hidden_while_snapshot_says_closing() -> None:
    """A closing snapshot should keep an optimistically hidden session off-screen."""
    view = SessionsView()
    view._rebuild_tree = lambda: None
    view._computers = [_computer()]
    view._projects = [_project()]
    hidden = _session("sess-1")
    other = _session("sess-2", title="Other")
    view.update_data(view._computers, view._projects, [hidden, other])

    view.optimistically_hide_session("sess-1")
    view.update_data(view._computers, view._projects, [_session("sess-1", status="closing"), other])

    assert "sess-1" in view._optimistically_hidden_session_ids
    assert [session.session_id for session in view._sessions] == ["sess-2"]


def test_update_session_reveals_hidden_session_on_active_update() -> None:
    """An active session update should reinsert a session hidden optimistically."""
    view = SessionsView()
    view._rebuild_tree = lambda: None
    view._computers = [_computer()]
    view._projects = [_project()]
    hidden = _session("sess-1")
    view.update_data(view._computers, view._projects, [hidden])

    view.optimistically_hide_session("sess-1")
    view.update_session(_session("sess-1", status="active", title="Recovered"))

    assert "sess-1" not in view._optimistically_hidden_session_ids
    assert len(view._sessions) == 1
    assert view._sessions[0].session_id == "sess-1"
    assert view._sessions[0].title == "Recovered"
