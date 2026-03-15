from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

import pytest

from teleclaude.cli.tui import controller as controller_module
from teleclaude.cli.tui.controller import ComputerInfo, Intent, IntentType, SessionInfo, TuiController, TuiState


class _ApplyLayoutCall(TypedDict):
    active_session_id: str | None
    sticky_session_ids: list[str]
    get_computer_info: object
    active_doc_preview: object | None
    selected_session_id: str | None
    tree_node_has_focus: bool
    focus: bool


@dataclass
class _PaneManagerStub:
    apply_calls: list[_ApplyLayoutCall] = field(default_factory=list)
    focus_calls: list[str] = field(default_factory=list)

    def is_available(self) -> bool:
        return True

    def apply_layout(self, *args: object, **kwargs: object) -> None:
        self.apply_calls.append(kwargs)

    def focus_pane_for_session(self, session_id: str) -> None:
        self.focus_calls.append(session_id)


def _make_controller(pane_manager: _PaneManagerStub) -> TuiController:
    controller = TuiController(TuiState(), pane_manager, lambda name: ComputerInfo(name=name, is_local=True))
    controller.update_sessions([SessionInfo(session_id="s1", title="one", status="idle", computer="c1")])
    return controller


@pytest.mark.unit
def test_apply_pending_layout_for_deferred_preview_uses_current_layout_state() -> None:
    pane_manager = _PaneManagerStub()
    controller = _make_controller(pane_manager)

    controller.dispatch(Intent(IntentType.SET_PREVIEW, {"session_id": "s1"}), defer_layout=True)

    assert controller.apply_pending_layout() is True
    assert pane_manager.apply_calls == [
        {
            "active_session_id": "s1",
            "sticky_session_ids": [],
            "get_computer_info": controller._get_computer_info,
            "active_doc_preview": None,
            "selected_session_id": None,
            "tree_node_has_focus": True,
            "focus": False,
        }
    ]


@pytest.mark.unit
def test_request_focus_session_triggers_layout_and_focus_on_next_apply() -> None:
    pane_manager = _PaneManagerStub()
    controller = _make_controller(pane_manager)

    controller.request_focus_session("s1")

    assert controller.has_pending_focus() is True
    assert controller.apply_pending_layout() is True
    assert pane_manager.focus_calls == ["s1"]
    assert pane_manager.apply_calls[0]["active_session_id"] is None


@pytest.mark.unit
def test_toggle_sticky_dispatch_persists_current_sticky_list(monkeypatch: pytest.MonkeyPatch) -> None:
    pane_manager = _PaneManagerStub()
    controller = _make_controller(pane_manager)
    calls: list[list[str]] = []

    monkeypatch.setattr(
        controller_module,
        "save_sticky_state",
        lambda state: calls.append([item.session_id for item in state.sessions.sticky_sessions]),
    )

    controller.dispatch(Intent(IntentType.TOGGLE_STICKY, {"session_id": "s1"}), defer_layout=True)
    controller.dispatch(Intent(IntentType.TOGGLE_STICKY, {"session_id": "s1"}), defer_layout=True)

    assert calls == [["s1"], []]
