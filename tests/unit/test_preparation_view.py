"""Unit tests for PreparationView session launch behavior."""

from __future__ import annotations

import os
from typing import TypedDict
from unittest.mock import Mock

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.cli.models import AgentAvailabilityInfo, CreateSessionResult
from teleclaude.cli.tui.app import FocusContext
from teleclaude.cli.tui.controller import TuiController
from teleclaude.cli.tui.state import TuiState
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.views.preparation import PreparationView, PrepTodoDisplayInfo, PrepTodoNode


class DummyAPI:
    """API stub for create_session calls."""

    def __init__(self, *, session_id: str = "sess-123", tmux_session_name: str = "tc_missing") -> None:
        self.session_id = session_id
        self.tmux_session_name = tmux_session_name

    async def create_session(
        self,
        *,
        computer: str,
        project_path: str,
        subdir: str | None = None,
        agent: str,
        thinking_mode: str,
        title: str | None = None,
        message: str | None = None,
        auto_command: str | None = None,
    ) -> CreateSessionResult:
        _ = (computer, project_path, subdir, agent, thinking_mode, title, message, auto_command)
        return CreateSessionResult(
            session_id=self.session_id,
            tmux_session_name=self.tmux_session_name,
            status="success",
        )


class DummyScreen:
    """Curses screen stub."""

    def __init__(self) -> None:
        self.refresh_called = False

    def refresh(self) -> None:
        self.refresh_called = True


class ModalInitCapture(TypedDict):
    computer: str
    project_path: str
    default_prompt: str


def _build_ready_todo_node(slug: str, status: str = "ready") -> PrepTodoNode:
    return PrepTodoNode(
        type="todo",
        data=PrepTodoDisplayInfo(
            todo=TodoItem(
                slug=slug,
                status=status,
                description="test",
                has_requirements=True,
                has_impl_plan=True,
            ),
            project_path="/tmp",
            computer="local",
        ),
        depth=0,
    )


def test_handle_enter_on_ready_todo_uses_start_modal_with_prefilled_next_work(monkeypatch):
    """Enter on ready todo should open modal prefilled with /next-work <slug>."""
    api = DummyAPI(tmux_session_name="session-1")
    pane_manager = Mock()
    pane_manager.is_available = True

    state = TuiState()
    controller = TuiController(state, pane_manager, lambda _name: None)
    view = PreparationView(
        api=api,
        agent_availability={},
        focus=FocusContext(),
        pane_manager=pane_manager,
        state=state,
        controller=controller,
    )
    screen = DummyScreen()

    view.flat_items = [_build_ready_todo_node("test-todo")]
    view.selected_index = 0

    captured: ModalInitCapture = {
        "computer": "",
        "project_path": "",
        "default_prompt": "",
    }
    result = CreateSessionResult(status="success", session_id="sess-1", tmux_session_name="tc_123", agent="codex")

    class FakeStartSessionModal:
        def __init__(
            self,
            computer: str,
            project_path: str,
            api: DummyAPI,
            agent_availability: dict[str, AgentAvailabilityInfo],
            default_prompt: str = "",
            notify: object | None = None,
        ) -> None:
            _ = (api, agent_availability, notify)
            captured["computer"] = computer
            captured["project_path"] = project_path
            captured["default_prompt"] = default_prompt
            self.start_requested = False

        def run(self, _stdscr: DummyScreen) -> CreateSessionResult:
            return result

    monkeypatch.setattr("teleclaude.cli.tui.views.preparation.StartSessionModal", FakeStartSessionModal)

    view.handle_enter(screen)

    assert captured["computer"] == "local"
    assert captured["project_path"] == "/tmp"
    assert captured["default_prompt"] == "/next-work test-todo"
    assert view.needs_refresh is True
    pane_manager.show_session.assert_called_once()


def test_prepare_key_uses_start_modal_with_prefilled_next_prepare(monkeypatch):
    """Pressing p on a todo should open modal prefilled with /next-prepare <slug>."""
    api = DummyAPI(tmux_session_name="session-1")
    pane_manager = Mock()
    pane_manager.is_available = True

    state = TuiState()
    controller = TuiController(state, pane_manager, lambda _name: None)
    view = PreparationView(
        api=api,
        agent_availability={},
        focus=FocusContext(),
        pane_manager=pane_manager,
        state=state,
        controller=controller,
    )
    screen = DummyScreen()
    view.flat_items = [_build_ready_todo_node("todo-2", status="pending")]
    view.selected_index = 0

    captured: ModalInitCapture = {
        "computer": "",
        "project_path": "",
        "default_prompt": "",
    }

    class FakeStartSessionModal:
        def __init__(
            self,
            computer: str,
            project_path: str,
            api: DummyAPI,
            agent_availability: dict[str, AgentAvailabilityInfo],
            default_prompt: str = "",
            notify: object | None = None,
        ) -> None:
            _ = (api, agent_availability, notify)
            captured["computer"] = computer
            captured["project_path"] = project_path
            captured["default_prompt"] = default_prompt
            self.start_requested = False

        def run(self, _stdscr: DummyScreen) -> CreateSessionResult:
            return CreateSessionResult(
                status="success", session_id="sess-2", tmux_session_name="tc_456", agent="claude"
            )

    monkeypatch.setattr("teleclaude.cli.tui.views.preparation.StartSessionModal", FakeStartSessionModal)

    view.handle_key(ord("p"), screen)

    assert captured["default_prompt"] == "/next-prepare todo-2"
    assert view.needs_refresh is True
