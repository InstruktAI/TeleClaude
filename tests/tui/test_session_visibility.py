"""Functional tests for push-driven authoritative session reconciliation."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

import teleclaude.cli.tui.app as app_mod
import teleclaude.cli.tui.state_store as state_store
from teleclaude.api_models import (
    SessionDTO,
    SessionLifecycleStatusEventDTO,
    SessionsInitialDataDTO,
    SessionsInitialEventDTO,
    TuiBootstrapDTO,
    TuiBootstrapPillar,
)
from teleclaude.cli.tui.app import TelecApp
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.config import config
from tests.tui.conftest import StubPaneBridge, build_bootstrap_response

pytestmark = pytest.mark.functional

SESSION_VISIBILITY_SPEC = "project/spec/feature/tui/session-visibility"


class _StubAPI:
    """Stub API client: no daemon connection, bootstrap fed from `sessions`."""

    def __init__(self) -> None:
        self.sessions: list[SessionDTO] = []
        self.bootstrap_requests: list[list[TuiBootstrapPillar]] = []

    async def connect(self) -> None:
        return None

    def start_websocket(self, **_kwargs: object) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_tui_bootstrap(
        self, pillars: list[TuiBootstrapPillar], include_removed: bool = True
    ) -> TuiBootstrapDTO:
        self.bootstrap_requests.append(list(pillars))
        return build_bootstrap_response(pillars, sessions=list(self.sessions))


def _session(session_id: str) -> SessionDTO:
    return SessionDTO(
        session_id=session_id,
        title=session_id,
        status="active",
        created_at="2026-07-06T19:05:42",
        project_path="/repo",
        computer=config.computer.name,
    )


def _session_ids(view: SessionsView) -> set[str]:
    return {session.session_id for session in view._sessions}


@pytest.mark.asyncio
@pytest.mark.spec(SESSION_VISIBILITY_SPEC, "UC-SVIS-1")
async def test_reconnect_snapshot_surfaces_a_session_missed_by_live_delivery_without_pull(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", tmp_path / "tui_state.json")
    monkeypatch.setattr(app_mod, "PaneManagerBridge", StubPaneBridge)

    api = _StubAPI()
    app = TelecApp(api=api)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        sessions_view = app.query_one("#sessions-view", SessionsView)
        assert _session_ids(sessions_view) == set()
        assert len(api.bootstrap_requests) == 1

        # The session is active in the authoritative store but was never
        # delivered as a live event to this TUI (websocket down at
        # activation, per the diagnosed cause).
        missed = _session("699afee6-966e-45be-8aa3-cf04a7e564ce")
        app._handle_ws_connected()
        app._handle_ws_event(
            SessionsInitialEventDTO(
                data=SessionsInitialDataDTO(sessions=[missed], computer="local"),
            )
        )
        await pilot.pause()
        await app.workers.wait_for_complete()

        assert missed.session_id in _session_ids(sessions_view)
        assert len(sessions_view._sessions) == 1
        assert len(api.bootstrap_requests) == 1


@pytest.mark.asyncio
@pytest.mark.spec(SESSION_VISIBILITY_SPEC, "UC-SVIS-3")
async def test_pushed_close_error_triggers_targeted_sessions_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", tmp_path / "tui_state.json")
    monkeypatch.setattr(app_mod, "PaneManagerBridge", StubPaneBridge)

    api = _StubAPI()
    app = TelecApp(api=api)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert len(api.bootstrap_requests) == 1

        app._handle_ws_event(
            SessionLifecycleStatusEventDTO(
                session_id="session-1",
                status="error",
                reason="close_failed",
                timestamp="2026-07-21T12:00:00Z",
            )
        )
        await pilot.pause()
        await app.workers.wait_for_complete()

        assert len(api.bootstrap_requests) == 2
        assert api.bootstrap_requests[-1] == ["sessions"]


@pytest.mark.asyncio
@pytest.mark.spec(SESSION_VISIBILITY_SPEC, "UC-SVIS-2")
async def test_pre_activation_session_is_visible_in_authoritative_bootstrap(
    api: AsyncClient, cluster_event_bus: None
) -> None:
    """A session whose startup never completed is still in the authoritative set.

    Seeds one open row per lifecycle status the store can hold, then reads the
    same route the TUI reads at startup (``GET /tui/bootstrap``) and
    asserts the returned ids are exactly the "active" and "initializing" rows
    — proving both that the regression is fixed and that the fix does not
    over-widen to "closing" or "escalated" rows.
    """
    del cluster_event_bus
    seeded_ids: dict[str, str] = {}
    for status in ("active", "initializing", "closing", "escalated"):
        session = await api.db.create_session(
            computer_name="TestComputer",
            tmux_session_name=f"tc-{status}",
            last_input_origin="terminal",
            title=status,
            lifecycle_status=status,
            emit_session_started=False,
        )
        seeded_ids[status] = session.session_id

    closed = await api.db.create_session(
        computer_name="TestComputer",
        tmux_session_name="tc-closed",
        last_input_origin="terminal",
        title="closed",
        lifecycle_status="active",
        emit_session_started=False,
    )
    await api.db.close_session(closed.session_id)

    response = await api.get("/tui/bootstrap", params={"pillars": "sessions"})
    assert response.status_code == 200

    bootstrap = TuiBootstrapDTO.model_validate(response.json())
    returned_ids = {session.session_id for session in bootstrap.data.sessions or []}

    assert returned_ids == {seeded_ids["active"], seeded_ids["initializing"]}
