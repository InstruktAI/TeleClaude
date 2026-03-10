"""Coverage for Textual footer migration behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from textual.app import App, ComposeResult

from teleclaude.cli.models import ChiptunesStateEvent, ChiptunesTrackEvent, ComputerInfo, ProjectInfo, SessionInfo
from teleclaude.cli.tui.app import TelecApp
from teleclaude.cli.tui.persistence import Persistable
from teleclaude.cli.tui.theme import get_neutral_color
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.tree import ComputerDisplayInfo
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.session_row import SessionRow
from teleclaude.cli.tui.widgets.telec_footer import FooterActionButton, TelecFooter
from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow
from teleclaude.cli.tui.widgets.todo_row import TodoRow
from teleclaude.core.next_machine.core import DOR_READY_THRESHOLD


class FooterHarness(App[None]):
    def compose(self) -> ComposeResult:
        yield TelecFooter()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_telec_app_uses_compact_textual_footer() -> None:
    api = SimpleNamespace(
        connect=AsyncMock(),
        start_websocket=MagicMock(),
        list_computers=AsyncMock(return_value=[]),
        list_projects_with_todos=AsyncMock(return_value=[]),
        list_sessions=AsyncMock(return_value=[]),
        get_agent_availability=AsyncMock(return_value={}),
        list_jobs=AsyncMock(return_value=[]),
        get_settings=AsyncMock(
            return_value=SimpleNamespace(
                tts=SimpleNamespace(enabled=False),
            )
        ),
        get_chiptunes_status=AsyncMock(
            return_value=SimpleNamespace(
                loaded=False,
                playback="cold",
                playing=False,
                paused=False,
                position_seconds=0.0,
                track="",
                sid_path="",
            )
        ),
    )
    app = TelecApp(api)  # type: ignore[arg-type]

    async with app.run_test():
        footer = app.query_one(TelecFooter)
        assert footer is not None
        assert not app.query("#action-bar")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_telec_app_initializes_chiptunes_footer_from_status() -> None:
    api = SimpleNamespace(
        connect=AsyncMock(),
        start_websocket=MagicMock(),
        list_computers=AsyncMock(return_value=[]),
        list_projects_with_todos=AsyncMock(return_value=[]),
        list_sessions=AsyncMock(return_value=[]),
        get_agent_availability=AsyncMock(return_value={}),
        list_jobs=AsyncMock(return_value=[]),
        get_settings=AsyncMock(
            return_value=SimpleNamespace(
                tts=SimpleNamespace(enabled=False),
            )
        ),
        get_chiptunes_status=AsyncMock(
            return_value=SimpleNamespace(
                loaded=True,
                playback="playing",
                playing=True,
                paused=False,
                position_seconds=12.0,
                track="Demo Tune",
                sid_path="/music/demo.sid",
            )
        ),
    )
    app = TelecApp(api)  # type: ignore[arg-type]

    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        footer = app.query_one(TelecFooter)
        assert footer.chiptunes_loaded is True
        assert footer.chiptunes_playing is True
        assert footer.chiptunes_track == "Demo Tune"
        assert footer.chiptunes_sid_path == "/music/demo.sid"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_telec_app_applies_chiptunes_state_events() -> None:
    api = SimpleNamespace(
        connect=AsyncMock(),
        start_websocket=MagicMock(),
        list_computers=AsyncMock(return_value=[]),
        list_projects_with_todos=AsyncMock(return_value=[]),
        list_sessions=AsyncMock(return_value=[]),
        get_agent_availability=AsyncMock(return_value={}),
        list_jobs=AsyncMock(return_value=[]),
        get_settings=AsyncMock(
            return_value=SimpleNamespace(
                tts=SimpleNamespace(enabled=False),
            )
        ),
        get_chiptunes_status=AsyncMock(
            return_value=SimpleNamespace(
                loaded=False,
                playback="cold",
                playing=False,
                paused=False,
                position_seconds=0.0,
                track="",
                sid_path="",
            )
        ),
    )
    app = TelecApp(api)  # type: ignore[arg-type]

    async with app.run_test():
        footer = app.query_one(TelecFooter)
        app._handle_ws_event(
            ChiptunesStateEvent(
                loaded=True,
                playback="paused",
                state_version=3,
                playing=False,
                paused=True,
                position_seconds=33.0,
                track="Paused Tune",
                sid_path="/music/paused.sid",
            )
        )

        assert footer.chiptunes_loaded is True
        assert footer.chiptunes_playing is False
        assert footer.chiptunes_track == "Paused Tune"
        assert footer.chiptunes_sid_path == "/music/paused.sid"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_telec_app_track_events_reconcile_loaded_state() -> None:
    api = SimpleNamespace(
        connect=AsyncMock(),
        start_websocket=MagicMock(),
        list_computers=AsyncMock(return_value=[]),
        list_projects_with_todos=AsyncMock(return_value=[]),
        list_sessions=AsyncMock(return_value=[]),
        get_agent_availability=AsyncMock(return_value={}),
        list_jobs=AsyncMock(return_value=[]),
        get_settings=AsyncMock(
            return_value=SimpleNamespace(
                tts=SimpleNamespace(enabled=False),
            )
        ),
        get_chiptunes_status=AsyncMock(
            return_value=SimpleNamespace(
                loaded=False,
                playback="cold",
                playing=False,
                paused=False,
                position_seconds=0.0,
                track="",
                sid_path="",
            )
        ),
    )
    app = TelecApp(api)  # type: ignore[arg-type]

    async with app.run_test():
        footer = app.query_one(TelecFooter)
        footer.chiptunes_loaded = False
        footer.chiptunes_playing = False
        footer.chiptunes_track = ""
        footer.chiptunes_sid_path = ""

        app._handle_ws_event(
            ChiptunesTrackEvent(
                track="Looping Tune",
                sid_path="/music/loop.sid",
            )
        )

        assert footer.chiptunes_loaded is True
        assert footer.chiptunes_playing is True
        assert footer.chiptunes_track == "Looping Tune"
        assert footer.chiptunes_sid_path == "/music/loop.sid"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_telec_app_play_pause_starts_from_cold_state() -> None:
    api = SimpleNamespace(
        connect=AsyncMock(),
        start_websocket=MagicMock(),
        list_computers=AsyncMock(return_value=[]),
        list_projects_with_todos=AsyncMock(return_value=[]),
        list_sessions=AsyncMock(return_value=[]),
        get_agent_availability=AsyncMock(return_value={}),
        list_jobs=AsyncMock(return_value=[]),
        patch_settings=AsyncMock(),
        chiptunes_pause=AsyncMock(
            return_value=SimpleNamespace(
                loaded=False,
                playback="cold",
                state_version=2,
                playing=False,
                paused=False,
                position_seconds=0.0,
                track="",
                sid_path="",
            )
        ),
        chiptunes_resume=AsyncMock(
            return_value=SimpleNamespace(
                loaded=True,
                playback="playing",
                state_version=2,
                playing=True,
                paused=False,
                position_seconds=0.0,
                track="Demo Tune",
                sid_path="/music/demo.sid",
            )
        ),
        get_chiptunes_status=AsyncMock(
            return_value=SimpleNamespace(
                loaded=False,
                playback="cold",
                playing=False,
                paused=False,
                position_seconds=0.0,
                track="",
                sid_path="",
            )
        ),
        get_settings=AsyncMock(
            return_value=SimpleNamespace(
                tts=SimpleNamespace(enabled=False),
            )
        ),
    )
    app = TelecApp(api)  # type: ignore[arg-type]

    async with app.run_test():
        footer = app.query_one(TelecFooter)
        assert footer.chiptunes_loaded is False

        await TelecApp._chiptunes_play_pause.__wrapped__(app)

        api.chiptunes_pause.assert_not_awaited()
        api.chiptunes_resume.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_telec_app_chiptunes_favorite_toggles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from teleclaude.chiptunes import favorites as fav_mod

    fav_path = tmp_path / "chiptunes-favorites.json"
    monkeypatch.setattr(fav_mod, "FAVORITES_PATH", fav_path)

    api = SimpleNamespace(
        connect=AsyncMock(),
        start_websocket=MagicMock(),
        list_computers=AsyncMock(return_value=[]),
        list_projects_with_todos=AsyncMock(return_value=[]),
        list_sessions=AsyncMock(return_value=[]),
        get_agent_availability=AsyncMock(return_value={}),
        list_jobs=AsyncMock(return_value=[]),
        get_settings=AsyncMock(
            return_value=SimpleNamespace(
                tts=SimpleNamespace(enabled=False),
            )
        ),
        get_chiptunes_status=AsyncMock(
            return_value=SimpleNamespace(
                loaded=True,
                playback="playing",
                playing=True,
                paused=False,
                position_seconds=1.0,
                track="Demo Tune",
                sid_path="/music/demo.sid",
            )
        ),
    )
    app = TelecApp(api)  # type: ignore[arg-type]

    notices: list[str] = []

    async with app.run_test() as pilot:
        await pilot.pause(0.05)
        footer = app.query_one(TelecFooter)
        app.notify = lambda message, **kwargs: notices.append(str(message))  # type: ignore[method-assign]

        await TelecApp._chiptunes_favorite.__wrapped__(app)
        assert footer.chiptunes_favorited is True
        assert fav_mod.is_favorited("/music/demo.sid") is True

        await TelecApp._chiptunes_favorite.__wrapped__(app)
        assert footer.chiptunes_favorited is False
        assert fav_mod.is_favorited("/music/demo.sid") is False

    assert notices == ["⭐ Added to favorites", "Removed from favorites"]


@pytest.mark.unit
def test_telec_footer_implements_persistable_protocol() -> None:
    footer = TelecFooter()

    assert isinstance(footer, Persistable)
    footer.load_persisted_state({"animation_mode": "party", "pane_theming_mode": "agent_plus"})

    assert footer.get_persisted_state() == {
        "animation_mode": "party",
        "pane_theming_mode": "agent_plus",
    }


@pytest.mark.unit
def test_telec_footer_play_click_routes_to_play_pause() -> None:
    footer = TelecFooter()
    footer.chiptunes_loaded = True

    seen: list[tuple[str, object]] = []
    footer.post_message = lambda message: seen.append((message.key, message.value))  # type: ignore[method-assign]

    footer.on_footer_action_button_pressed(SimpleNamespace(button=SimpleNamespace(id="footer-play")))

    assert seen == [("chiptunes_play_pause", None)]


@pytest.mark.unit
def test_telec_footer_next_click_routes_to_next() -> None:
    footer = TelecFooter()

    seen: list[tuple[str, object]] = []
    footer.post_message = lambda message: seen.append((message.key, message.value))  # type: ignore[method-assign]

    footer.chiptunes_loaded = True
    footer.on_footer_action_button_pressed(SimpleNamespace(button=SimpleNamespace(id="footer-next")))

    assert seen == [("chiptunes_next", None)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_telec_footer_play_button_width_is_stable() -> None:
    app = FooterHarness()

    async with app.run_test() as pilot:
        footer = app.query_one(TelecFooter)
        footer.chiptunes_loaded = True
        await pilot.pause(0.05)

        play_button = footer.query_one("#footer-play", FooterActionButton)
        play_width = play_button.size.width

        footer.chiptunes_playing = True
        await pilot.pause(0.05)
        pause_width = play_button.size.width

        assert play_width == pause_width


@pytest.mark.unit
@pytest.mark.asyncio
async def test_telec_footer_transport_controls_use_real_buttons() -> None:
    app = FooterHarness()

    async with app.run_test() as pilot:
        footer = app.query_one(TelecFooter)
        footer.chiptunes_loaded = True
        await pilot.pause(0.05)

        play_button = footer.query_one("#footer-play", FooterActionButton)
        next_button = footer.query_one("#footer-next", FooterActionButton)

        assert play_button.icon == "▶"
        assert play_button.can_focus is False
        assert next_button.disabled is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_telec_footer_transport_controls_disable_when_cold() -> None:
    app = FooterHarness()

    async with app.run_test() as pilot:
        footer = app.query_one(TelecFooter)
        prev_button = footer.query_one("#footer-prev", FooterActionButton)
        play_button = footer.query_one("#footer-play", FooterActionButton)
        next_button = footer.query_one("#footer-next", FooterActionButton)
        fav_button = footer.query_one("#footer-fav", FooterActionButton)
        footer.chiptunes_loaded = True
        await pilot.pause(0.05)
        footer.chiptunes_loaded = False
        await pilot.pause(0.05)

        assert prev_button.disabled is True
        assert play_button.disabled is False
        assert next_button.disabled is True
        assert fav_button.disabled is True

        footer.chiptunes_loaded = True
        await pilot.pause(0.05)

        assert prev_button.disabled is False
        assert play_button.disabled is False
        assert next_button.disabled is False
        assert fav_button.disabled is False


@pytest.mark.unit
def test_footer_action_button_enabled_icon_uses_neutral_highlight_color() -> None:
    button = FooterActionButton("▶")

    text = button._render_icon()

    assert text.style is not None
    assert text.style.color is not None
    assert text.style.color.triplet is not None
    assert text.style.color.triplet.hex == get_neutral_color("highlight")
    assert text.style.bold is True


@pytest.mark.unit
def test_sessions_view_persisted_state_round_trip() -> None:
    view = SessionsView()
    view.load_persisted_state(
        {
            "sticky_sessions": [{"session_id": "sess-1"}],
            "input_highlights": ["sess-1"],
            "output_highlights": ["sess-2"],
            "last_output_summary": {"sess-2": {"text": "done", "ts": 1.0}},
            "collapsed_sessions": ["sess-3"],
            "preview": {"session_id": "sess-1"},
        }
    )

    state = view.get_persisted_state()
    assert state["sticky_sessions"] == [{"session_id": "sess-1"}]
    assert state["input_highlights"] == ["sess-1"]
    assert state["output_highlights"] == ["sess-2"]
    assert state["last_output_summary"] == {"sess-2": {"text": "done", "ts": 1.0}}
    assert state["collapsed_sessions"] == ["sess-3"]
    assert state["preview"] == {"session_id": "sess-1"}


def _computer_header() -> ComputerHeader:
    return ComputerHeader(
        data=ComputerDisplayInfo(
            computer=ComputerInfo(
                name="local",
                status="online",
                user="tester",
                host="localhost",
                is_local=True,
                tmux_binary="tmux",
            ),
            session_count=1,
            recent_activity=False,
        )
    )


def _project_header(path: str = "/tmp/project") -> ProjectHeader:
    return ProjectHeader(
        project=ProjectInfo(computer="local", name="project", path=path, description=None),
        session_count=1,
    )


def _session_row() -> SessionRow:
    return SessionRow(
        session=SessionInfo(
            session_id="sess-1",
            title="Session One",
            status="active",
            computer="local",
            project_path="/tmp/project",
            tmux_session_name="tc_sess_1",
        ),
        display_index="1",
        depth=2,
    )


def _todo_row(*, slug: str = "todo-1", dor: int = DOR_READY_THRESHOLD) -> TodoRow:
    return TodoRow(
        todo=TodoItem(
            slug=slug,
            status=TodoStatus.READY,
            description="todo",
            has_requirements=True,
            has_impl_plan=True,
            dor_score=dor,
            files=["requirements.md"],
        )
    )


def _todo_file_row(*, slug: str = "todo-1") -> TodoFileRow:
    return TodoFileRow(
        filepath=f"/tmp/project/todos/{slug}/requirements.md",
        filename="requirements.md",
        slug=slug,
    )


@pytest.mark.unit
def test_sessions_check_action_is_context_sensitive() -> None:
    view = SessionsView()
    computer = _computer_header()
    project = _project_header()
    session = _session_row()
    view._nav_items = [computer, project, session]

    view.cursor_index = 0
    assert view.check_action("restart_all", ()) is True
    assert view.check_action("new_session", ()) is False
    assert view.check_action("focus_pane", ()) is True
    assert view.check_action("kill_session", ()) is False
    assert view.check_action("restart_session", ()) is False

    view.cursor_index = 1
    assert view.check_action("new_session", ()) is True
    assert view.check_action("restart_all", ()) is False
    assert view.check_action("focus_pane", ()) is True
    assert view.check_action("kill_session", ()) is False
    assert view.check_action("restart_session", ()) is False

    view.cursor_index = 2
    assert view.check_action("kill_session", ()) is True
    assert view.check_action("restart_session", ()) is True
    assert view.check_action("focus_pane", ()) is True
    assert view.check_action("new_session", ()) is False
    assert view.check_action("restart_all", ()) is False


@pytest.mark.unit
def test_sessions_focus_pane_routes_to_header_default_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    view = SessionsView()
    view._nav_items = [_computer_header(), _project_header(), _session_row()]
    called: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        view, "action_new_session", lambda path_mode=False: called.append(("new_session", str(path_mode)))
    )

    # Computer header → path-mode new session (not restart_all)
    view.cursor_index = 0
    view.action_focus_pane()
    assert called == [("new_session", "True")]

    view.cursor_index = 1
    view.action_focus_pane()
    assert called == [("new_session", "True"), ("new_session", "False")]


@pytest.mark.unit
def test_sessions_default_action_tracks_cursor_context() -> None:
    view = SessionsView()
    view._nav_items = [_computer_header(), _project_header(), _session_row()]

    # Computer header → focus_pane (Enter opens path-mode modal, not restart_all)
    view.cursor_index = 0
    assert view._default_footer_action() == "focus_pane"
    view.cursor_index = 1
    assert view._default_footer_action() == "new_session"
    view.cursor_index = 2
    assert view._default_footer_action() == "focus_pane"


@pytest.mark.unit
def test_sessions_default_action_is_executable_for_selected_node() -> None:
    view = SessionsView()
    view._nav_items = [_computer_header(), _project_header(), _session_row()]

    for index in (0, 1, 2):
        view.cursor_index = index
        default_action = view._default_footer_action()
        assert default_action is not None
        assert view.check_action(default_action, ()) is True


@pytest.mark.unit
def test_preparation_check_action_is_context_sensitive() -> None:
    view = PreparationView()
    project = _project_header()
    todo = _todo_row()
    file_row = _todo_file_row()
    view._nav_items = [project, todo, file_row]

    view.cursor_index = 0
    assert view.check_action("new_todo", ()) is True
    assert view.check_action("remove_todo", ()) is False
    assert view.check_action("activate", ()) is False
    assert view.check_action("preview_file", ()) is False

    view.cursor_index = 1
    assert view.check_action("prepare", ()) is True
    assert view.check_action("start_work", ()) is True
    assert view.check_action("remove_todo", ()) is True
    assert view.check_action("preview_file", ()) is False

    view.cursor_index = 2
    assert view.check_action("prepare", ()) is True
    assert view.check_action("start_work", ()) is True
    assert view.check_action("remove_todo", ()) is True
    assert view.check_action("activate", ()) is True
    assert view.check_action("preview_file", ()) is True
    assert view.check_action("new_todo", ()) is False
    assert view.check_action("new_bug", ()) is False


@pytest.mark.unit
def test_preparation_enter_hint_matches_activate_behavior() -> None:
    enter_binding = next(binding for binding in PreparationView.BINDINGS if binding.action == "activate")
    assert enter_binding.description == "Toggle/Edit"


@pytest.mark.unit
def test_preparation_activate_on_todo_toggles_expansion_not_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = PreparationView()
    view._nav_items = [_project_header(), _todo_row(slug="todo-2")]
    view.cursor_index = 1

    toggle_calls: list[str] = []
    post_calls: list[object] = []
    is_expanded = {"value": False}

    monkeypatch.setattr(view, "_expand_todo", lambda row: toggle_calls.append(f"expand:{row.slug}"))
    monkeypatch.setattr(view, "_collapse_todo", lambda row: toggle_calls.append(f"collapse:{row.slug}"))
    monkeypatch.setattr(view, "_is_expanded", lambda _slug: is_expanded["value"])
    monkeypatch.setattr(view, "post_message", lambda message: post_calls.append(message))

    view.action_activate()
    is_expanded["value"] = True
    view.action_activate()

    assert toggle_calls == ["expand:todo-2", "collapse:todo-2"]
    assert post_calls == []


@pytest.mark.unit
def test_preparation_default_action_tracks_cursor_context() -> None:
    view = PreparationView()
    view._nav_items = [_project_header(), _todo_row(), _todo_file_row()]

    view.cursor_index = 0
    assert view._default_footer_action() == "new_todo"
    view.cursor_index = 1
    assert view._default_footer_action() == "activate"
    view.cursor_index = 2
    assert view._default_footer_action() == "activate"


@pytest.mark.unit
def test_prepare_on_project_opens_modal_without_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    view = PreparationView()
    view._nav_items = [_project_header("/tmp/project")]
    view.cursor_index = 0

    captured: dict[str, str] = {}
    monkeypatch.setattr(view, "_open_session_modal", lambda **kwargs: captured.update(kwargs))

    view.action_prepare()

    assert captured["computer"] == "local"
    assert captured["project_path"] == "/tmp/project"
    assert captured["default_message"] == "/next-prepare"


@pytest.mark.unit
def test_start_work_on_project_opens_modal_without_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    view = PreparationView()
    view._nav_items = [_project_header("/tmp/project")]
    view.cursor_index = 0

    captured: dict[str, str] = {}
    monkeypatch.setattr(view, "_open_session_modal", lambda **kwargs: captured.update(kwargs))

    view.action_start_work()

    assert captured["computer"] == "local"
    assert captured["project_path"] == "/tmp/project"
    assert captured["default_message"] == "/next-work"


@pytest.mark.unit
def test_start_work_on_file_row_uses_parent_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    view = PreparationView()
    project = _project_header("/tmp/project")
    todo = _todo_row(slug="todo-2")
    file_row = _todo_file_row(slug="todo-2")
    view._nav_items = [project, todo, file_row]
    view.cursor_index = 2
    view._slug_to_project_path["todo-2"] = "/tmp/project"
    view._slug_to_computer["todo-2"] = "local"

    captured: dict[str, str] = {}
    monkeypatch.setattr(view, "_open_session_modal", lambda **kwargs: captured.update(kwargs))

    view.action_start_work()

    assert captured["computer"] == "local"
    assert captured["project_path"] == "/tmp/project"
    assert captured["default_message"] == "/next-work todo-2"


@pytest.mark.unit
def test_start_work_bug_row_bypasses_dor_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    view = PreparationView()
    project = _project_header("/tmp/project")
    bug_row = TodoRow(
        todo=TodoItem(
            slug="fix-login-bug",
            status=TodoStatus.PENDING,
            description="bug",
            has_requirements=False,
            has_impl_plan=False,
            dor_score=None,
            files=["bug.md"],
        )
    )
    view._nav_items = [project, bug_row]
    view.cursor_index = 1
    view._slug_to_project_path["fix-login-bug"] = "/tmp/project"
    view._slug_to_computer["fix-login-bug"] = "local"

    captured: dict[str, str] = {}
    monkeypatch.setattr(view, "_open_session_modal", lambda **kwargs: captured.update(kwargs))

    view.action_start_work()

    assert captured["computer"] == "local"
    assert captured["project_path"] == "/tmp/project"
    assert captured["default_message"] == "/next-work fix-login-bug"
