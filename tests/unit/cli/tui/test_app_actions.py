from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from teleclaude.cli.tui import app_actions
from teleclaude.cli.tui.messages import RestartSessionsRequest


class _FakeSessionRow:
    def __init__(self) -> None:
        self.is_sticky = True


class _ActionsApp(app_actions.TelecAppActionsMixin):
    def __init__(self) -> None:
        self._post_messages: list[object] = []
        self._focused_tabs: list[str] = []
        self._after_refresh_calls = 0
        self._mapping: dict[str, SimpleNamespace] = {}
        self.notify = Mock()
        self.api = SimpleNamespace(agent_restart=AsyncMock())

    def query_one(self, selector: str, *_args: object) -> object:
        return self._mapping[selector]

    def post_message(self, message: object) -> None:
        self._post_messages.append(message)

    def call_after_refresh(self, callback: object) -> None:
        self._after_refresh_calls += 1
        if callable(callback):
            callback()

    def _focus_active_view(self, tab_id: str) -> None:
        self._focused_tabs.append(tab_id)


@pytest.mark.unit
def test_action_clear_layout_clears_preview_sticky_rows_and_doc_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _ActionsApp()
    sessions_module = __import__("teleclaude.cli.tui.views.sessions", fromlist=["SessionRow"])
    monkeypatch.setattr(sessions_module, "SessionRow", _FakeSessionRow, raising=False)
    sticky_row = _FakeSessionRow()
    sessions_view = SimpleNamespace(
        preview_session_id="session-1",
        _sticky_session_ids=["session-2"],
        _nav_items=[sticky_row, object()],
        _notify_state_changed=Mock(),
    )
    pane_bridge = SimpleNamespace(_active_doc_preview=object(), _set_preview=Mock())
    app._mapping = {"#sessions-view": sessions_view, "#pane-bridge": pane_bridge}

    app.action_clear_layout()

    assert sessions_view.preview_session_id is None
    assert sessions_view._sticky_session_ids == []
    assert sticky_row.is_sticky is False
    assert [type(message).__name__ for message in app._post_messages] == ["PreviewChanged", "StickyChanged"]
    pane_bridge._set_preview.assert_called_once_with(focus=False)
    sessions_view._notify_state_changed.assert_called_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_on_restart_sessions_request_reports_partial_failures() -> None:
    app = _ActionsApp()

    async def _restart(session_id: str) -> None:
        if session_id == "session-2":
            raise RuntimeError("boom")

    app.api.agent_restart.side_effect = _restart

    await app_actions.TelecAppActionsMixin.on_restart_sessions_request.__wrapped__(
        app,
        RestartSessionsRequest("computer-1", ["session-1", "session-2"]),
    )

    app.notify.assert_called_once()
    assert app.notify.call_args.kwargs["severity"] == "warning"


@pytest.mark.unit
def test_action_switch_tab_updates_widgets_and_posts_state_only_when_tab_changes() -> None:
    app = _ActionsApp()
    tabs = SimpleNamespace(active="sessions")
    box_tabs = SimpleNamespace(active_tab="sessions")
    app._mapping = {"#main-tabs": tabs, "#box-tab-bar": box_tabs}

    app.action_switch_tab("jobs")

    assert tabs.active == "jobs"
    assert box_tabs.active_tab == "jobs"
    assert app._focused_tabs == ["jobs"]
    assert [type(message).__name__ for message in app._post_messages] == ["StateChanged"]
    assert app._after_refresh_calls == 1
