"""Functional tests for session action gestures."""

from __future__ import annotations

import pytest

from teleclaude.api_models import SessionDTO
from teleclaude.cli.tui.messages import ReviveSessionRequest
from teleclaude.cli.tui.views.sessions import SessionsView
from tests.tui.test_session_row import SID, _click_row_offset, _only_row, _SessionsTestApp

pytestmark = pytest.mark.functional

SESSION_ACTIONS_SPEC = "project/spec/feature/tui/session-actions"


class _SessionActionsTestApp(_SessionsTestApp):
    def __init__(self) -> None:
        super().__init__()
        self.revive_requests: list[ReviveSessionRequest] = []

    def clear_recorded_messages(self) -> None:
        super().clear_recorded_messages()
        self.revive_requests.clear()

    def on_revive_session_request(self, message: ReviveSessionRequest) -> None:
        self.revive_requests.append(message)


def _headless_session(session_id: str) -> SessionDTO:
    return SessionDTO(
        session_id=session_id,
        title=session_id,
        status="headless",
        tmux_session_name="",
        active_agent="claude",
        computer="local",
        project_path="/proj",
    )


@pytest.mark.asyncio
@pytest.mark.spec(SESSION_ACTIONS_SPEC, "UC-SACT-1")
async def test_fast_close_headless_session_suppresses_trailing_mouse_revive() -> None:
    app = _SessionActionsTestApp()
    async with app.run_test(size=(100, 40)) as pilot:
        view = app.query_one(SessionsView)
        view.update_data(computers=[], projects=[], sessions=[_headless_session(SID)])
        await pilot.pause()

        row = _only_row(view, SID)
        _click_row_offset(row, 0, shift=True, meta=True)
        _click_row_offset(row, 0)
        await pilot.pause()

    assert [request.session_id for request in app.kill_requests] == [SID]
    assert [request.session_id for request in app.revive_requests] == []
