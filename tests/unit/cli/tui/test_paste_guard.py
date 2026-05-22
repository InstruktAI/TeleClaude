"""Behavioral tests for TUI paste and key-burst guarding."""

from __future__ import annotations

import unicodedata
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest
from syrupy.assertion import SnapshotAssertion
from textual import events
from textual.pilot import Pilot
from textual.widget import Widget
from textual.widgets import Input

from teleclaude.api_models import (
    ChiptunesStatusDTO,
    ComputerDTO,
    ProjectWithTodosDTO,
    SettingsDTO,
    TodoDTO,
    TTSSettingsDTO,
    TuiBootstrapDataDTO,
    TuiBootstrapDTO,
    TuiBootstrapPillar,
)
from teleclaude.cli.tui import app as app_module
from teleclaude.cli.tui.app import _BURST_THRESHOLD, TelecApp
from teleclaude.cli.tui.views.preparation import PreparationView

_PASTE_TEXT = "R"
_MANUAL_KEY = "n"


@dataclass
class _ActionCalls:
    remove_artifact: int = 0
    new_project: int = 0
    new_todo: int = 0
    notifications: list[dict[str, object]] = field(default_factory=list)


class _StubAPI:
    def __init__(self) -> None:
        self.connect = AsyncMock(return_value=None)
        self.close = AsyncMock(return_value=None)
        self.websocket_calls: list[tuple[object, object, object]] = []

    def start_websocket(
        self,
        *,
        callback: object,
        subscriptions: object = None,
        on_connect: object = None,
    ) -> None:
        self.websocket_calls.append((callback, subscriptions, on_connect))

    async def get_tui_bootstrap(self, requested: list[TuiBootstrapPillar]) -> TuiBootstrapDTO:
        return TuiBootstrapDTO(
            requested=requested,
            data=TuiBootstrapDataDTO(
                computers=[ComputerDTO(name="local", status="online", user="test", host="localhost", is_local=True)],
                projects_with_todos=[
                    ProjectWithTodosDTO(
                        computer="local",
                        name="Functional Project",
                        path="/tmp/project",
                        description="Preparation flow fixture",
                        todos=[
                            TodoDTO(
                                slug="todo-1",
                                status="pending",
                                description="Test todo",
                                has_requirements=True,
                                has_impl_plan=False,
                                files=["requirements"],
                                project_path="/tmp/project",
                            )
                        ],
                    )
                ],
                sessions=[],
                availability={},
                jobs=[],
                settings=SettingsDTO(tts=TTSSettingsDTO(enabled=False)),
                chiptunes=ChiptunesStatusDTO(),
            ),
        )


async def _wait_for_preparation_rows(pilot: Pilot[str | None], prep: PreparationView) -> None:
    for _ in range(10):
        await pilot.pause()
        if prep._nav_items:
            return
    raise AssertionError("preparation rows did not populate")


@asynccontextmanager
async def _running_preparation_app(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[TelecApp, Pilot[str | None], PreparationView, _ActionCalls]]:
    monkeypatch.setattr(app_module, "load_state", lambda: {})
    monkeypatch.setattr(app_module, "save_state", lambda _state: None)
    monkeypatch.setattr(app_module.signal, "signal", lambda *_args, **_kwargs: None)
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)

    calls = _ActionCalls()

    def notify(self: TelecApp, message: str, **kwargs: object) -> None:
        calls.notifications.append({"message": message, **kwargs})

    def remove_artifact(_self: PreparationView) -> None:
        calls.remove_artifact += 1

    def new_project(_self: PreparationView) -> None:
        calls.new_project += 1

    def new_todo(_self: PreparationView) -> None:
        calls.new_todo += 1

    monkeypatch.setattr(TelecApp, "notify", notify)
    monkeypatch.setattr(PreparationView, "action_remove_artifact", remove_artifact)
    monkeypatch.setattr(PreparationView, "action_new_project", new_project)
    monkeypatch.setattr(PreparationView, "action_new_todo", new_todo)

    app = TelecApp(api=_StubAPI(), start_view=2)
    async with app.run_test() as pilot:
        prep = app.query_one("#preparation-view", PreparationView)
        await _wait_for_preparation_rows(pilot, prep)
        prep.focus()
        yield app, pilot, prep, calls


def _send_driver_key(app: TelecApp, key: str) -> None:
    driver = app._driver
    assert driver is not None
    character = unicodedata.lookup(f"LATIN SMALL LETTER {key.upper()}") if key.isalpha() else key
    event = events.Key(key, character)
    event.set_sender(app)
    driver.send_message(event)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_paste_on_preparation_surface_does_not_fire_remove_binding(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    async with _running_preparation_app(monkeypatch) as (app, pilot, _prep, calls):
        app.post_message(events.Paste(_PASTE_TEXT))
        await pilot.pause()

    assert calls.remove_artifact == 0
    assert calls.notifications == snapshot


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_burst_keys_on_preparation_surface_do_not_fire_new_item_binding(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    async with _running_preparation_app(monkeypatch) as (app, pilot, _prep, calls):
        for _ in range(_BURST_THRESHOLD + 1):
            _send_driver_key(app, _MANUAL_KEY)
        await pilot.pause()

    assert calls.new_project == 0
    assert calls.new_todo == 0
    assert calls.notifications == snapshot


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_single_manual_key_on_preparation_surface_fires_without_burst_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _running_preparation_app(monkeypatch) as (_app, pilot, _prep, calls):
        await pilot.press(_MANUAL_KEY)

        assert calls.new_project + calls.new_todo == 1
        assert calls.notifications == []


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_threshold_sized_key_group_is_replayed_without_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _running_preparation_app(monkeypatch) as (app, pilot, _prep, calls):
        for _ in range(_BURST_THRESHOLD):
            _send_driver_key(app, _MANUAL_KEY)
        await pilot.pause()

    assert calls.new_project + calls.new_todo == _BURST_THRESHOLD
    assert calls.notifications == []


@pytest.mark.unit
def test_textual_input_is_paste_safe_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    app = object.__new__(TelecApp)
    text_input = Input()
    monkeypatch.setattr(TelecApp, "focused", property(lambda _self: text_input))

    assert app._focused_widget_is_paste_safe() is True


@pytest.mark.unit
def test_explicit_marker_makes_non_input_widget_paste_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    app = object.__new__(TelecApp)
    marked_widget = Widget()
    marked_widget.paste_safe = True
    monkeypatch.setattr(TelecApp, "focused", property(lambda _self: marked_widget))

    assert app._focused_widget_is_paste_safe() is True
