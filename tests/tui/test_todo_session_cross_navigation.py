"""Integration tests for todo<->session cross-navigation through TelecApp code.

The harness mounts the real tab container and both participating views, then
drives the row click handlers into the same app-level cross-navigation handlers
used by ``TelecApp``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import Response
from rich.style import Style
from rich.text import Span, Text
from textual.app import App, ComposeResult
from textual.events import Click
from textual.pilot import Pilot
from textual.widget import Widget
from textual.widgets import TabbedContent, TabPane

import teleclaude.cli.tui.app as app_mod
import teleclaude.cli.tui.state_store as state_store
import teleclaude.cli.tui.widgets.todo_creation_record_row as creator_row_mod
import teleclaude.cli.tui.widgets.todo_row as todo_row_mod
from teleclaude.api_models import (
    ChiptunesStatusDTO,
    ProjectWithTodosDTO,
    SessionDTO,
    SettingsDTO,
    TodoDTO,
    TTSSettingsDTO,
    TuiBootstrapDataDTO,
    TuiBootstrapDTO,
    TuiBootstrapPillar,
)
from teleclaude.cli.api_client import APIError, TelecAPIClient
from teleclaude.cli.tui.app import TelecApp
from teleclaude.cli.tui.app_actions import TelecAppActionsMixin
from teleclaude.cli.tui.app_cross_nav import TelecAppCrossNavMixin
from teleclaude.cli.tui.creator_session import CreatorSessionInfo
from teleclaude.cli.tui.pane_bridge import PaneManagerBridge
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.widgets.box_tab_bar import BoxTabBar
from teleclaude.cli.tui.widgets.session_row import SessionRow
from teleclaude.cli.tui.widgets.todo_creation_record_row import CreatorSessionRow
from teleclaude.cli.tui.widgets.todo_row import TodoRow
from tests.tui.conftest import (
    PILLAR_AVAILABILITY,
    PILLAR_CHIPTUNES,
    PILLAR_COMPUTERS,
    PILLAR_JOBS,
    PILLAR_PROJECTS,
    PILLAR_SESSIONS,
    PILLAR_SETTINGS,
    StubPaneBridge,
)

pytestmark = pytest.mark.functional

XNAV_SPEC = "project/spec/feature/tui/todo-session-cross-navigation"
SESSIONS_TAB = "sessions"
PREPARATION_TAB = "preparation"

ALICE = {"name": "Alice Smith", "email": "alice@example.com", "slug": "alice-smith"}
BOB = {"name": "Bob Jones", "email": "bob@example.com", "slug": "bob-jones"}


class _FakeReviveApi:
    """Fake API surface for the revive-and-navigate action handler (Task 4)."""

    def __init__(self, *, session_id: str = "creator-1", status: str = "success", error: str | None = None) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self._session_id = session_id
        self._status = status
        self._error = error

    async def revive_session(self, session_id: str, *, computer: str | None = None) -> SimpleNamespace:
        self.calls.append((session_id, computer))
        return SimpleNamespace(status=self._status, session_id=self._session_id, error=self._error)


class _CrossNavApp(TelecAppActionsMixin, TelecAppCrossNavMixin, App[None]):
    """Lean TelecApp-shaped harness for cross-view behavior."""

    def __init__(self, *, initial_tab: str) -> None:
        super().__init__()
        self.initial_tab = initial_tab
        self.api = _FakeReviveApi()
        self._tui_initiated_sessions: set[str] = set()
        self.refreshed_pillars: list[list[str] | None] = []

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

    def _refresh_data(self, pillars: list[str] | None = None) -> None:
        self.refreshed_pillars.append(pillars)


class _TestPaneBridge(PaneManagerBridge):
    """Pane bridge shell that satisfies app tab-switch queries without tmux."""

    def __init__(self, **kwargs: object) -> None:
        Widget.__init__(self, **kwargs)
        self._active_doc_preview = None


def _todo_dto(slug: str, *, lineage: str | None = None, active_runner: str | None = None) -> TodoDTO:
    return TodoDTO(
        slug=slug,
        status="active",
        has_requirements=False,
        has_impl_plan=False,
        kind="feature",
        lifecycle_phase="build_started",
        lineage=lineage,
        active_runner=active_runner,
    )


def _project_with(todos: list[TodoDTO]) -> ProjectWithTodosDTO:
    return ProjectWithTodosDTO(computer="local", name="proj", path="/proj", todos=todos)


def _session(
    session_id: str,
    *,
    working_slug: str | None = None,
    human_email: str | None = None,
    native_session_id: str | None = None,
) -> SessionDTO:
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
        native_session_id=native_session_id,
    )


def _span_over(rendered: Text, text: str) -> Span | None:
    """Return the exact-bounds span covering ``text``, or None if no span matches those bounds.

    An exact ``start == pos`` / ``end == pos + len(text)`` match — rather than
    a span that merely overlaps ``text`` — is itself the proof that the styled
    region carries no leading or trailing whitespace: a span padded with an
    adjacent space would not line up with ``text``'s own bounds.
    """
    pos = rendered.plain.index(text)
    for span in rendered._spans:
        if span.start == pos and span.end == pos + len(text):
            return span
    return None


def _is_bold(span: Span) -> bool:
    """Return whether a span's style is bold. Guards the Rich `str | Style` union."""
    return isinstance(span.style, Style) and bool(span.style.bold)


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
        await _wait_until(pilot, lambda: tabs.active == SESSIONS_TAB and sessions_view.preview_session_id == runner)

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
        await _wait_until(pilot, lambda: tabs.active == PREPARATION_TAB)

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
                    _todo_dto("alice-work", lineage=f"human:{alice_email}"),
                    _todo_dto("bob-work", lineage="human:bob@example.com"),
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


def _creation_todo(slug: str, *, entry_point: str | None, human_involved: bool) -> TodoItem:
    return TodoItem(
        slug=slug,
        status=TodoStatus.IN_PROGRESS,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        kind="feature",
        lifecycle_phase=None,
        entry_point=entry_point,
        human_involved=human_involved,
    )


@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-19")
def test_autonomous_marker_renders_only_for_no_human_agent_creation() -> None:
    items = [
        _creation_todo("agent-alone", entry_point="agent", human_involved=False),
        _creation_todo("agent-with-human", entry_point="agent", human_involved=True),
        _creation_todo("tui-filed", entry_point="tui", human_involved=False),
    ]
    rendered = {
        item.slug: TodoRow(item, slug_width=len(item.slug), col_widths=TodoRow.compute_col_widths([item]))
        .render()
        .plain
        for item in items
    }

    marker = todo_row_mod._AUTONOMOUS_ICON
    assert marker in rendered["agent-alone"]
    assert marker not in rendered["agent-with-human"]
    # A declared entry point other than "agent" never carries the marker, even with
    # no human involved — the undeclared-human signal alone does not qualify.
    assert marker not in rendered["tui-filed"]


def _expanded_creator_row(prep_view: PreparationView, slug: str) -> CreatorSessionRow:
    row = next(r for r in _todo_rows(prep_view) if r.slug == slug)
    prep_view._expand_todo(row)
    [creator_row] = [w for w in prep_view._nav_items if isinstance(w, CreatorSessionRow) and w.slug == slug]
    return creator_row


@pytest.mark.asyncio
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-20")
async def test_creator_row_renders_only_when_lineage_carries_acting_session(wire_people, snapshot) -> None:
    session_id = "creator-1"
    wire_people([ALICE, BOB])
    app = _CrossNavApp(initial_tab=PREPARATION_TAB)
    async with app.run_test(size=(140, 30)) as pilot:
        prep_view = app.query_one("#preparation-view", PreparationView)
        prep_view.update_data(
            [
                _project_with(
                    [
                        _todo_dto("with-session", lineage=f"human:alice@example.com>session:{session_id}"),
                        _todo_dto("no-session", lineage="human:alice@example.com"),
                    ]
                )
            ],
            creator_session_lookup={session_id: CreatorSessionInfo(status="live", computer="local")},
        )
        await pilot.pause()

        with_row = next(r for r in _todo_rows(prep_view) if r.slug == "with-session")
        assert not any(isinstance(w, CreatorSessionRow) and w.slug == "with-session" for w in prep_view._nav_items)

        prep_view._expand_todo(with_row)
        await pilot.pause()
        [creator_row] = [
            w for w in prep_view._nav_items if isinstance(w, CreatorSessionRow) and w.slug == "with-session"
        ]
        assert creator_row.state.session_id == session_id
        # The full rendered line is pinned by snapshot — the strongest available
        # proof that nothing beyond the TeleClaude session id is ever rendered
        # (no native id, no raw lineage/`session:`-prefixed encoding).
        rendered = creator_row.render()
        assert rendered.plain == snapshot

        prep_view._collapse_todo(with_row)
        await pilot.pause()
        assert not any(isinstance(w, CreatorSessionRow) and w.slug == "with-session" for w in prep_view._nav_items)

        no_session_row = next(r for r in _todo_rows(prep_view) if r.slug == "no-session")
        prep_view._expand_todo(no_session_row)
        await pilot.pause()
        assert not any(isinstance(w, CreatorSessionRow) and w.slug == "no-session" for w in prep_view._nav_items)


@pytest.mark.asyncio
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-21")
async def test_live_creator_session_click_jumps_to_sessions_tab(wire_people, snapshot) -> None:
    session_id = "creator-1"
    native_session_id = "native-should-never-render"
    wire_people([ALICE, BOB])
    app = _CrossNavApp(initial_tab=PREPARATION_TAB)
    async with app.run_test(size=(140, 30)) as pilot:
        tabs = app.query_one("#main-tabs", TabbedContent)
        sessions_view = app.query_one("#sessions-view", SessionsView)
        prep_view = app.query_one("#preparation-view", PreparationView)
        sessions_view.update_data(
            computers=[], projects=[], sessions=[_session(session_id, native_session_id=native_session_id)]
        )
        prep_view.update_data(
            [_project_with([_todo_dto("agent-work", lineage=f"human:alice@example.com>session:{session_id}")])],
            creator_session_lookup={session_id: CreatorSessionInfo(status="live", computer="local")},
        )
        await pilot.pause()

        creator_row = _expanded_creator_row(prep_view, "agent-work")
        rendered = creator_row.render()
        # RV: the snapshot pins the exact rendered line — the strongest
        # available proof that only the TeleClaude session id appears, never
        # the session's (unrelated) native id.
        assert rendered.plain == snapshot

        # RV: the live session id is the entire bold span, with no leading or
        # trailing whitespace folded into the styled region.
        id_span = _span_over(rendered, session_id)
        assert id_span is not None
        assert _is_bold(id_span)

        assert creator_row._click_region is not None
        _click_row_offset(creator_row, creator_row._click_region[0])
        await _wait_until(pilot, lambda: tabs.active == SESSIONS_TAB and sessions_view.preview_session_id == session_id)

        assert tabs.active == SESSIONS_TAB
        assert sessions_view.preview_session_id == session_id


@pytest.mark.asyncio
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-22")
async def test_retained_closed_creator_session_revive_navigates_to_revived_session(wire_people, snapshot) -> None:
    session_id = "creator-1"
    computer = "local"
    native_session_id = "native-should-never-render"
    wire_people([ALICE, BOB])
    app = _CrossNavApp(initial_tab=PREPARATION_TAB)
    async with app.run_test(size=(140, 30)) as pilot:
        tabs = app.query_one("#main-tabs", TabbedContent)
        sessions_view = app.query_one("#sessions-view", SessionsView)
        prep_view = app.query_one("#preparation-view", PreparationView)
        prep_view.update_data(
            [_project_with([_todo_dto("agent-work", lineage=f"human:alice@example.com>session:{session_id}")])],
            creator_session_lookup={session_id: CreatorSessionInfo(status="closed", computer=computer)},
        )
        await pilot.pause()

        creator_row = _expanded_creator_row(prep_view, "agent-work")
        rendered = creator_row.render()
        # RV: the snapshot pins the exact rendered line — only the TeleClaude
        # session id appears, never the session's (unrelated) native id.
        assert rendered.plain == snapshot

        # RV: only the "revive" label is bold and carries no adjacent
        # whitespace in its styled span — the id and separator stay normal weight.
        revive_span = _span_over(rendered, creator_row_mod._REVIVE_LABEL)
        assert revive_span is not None
        assert _is_bold(revive_span)
        id_span = _span_over(rendered, session_id)
        assert id_span is None or not _is_bold(id_span)

        assert creator_row._click_region is not None
        _click_row_offset(creator_row, creator_row._click_region[0])
        await _wait_until(pilot, lambda: bool(app.api.calls))

        # The revive call targets the retained session on its owning computer.
        assert app.api.calls == [(session_id, computer)]

        # Once revived, the app switches to the Sessions tab and waits until the
        # revived session becomes attachable before selecting/previewing it.
        sessions_view.update_data(
            computers=[], projects=[], sessions=[_session(session_id, native_session_id=native_session_id)]
        )
        await _wait_until(pilot, lambda: tabs.active == SESSIONS_TAB and sessions_view.preview_session_id == session_id)
        assert tabs.active == SESSIONS_TAB
        assert sessions_view.preview_session_id == session_id

        # The creator-session lookup is refreshed so the row transitions out of
        # the retained-closed state.
        assert app.refreshed_pillars and app.refreshed_pillars[-1] == ["sessions"]


@pytest.mark.asyncio
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-22")
async def test_api_client_list_sessions_sends_route_accepted_closed_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`list_sessions(include_closed=True)` must send the query alias `/sessions`
    actually parses (`closed=true`), not `include_closed=true` — otherwise
    retained closed sessions never reach the TUI creator-session lookup that
    this scenario's retained-closed revive affordance depends on."""
    calls: list[tuple[str, str, dict[str, str] | None]] = []
    client = TelecAPIClient()

    async def request(
        method: str,
        path: str,
        *,
        timeout: float | None = None,
        request_options: object | None = None,
    ) -> Response:
        del timeout
        params = getattr(request_options, "params", None)
        calls.append((method, path, params))
        return Response(200, json=[])

    monkeypatch.setattr(client, "_request", request)

    await client.list_sessions(include_closed=True)

    assert calls == [("GET", "/sessions", {"closed": "true"})]


class _FlakyCreatorLookupAPI:
    """Stub API whose `list_sessions` succeeds once, then fails.

    Proves the visible creator-session row — not just the internal lookup
    dict — survives a failed refresh instead of going inert on a transient
    daemon hiccup. Serves a fixed project/todo for the bootstrap's "projects"
    pillar so a real `CreatorSessionRow` can be expanded and inspected.
    """

    def __init__(self, *, project: ProjectWithTodosDTO) -> None:
        self.list_sessions_calls = 0
        self._project = project

    async def connect(self) -> None:
        return None

    def start_websocket(self, **_kwargs: object) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_tui_bootstrap(
        self, pillars: list[TuiBootstrapPillar], include_removed: bool = True
    ) -> TuiBootstrapDTO:
        requested = set(pillars)
        data = TuiBootstrapDataDTO(
            computers=[] if PILLAR_COMPUTERS in requested else None,
            projects_with_todos=[self._project] if PILLAR_PROJECTS in requested else None,
            sessions=[] if PILLAR_SESSIONS in requested else None,
            availability={} if PILLAR_AVAILABILITY in requested else None,
            jobs=[] if PILLAR_JOBS in requested else None,
            settings=SettingsDTO(tts=TTSSettingsDTO()) if PILLAR_SETTINGS in requested else None,
            chiptunes=ChiptunesStatusDTO() if PILLAR_CHIPTUNES in requested else None,
        )
        return TuiBootstrapDTO(requested=list(pillars), data=data)

    async def list_sessions(self, computer: str | None = None, *, include_closed: bool = False) -> list[SessionDTO]:
        self.list_sessions_calls += 1
        if self.list_sessions_calls == 1:
            return [
                SessionDTO(
                    session_id="creator-1",
                    title="creator-1",
                    status="idle",
                    closed_at="2026-01-01T00:00:00+00:00",
                    computer="local",
                )
            ]
        raise APIError("Connection to API server interrupted mid-request. Daemon may be restarting.")


@pytest.mark.asyncio
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-22")
async def test_periodic_reconciliation_reuses_creator_session_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wire_people
) -> None:
    """Periodic live reconciliation never rescans retained session history."""
    wire_people([ALICE, BOB])
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", tmp_path / "tui_state.json")
    monkeypatch.setattr(app_mod, "PaneManagerBridge", StubPaneBridge)

    session_id = "creator-1"
    project = _project_with([_todo_dto("agent-work", lineage=f"human:alice@example.com>session:{session_id}")])
    api = _FlakyCreatorLookupAPI(project=project)
    app = TelecApp(api=api)

    async with app.run_test(size=(120, 40)) as pilot:

        async def _lookup_calls(count: int) -> None:
            while api.list_sessions_calls < count:
                await pilot.pause()

        await asyncio.wait_for(_lookup_calls(1), timeout=2.0)
        await app.workers.wait_for_complete()

        prep_view = app.query_one("#preparation-view", PreparationView)
        creator_row = _expanded_creator_row(prep_view, "agent-work")
        revive_span = _span_over(creator_row.render(), creator_row_mod._REVIVE_LABEL)
        assert revive_span is not None
        assert _is_bold(revive_span)
        assert creator_row._click_region is not None

        # The 10-second reconciliation path refreshes only live sessions. It must
        # not enumerate the retained closed-session history again.
        app._refresh_data(["sessions"])
        await app.workers.wait_for_complete()
        assert api.list_sessions_calls == 1

        # The visible row remains mounted from the retained lookup.
        [creator_row_after] = [
            w for w in prep_view._nav_items if isinstance(w, CreatorSessionRow) and w.slug == "agent-work"
        ]
        revive_span_after = _span_over(creator_row_after.render(), creator_row_mod._REVIVE_LABEL)
        assert revive_span_after is not None
        assert _is_bold(revive_span_after)
        assert creator_row_after._click_region is not None


@pytest.mark.asyncio
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-23")
async def test_hard_deleted_creator_session_renders_inert_text(wire_people, snapshot) -> None:
    session_id = "gone-1"
    wire_people([ALICE, BOB])
    app = _CrossNavApp(initial_tab=PREPARATION_TAB)
    async with app.run_test(size=(140, 30)) as pilot:
        prep_view = app.query_one("#preparation-view", PreparationView)
        prep_view.update_data(
            [_project_with([_todo_dto("agent-work", lineage=f"human:alice@example.com>session:{session_id}")])],
            creator_session_lookup={},
        )
        await pilot.pause()

        creator_row = _expanded_creator_row(prep_view, "agent-work")
        rendered = creator_row.render()
        assert rendered.plain == snapshot
        # No bold span at all — nothing in the inert row offers an affordance.
        assert not any(_is_bold(span) for span in rendered._spans)
        assert creator_row._click_region is None


@pytest.mark.asyncio
@pytest.mark.spec(XNAV_SPEC, "UC-XNAV-22")
async def test_creator_row_rerenders_when_lookup_transitions_closed_to_live(wire_people, snapshot) -> None:
    """Regression for I-1: the todo fingerprint must include creator-lookup state.

    Without that, a lookup-only transition (no todo field changes) would never
    trigger a rebuild and the row would keep showing the stale retained-closed
    "revive" affordance after the session actually came back live.
    """
    session_id = "creator-1"
    wire_people([ALICE, BOB])
    app = _CrossNavApp(initial_tab=PREPARATION_TAB)
    async with app.run_test(size=(140, 30)) as pilot:
        prep_view = app.query_one("#preparation-view", PreparationView)
        project = _project_with([_todo_dto("agent-work", lineage=f"human:alice@example.com>session:{session_id}")])
        prep_view.update_data(
            [project], creator_session_lookup={session_id: CreatorSessionInfo(status="closed", computer="local")}
        )
        await pilot.pause()
        creator_row = _expanded_creator_row(prep_view, "agent-work")
        assert creator_row.render().plain == snapshot

        # Same todo data — only the lookup transitions from closed to live.
        prep_view.update_data(
            [project], creator_session_lookup={session_id: CreatorSessionInfo(status="live", computer="local")}
        )
        await pilot.pause()

        [creator_row_after] = [
            w for w in prep_view._nav_items if isinstance(w, CreatorSessionRow) and w.slug == "agent-work"
        ]
        rendered_after = creator_row_after.render()
        assert rendered_after.plain == snapshot
