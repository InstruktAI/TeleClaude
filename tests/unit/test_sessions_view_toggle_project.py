"""Unit tests for SessionsView.action_toggle_project_sessions (the 'a' key)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

from teleclaude.cli.tui.messages import PreviewChanged, StickyChanged
from teleclaude.cli.tui.views.sessions import MAX_STICKY, SessionsView
from teleclaude.cli.tui.widgets.project_header import ProjectHeader


def _make_project_header(path: str = "/proj/foo", computer: str = "local") -> ProjectHeader:
    from teleclaude.cli.models import ProjectInfo

    return ProjectHeader(project=ProjectInfo(path=path, computer=computer, name="foo"))


def _make_session(
    session_id: str,
    project_path: str = "/proj/foo",
    computer: str | None = "local",
    tmux_session_name: str | None = "tmux-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        session_id=session_id,
        project_path=project_path,
        computer=computer,
        tmux_session_name=tmux_session_name,
    )


def test_toggle_on_makes_project_sessions_sticky(monkeypatch) -> None:
    """'a' on a project with no sticky sessions makes first MAX_STICKY sessions sticky."""
    header = _make_project_header()
    sessions = [
        _make_session("s1"),
        _make_session("s2"),
        _make_session("s3"),
    ]
    view = SessionsView()
    view._sessions = sessions  # type: ignore[assignment]
    view._sticky_session_ids = []
    view._nav_items = []

    posted_messages: list[object] = []
    monkeypatch.setattr(view, "post_message", posted_messages.append)
    monkeypatch.setattr(view, "_current_item", lambda: header)
    monkeypatch.setattr(view, "_notify_state_changed", lambda: None)

    view.action_toggle_project_sessions()

    assert view._sticky_session_ids == ["s1", "s2", "s3"]
    assert any(isinstance(m, StickyChanged) for m in posted_messages)
    changed = next(m for m in posted_messages if isinstance(m, StickyChanged))
    assert changed.session_ids == ["s1", "s2", "s3"]


def test_toggle_off_removes_all_project_sticky_sessions(monkeypatch) -> None:
    """'a' on a project that already has sticky sessions removes them all."""
    header = _make_project_header()
    sessions = [_make_session("s1"), _make_session("s2")]
    view = SessionsView()
    view._sessions = sessions  # type: ignore[assignment]
    view._sticky_session_ids = ["s1", "s2"]
    view._nav_items = []

    posted_messages: list[object] = []
    monkeypatch.setattr(view, "post_message", posted_messages.append)
    monkeypatch.setattr(view, "_current_item", lambda: header)
    monkeypatch.setattr(view, "_notify_state_changed", lambda: None)

    view.action_toggle_project_sessions()

    assert view._sticky_session_ids == []
    assert any(isinstance(m, StickyChanged) for m in posted_messages)


def test_toggle_off_clears_preview_when_in_project(monkeypatch) -> None:
    """'a' toggle-off clears the preview pane if it belongs to the project."""
    header = _make_project_header()
    sessions = [_make_session("s1")]
    view = SessionsView()
    view._sessions = sessions  # type: ignore[assignment]
    view._sticky_session_ids = ["s1"]
    view.preview_session_id = "s1"
    view._nav_items = []

    posted_messages: list[object] = []
    monkeypatch.setattr(view, "post_message", posted_messages.append)
    monkeypatch.setattr(view, "_current_item", lambda: header)
    monkeypatch.setattr(view, "_notify_state_changed", lambda: None)

    view.action_toggle_project_sessions()

    assert view.preview_session_id is None
    preview_msgs = [m for m in posted_messages if isinstance(m, PreviewChanged)]
    assert preview_msgs, "PreviewChanged(None) should be posted"
    assert preview_msgs[0].session_id is None
    assert preview_msgs[0].request_focus is False


def test_toggle_off_does_not_clear_preview_outside_project(monkeypatch) -> None:
    """'a' toggle-off preserves the preview if it belongs to a different project."""
    header = _make_project_header()
    sessions = [_make_session("s1")]
    view = SessionsView()
    view._sessions = sessions  # type: ignore[assignment]
    view._sticky_session_ids = ["s1"]
    view.preview_session_id = "other-session"
    view._nav_items = []

    posted_messages: list[object] = []
    monkeypatch.setattr(view, "post_message", posted_messages.append)
    monkeypatch.setattr(view, "_current_item", lambda: header)
    monkeypatch.setattr(view, "_notify_state_changed", lambda: None)

    view.action_toggle_project_sessions()

    assert view.preview_session_id == "other-session"
    assert not any(isinstance(m, PreviewChanged) for m in posted_messages)


def test_toggle_on_respects_max_sticky_limit(monkeypatch) -> None:
    """'a' toggle-on only adds sessions up to the global MAX_STICKY limit."""
    header = _make_project_header()
    # Create more sessions than MAX_STICKY
    sessions = [_make_session(f"s{i}") for i in range(MAX_STICKY + 2)]
    view = SessionsView()
    view._sessions = sessions  # type: ignore[assignment]
    view._sticky_session_ids = []
    view._nav_items = []

    notify_calls: list[tuple[str, str]] = []
    mock_app = SimpleNamespace(notify=lambda msg, severity="info": notify_calls.append((msg, severity)))  # type: ignore[misc]

    posted_messages: list[object] = []
    monkeypatch.setattr(view, "post_message", posted_messages.append)
    monkeypatch.setattr(view, "_current_item", lambda: header)
    monkeypatch.setattr(view, "_notify_state_changed", lambda: None)

    with patch.object(type(view), "app", new_callable=PropertyMock, return_value=mock_app):
        view.action_toggle_project_sessions()

    assert len(view._sticky_session_ids) == MAX_STICKY
    # Should have notified about truncation
    assert any("max" in msg.lower() for msg, _ in notify_calls)


def test_toggle_on_skips_headless_sessions(monkeypatch) -> None:
    """'a' toggle-on skips sessions without a tmux_session_name."""
    header = _make_project_header()
    sessions = [
        _make_session("headless-1", tmux_session_name=None),
        _make_session("attachable-1", tmux_session_name="tmux-1"),
    ]
    view = SessionsView()
    view._sessions = sessions  # type: ignore[assignment]
    view._sticky_session_ids = []
    view._nav_items = []

    posted_messages: list[object] = []
    monkeypatch.setattr(view, "post_message", posted_messages.append)
    monkeypatch.setattr(view, "_current_item", lambda: header)
    monkeypatch.setattr(view, "_notify_state_changed", lambda: None)

    view.action_toggle_project_sessions()

    assert view._sticky_session_ids == ["attachable-1"]


def test_toggle_on_no_eligible_sessions_notifies(monkeypatch) -> None:
    """'a' toggle-on with no tmux sessions shows a warning and makes no changes."""
    header = _make_project_header()
    sessions = [_make_session("headless-1", tmux_session_name=None)]
    view = SessionsView()
    view._sessions = sessions  # type: ignore[assignment]
    view._sticky_session_ids = []
    view._nav_items = []

    notify_calls: list[tuple[str, str]] = []
    mock_app = SimpleNamespace(notify=lambda msg, severity="info": notify_calls.append((msg, severity)))  # type: ignore[misc]

    posted_messages: list[object] = []
    monkeypatch.setattr(view, "post_message", posted_messages.append)
    monkeypatch.setattr(view, "_current_item", lambda: header)
    monkeypatch.setattr(view, "_notify_state_changed", lambda: None)

    with patch.object(type(view), "app", new_callable=PropertyMock, return_value=mock_app):
        view.action_toggle_project_sessions()

    assert view._sticky_session_ids == []
    assert not any(isinstance(m, StickyChanged) for m in posted_messages)
    assert any("no attachable" in msg.lower() for msg, _ in notify_calls)


def test_toggle_ignores_non_project_node(monkeypatch) -> None:
    """'a' on a non-ProjectHeader node does nothing."""
    view = SessionsView()
    view._sessions = []  # type: ignore[assignment]
    view._sticky_session_ids = []
    view._nav_items = []

    posted_messages: list[object] = []
    monkeypatch.setattr(view, "post_message", posted_messages.append)
    monkeypatch.setattr(view, "_current_item", lambda: SimpleNamespace())
    monkeypatch.setattr(view, "_notify_state_changed", lambda: None)

    view.action_toggle_project_sessions()

    assert view._sticky_session_ids == []
    assert not posted_messages


def test_toggle_on_only_matches_project_and_computer(monkeypatch) -> None:
    """'a' only affects sessions on the same project+computer as the header."""
    header = _make_project_header(path="/proj/foo", computer="local")
    sessions = [
        _make_session("same-project", project_path="/proj/foo", computer="local"),
        _make_session("other-project", project_path="/proj/bar", computer="local"),
        _make_session("other-computer", project_path="/proj/foo", computer="remote"),
    ]
    view = SessionsView()
    view._sessions = sessions  # type: ignore[assignment]
    view._sticky_session_ids = []
    view._nav_items = []

    posted_messages: list[object] = []
    monkeypatch.setattr(view, "post_message", posted_messages.append)
    monkeypatch.setattr(view, "_current_item", lambda: header)
    monkeypatch.setattr(view, "_notify_state_changed", lambda: None)

    view.action_toggle_project_sessions()

    assert view._sticky_session_ids == ["same-project"]
