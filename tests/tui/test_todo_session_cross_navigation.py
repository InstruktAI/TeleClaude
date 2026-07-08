"""Integration tests for todo<->session cross-navigation through TelecApp code.

The harness mounts the real tab container and both participating views, then
drives the row click handlers into the same app-level cross-navigation handlers
used by ``TelecApp``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest
from rich.style import Style
from textual.app import App, ComposeResult
from textual.events import Click
from textual.pilot import Pilot
from textual.widget import Widget
from textual.widgets import TabbedContent, TabPane

import teleclaude.cli.tui.state_store as state_store
from teleclaude.api_models import ProjectWithTodosDTO, SessionDTO, TodoDTO
from teleclaude.cli.tui.app_actions import TelecAppActionsMixin
from teleclaude.cli.tui.app_cross_nav import TelecAppCrossNavMixin
from teleclaude.cli.tui.pane_bridge import PaneManagerBridge
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.widgets.box_tab_bar import BoxTabBar
from teleclaude.cli.tui.widgets.session_row import SessionRow
from teleclaude.cli.tui.widgets.todo_row import TodoRow

pytestmark = pytest.mark.functional

XNAV_SPEC = "project/spec/feature/tui/todo-session-cross-navigation"
SESSIONS_TAB = "sessions"
PREPARATION_TAB = "preparation"

ALICE = {"name": "Alice Smith", "email": "alice@example.com", "slug": "alice-smith"}
BOB = {"name": "Bob Jones", "email": "bob@example.com", "slug": "bob-jones"}


class _CrossNavApp(TelecAppActionsMixin, TelecAppCrossNavMixin, App[None]):
    """Lean TelecApp-shaped harness for cross-view behavior."""

    def __init__(self, *, initial_tab: str) -> None:
        super().__init__()
        self.initial_tab = initial_tab

    def compose(self) -> ComposeResult:
        yield BoxTabBar(id="box-tab-bar")
        with TabbedContent(id="main-tabs", initial=self.initial_tab):
            with TabPane("Sessions", id="sessions"):
                yield SessionsView(id="sessions-view")
            with TabPane("Preparation", id="preparation"):
                yield PreparationView(id="preparation-view")
        yield _TestPaneBridge(id="pane-bridge")

    def _schedule_state_save(self) -> None:
        pass


class _TestPaneBridge(PaneManagerBridge):
    """Pane bridge shell that satisfies app tab-switch queries without tmux."""

    def __init__(self, **kwargs: object) -> None:
        Widget.__init__(self, **kwargs)
        self._active_doc_preview = None


def _todo_dto(slug: str, *, created_by_principal: str | None = None, active_runner: str | None = None) -> TodoDTO:
    return TodoDTO(
        slug=slug,
        status="active",
        has_requirements=False,
        has_impl_plan=False,
        kind="feature",
        lifecycle_phase="build_started",
        created_by_principal=created_by_principal,
        active_runner=active_runner,
    )


def _project_with(todos: list[TodoDTO]) -> ProjectWithTodosDTO:
    return ProjectWithTodosDTO(computer="local", name="proj", path="/proj", todos=todos)


def _session(session_id: str, *, working_slug: str | None = None, human_email: str | None = None) -> SessionDTO:
    return SessionDTO(
        session_id=session_id,
        title=f"/next-build {working_slug}" if working_slug else session_id,
        status="idle",
        tmux_session_name=f"tmux-{session_id}",
        active_agent="claude",
        thinking_mode="med",
        computer="local",
        project_path="/proj",
        working_slug=working_slug,
        human_email=human_email,
    )


def _todo_rows(view: PreparationView) -> list[TodoRow]:
    return [w for w in view._nav_items if isinstance(w, TodoRow)]


def _session_rows(view: SessionsView) -> list[SessionRow]:
    return [w for w in view._nav_items if isinstance(w, SessionRow)]


async def _wait_until(pilot: Pilot, predicate: Callable[[], bool], *, timeout_s: float = 5.0) -> None:
    """Poll ``predicate`` via repeated ``pilot.pause()`` until true or the timeout elapses.

    ``pilot.pause()``'s idle heuristic can return before a multi-hop message
    bubble finishes processing under CPU contention (e.g. parallel test
    workers), so a single pause is not a reliable synchronization point.
    Polling the observable condition itself is.
    """
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await pilot.pause()
    assert predicate()


def _click_row_offset(row: TodoRow | SessionRow, column: int, *, line: int = 0) -> None:
    row.on_click(
        Click(
            row,
            x=column,
            y=line,
            delta_x=0,
            delta_y=0,
            button=1,
            shift=False,
            meta=False,
            ctrl=False,
            style=Style(meta={"offset": (column, line)}),
        )
    )


@pytest.mark.asyncio
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-12")
async def test_claimed_todo_column_click_activates_sessions_tab_and_selects_runner(wire_people) -> None:
    runner = "runner-session-1"
    wire_people([ALICE, BOB])
    app = _CrossNavApp(initial_tab=PREPARATION_TAB)
    async with app.run_test(size=(140, 30)) as pilot:
        tabs = app.query_one("#main-tabs", TabbedContent)
        sessions_view = app.query_one("#sessions-view", SessionsView)
        prep_view = app.query_one("#preparation-view", PreparationView)
        sessions_view.update_data(computers=[], projects=[], sessions=[_session(runner)])
        prep_view.update_data([_project_with([_todo_dto("claimed", active_runner=runner)])])
        await pilot.pause()
        assert tabs.active == PREPARATION_TAB

        # Click the claimed todo's text column (real row hit-test).
        row = _todo_rows(prep_view)[0]
        row.render()
        assert row._claim_region is not None
        _click_row_offset(row, row._claim_region[0])
        await pilot.pause()

        # The app handler activated the Sessions tab and selected/previewed the runner session.
        assert tabs.active == SESSIONS_TAB
        assert sessions_view.preview_session_id == runner


@pytest.mark.asyncio
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-13")
async def test_session_slug_click_activates_preparation_tab_and_selects_todo(wire_people) -> None:
    slug = "config-public-surface-contract"
    wire_people([ALICE, BOB])
    app = _CrossNavApp(initial_tab=SESSIONS_TAB)
    async with app.run_test(size=(140, 30)) as pilot:
        tabs = app.query_one("#main-tabs", TabbedContent)
        sessions_view = app.query_one("#sessions-view", SessionsView)
        prep_view = app.query_one("#preparation-view", PreparationView)
        sessions_view.update_data(computers=[], projects=[], sessions=[_session("s1", working_slug=slug)])
        prep_view.update_data([_project_with([_todo_dto(slug)])])
        await pilot.pause()
        assert tabs.active == SESSIONS_TAB

        # Click the session row's highlighted work-slug span (real on_click).
        row = _session_rows(sessions_view)[0]
        row.render()
        assert row._slug_region is not None
        _click_row_offset(row, row._slug_region[0])
        await pilot.pause()

        # The app handler activated the Preparation tab and selected the todo.
        assert tabs.active == PREPARATION_TAB
        current = prep_view._current_todo_row()
        assert current is not None
        assert current.slug == slug


def _populate_owned(app: _CrossNavApp, alice_email: str) -> tuple[SessionsView, PreparationView]:
    sessions_view = app.query_one("#sessions-view", SessionsView)
    prep_view = app.query_one("#preparation-view", PreparationView)
    sessions_view.update_data(
        computers=[],
        projects=[],
        sessions=[
            _session("alice-sess", working_slug="alice-work", human_email=alice_email),
            _session("bob-sess", working_slug="bob-work", human_email="bob@example.com"),
        ],
    )
    prep_view.update_data(
        [
            _project_with(
                [
                    _todo_dto("alice-work", created_by_principal=f"human:{alice_email}"),
                    _todo_dto("bob-work", created_by_principal="human:bob@example.com"),
                ]
            )
        ]
    )
    return sessions_view, prep_view


@pytest.mark.asyncio
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-16")
async def test_chip_filter_spans_both_views_and_persists_across_restart(wire_people, tmp_path, monkeypatch) -> None:
    alice_email = "alice@example.com"
    wire_people([ALICE, BOB])
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", tmp_path / "tui_state.json")

    app = _CrossNavApp(initial_tab=PREPARATION_TAB)
    async with app.run_test(size=(140, 30)) as pilot:
        sessions_view, prep_view = _populate_owned(app, alice_email)
        await pilot.pause()

        # Click alice's chip in the Preparation view → the shared filter is set
        # through the app handler.
        alice_todo = next(r for r in _todo_rows(prep_view) if r.slug == "alice-work")
        alice_todo.render()
        assert alice_todo._chip_region is not None
        _click_row_offset(alice_todo, alice_todo._chip_region[0])
        await _wait_until(pilot, lambda: app.collect_human_filter() == alice_email)

        # Both participating views now filter against the same value.
        assert app.collect_human_filter() == alice_email
        prep_rows = {r.slug: r for r in _todo_rows(prep_view)}
        sess_rows = {r.session_id: r for r in _session_rows(sessions_view)}
        assert prep_rows["alice-work"].display is True
        assert prep_rows["bob-work"].display is False
        assert sess_rows["alice-sess"].display is True
        assert sess_rows["bob-sess"].display is False

        # Persist through the app state owner's collect helper into the one
        # shared `app` namespace.
        state_store.save_state({"app": {"active_tab": PREPARATION_TAB, "human_filter": app.collect_human_filter()}})

    # Restart: a fresh app restores the one shared filter into both views.
    app2 = _CrossNavApp(initial_tab=SESSIONS_TAB)
    async with app2.run_test(size=(140, 30)) as pilot:
        sessions_view2, prep_view2 = _populate_owned(app2, alice_email)
        await pilot.pause()
        app2.restore_human_filter(state_store.load_state()["app"])
        await pilot.pause()

        assert app2.collect_human_filter() == alice_email
        prep_rows2 = {r.slug: r for r in _todo_rows(prep_view2)}
        sess_rows2 = {r.session_id: r for r in _session_rows(sessions_view2)}
        assert prep_rows2["alice-work"].display is True
        assert prep_rows2["bob-work"].display is False
        assert sess_rows2["alice-sess"].display is True
        assert sess_rows2["bob-sess"].display is False
