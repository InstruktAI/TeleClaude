"""SessionsView regression tests for un-sticky -> preview behavior."""

from types import SimpleNamespace

from teleclaude.cli.tui.messages import PreviewChanged, StickyChanged
from teleclaude.cli.tui.views.interaction import TreeInteractionAction, TreeInteractionDecision
from teleclaude.cli.tui.views.sessions import SessionsView


def test_action_toggle_preview_unsticky_promotes_session_to_preview(monkeypatch) -> None:
    """Double-space un-sticky should set preview to the removed sticky session."""
    session_id = "sess-sticky"
    now = 123.0
    view = SessionsView()
    view._sticky_session_ids = [session_id]
    view.preview_session_id = "existing-preview"

    posted_messages = []
    monkeypatch.setattr(view, "post_message", posted_messages.append)
    monkeypatch.setattr(view, "_current_session_row", lambda: SimpleNamespace(session_id=session_id))
    monkeypatch.setattr(view, "_is_headless", lambda _row: False)
    monkeypatch.setattr("teleclaude.cli.tui.views.sessions.time.monotonic", lambda: now)
    monkeypatch.setattr(
        view._interaction,
        "decide_preview_action",
        lambda *_args, **_kwargs: TreeInteractionDecision(
            action=TreeInteractionAction.TOGGLE_STICKY,
            now=now,
            clear_preview=True,
        ),
    )

    view.action_toggle_preview()

    assert view._sticky_session_ids == []
    assert view.preview_session_id == session_id
    sticky_index = next(i for i, msg in enumerate(posted_messages) if isinstance(msg, StickyChanged))
    preview_index = next(i for i, msg in enumerate(posted_messages) if isinstance(msg, PreviewChanged))
    assert sticky_index < preview_index
    preview_message = posted_messages[preview_index]
    assert isinstance(preview_message, PreviewChanged)
    assert preview_message.session_id == session_id
    assert preview_message.request_focus is False


def test_double_click_unsticky_promotes_session_to_preview(monkeypatch) -> None:
    """Double-click un-sticky should set preview to the removed sticky session."""
    session_id = "sess-sticky"
    now = 456.0
    view = SessionsView()
    view._sticky_session_ids = [session_id]
    view.preview_session_id = "existing-preview"
    view._last_click_session = session_id
    view._last_click_time = now - 0.1

    posted_messages = []
    monkeypatch.setattr(view, "post_message", posted_messages.append)
    monkeypatch.setattr(view, "_find_nav_index", lambda _target: 0)
    monkeypatch.setattr("teleclaude.cli.tui.views.sessions.time.monotonic", lambda: now)

    pressed_message = SimpleNamespace(session_row=SimpleNamespace(session_id=session_id), shift=False)

    view.on_session_row_pressed(pressed_message)

    assert view._sticky_session_ids == []
    assert view.preview_session_id == session_id
    sticky_index = next(i for i, msg in enumerate(posted_messages) if isinstance(msg, StickyChanged))
    preview_index = next(i for i, msg in enumerate(posted_messages) if isinstance(msg, PreviewChanged))
    assert sticky_index < preview_index
    preview_message = posted_messages[preview_index]
    assert isinstance(preview_message, PreviewChanged)
    assert preview_message.session_id == session_id
    assert preview_message.request_focus is False
