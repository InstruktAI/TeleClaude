"""Functional test for live agent-availability event rendering."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from rich.text import Text

import teleclaude.cli.tui.app as app_mod
import teleclaude.cli.tui.state_store as state_store
from teleclaude.api_models import (
    AgentAvailabilityDTO,
    AgentAvailabilityEventDTO,
    ComputerDTO,
    ProjectWithTodosDTO,
    SessionDTO,
    TuiBootstrapDTO,
    TuiBootstrapPillar,
)
from teleclaude.cli.tui.app import TelecApp
from teleclaude.cli.tui.widgets.modals import AgentSelector
from teleclaude.cli.tui.widgets.telec_footer import TelecFooter
from tests.tui.conftest import StubPaneBridge, build_bootstrap_response

pytestmark = pytest.mark.functional

AGENT_AVAILABILITY_SPEC = "project/spec/feature/tui/agent-availability-visibility"

_ALL_AVAILABLE = {
    agent: AgentAvailabilityDTO(agent=agent, available=True, status="available")
    for agent in ("claude", "gemini", "codex")
}

_COMPUTER = ComputerDTO(name="local", status="online", is_local=True)
_PROJECT = ProjectWithTodosDTO(computer="local", name="repo", path="/repo", description=None)


class _StubAPI:
    """Stub API client: no daemon connection, bootstrap fed from `availability`."""

    def __init__(self) -> None:
        self.sessions: list[SessionDTO] = []
        self.availability: dict[str, AgentAvailabilityDTO] = dict(_ALL_AVAILABLE)
        self.projects_with_todos: list[ProjectWithTodosDTO] = [_PROJECT]
        self.computers: list[ComputerDTO] = [_COMPUTER]

    async def connect(self) -> None:
        return None

    def start_websocket(self, **_kwargs: object) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_tui_bootstrap(
        self, pillars: list[TuiBootstrapPillar], include_removed: bool = True
    ) -> TuiBootstrapDTO:
        return build_bootstrap_response(
            pillars,
            sessions=list(self.sessions),
            availability=dict(self.availability),
            projects_with_todos=list(self.projects_with_todos),
            computers=list(self.computers),
        )


def _footer_agent_pills(app: TelecApp) -> dict[str, str]:
    footer = app.query_one("#telec-footer", TelecFooter)
    return {
        agent: cast(Text, footer.query_one(f"#footer-agent-{agent}").render()).plain
        for agent in ("claude", "gemini", "codex")
    }


def _agent_selector_pills(app: TelecApp) -> str:
    selector = app.screen.query_one("#agent-selector", AgentSelector)
    return selector.render().plain


@pytest.mark.asyncio
@pytest.mark.spec(AGENT_AVAILABILITY_SPEC, "UC-TAAV-1")
async def test_live_event_leaves_other_agents_rendered_status_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: object
) -> None:
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", tmp_path / "tui_state.json")
    monkeypatch.setattr(app_mod, "PaneManagerBridge", StubPaneBridge)

    api = _StubAPI()
    app = TelecApp(api=api)
    async with app.run_test(size=(120, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()

        app._handle_ws_event(
            AgentAvailabilityEventDTO(
                data=AgentAvailabilityDTO(agent="claude", available=False, status="unavailable"),
            )
        )
        await pilot.pause()

        # Open the real "new session" agent-selection surface (SessionsView's
        # production `n` binding) to prove it reflects the live event too —
        # it is fed from the same view-level `_availability` store that
        # `sessions_view.set_availability` merges into, a separate call site
        # from the footer's. `new_session` is only enabled with a ProjectHeader
        # under cursor, so move off the bootstrap-selected ComputerHeader first.
        await pilot.press("down")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        assert {
            "footer": _footer_agent_pills(app),
            "agent_selector": _agent_selector_pills(app),
        } == snapshot
