"""Functional tests for TUI input safety."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from textual import events
from textual.screen import ModalScreen
from textual.widgets import Input

import teleclaude.cli.tui.app as app_mod
from teleclaude.cli.tui.app import TelecApp
from teleclaude.cli.tui.paste_guard import (
    PASTE_IGNORED_NOTIFICATION,
    RAW_KEY_BURST_THRESHOLD,
    RAW_KEY_BURST_WINDOW_SECONDS,
)
from teleclaude.cli.tui.views.config import ConfigView

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/tui/input-safety"
_BARE_TIME = 100.0
_KEY_A = "a"
_KEY_B = "b"
_KEY_C = "c"
_KEY_QUIT = "q"
_KEY_THEME = "t"


class _BareScreen:
    @property
    def active_bindings(self) -> object:
        raise AssertionError("guard must not inspect active_bindings")


class _RecordingTimer:
    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True

    def fire(self) -> None:
        if not self.stopped:
            self.callback()


class _GuardHarness:
    def __init__(self) -> None:
        self.screen: object = _BareScreen()
        self.focused: object | None = None
        self._driver = None
        self._paste_guard_keys: deque[tuple[str, str | None]] = deque(maxlen=RAW_KEY_BURST_THRESHOLD + 1)
        self._paste_guard_flush_timer: _RecordingTimer | None = None
        self._paste_guard_window_started_at: float | None = None
        self._paste_guard_quiet_until = float("-inf")
        self._last_paste_at = float("-inf")
        self.notifications: list[tuple[str, str]] = []
        self.posted: list[events.Key] = []
        self.timers: list[_RecordingTimer] = []

    def notify(self, message: str, *, severity: str) -> None:
        self.notifications.append((message, severity))

    def set_timer(self, _delay: float, callback: Callable[[], None]) -> _RecordingTimer:
        timer = _RecordingTimer(callback)
        self.timers.append(timer)
        self._paste_guard_flush_timer = timer
        return timer

    def post_message(self, event: events.Key) -> None:
        self.posted.append(event)

    def _input_surface_active(self) -> bool:
        return TelecApp._input_surface_active(self)

    def _focused_widget_is_paste_safe(self) -> bool:
        return TelecApp._focused_widget_is_paste_safe(self)

    def _schedule_guarded_key_flush(self) -> None:
        TelecApp._schedule_guarded_key_flush(self)

    def _flush_guarded_keys(self) -> None:
        TelecApp._flush_guarded_keys(self)

    def _discard_guarded_keys(self, now: float | None = None) -> None:
        TelecApp._discard_guarded_keys(self, now)


def _key(key: str) -> events.Key:
    return events.Key(key, key if len(key) == 1 else None)


def _event_was_blocked(event: events.Event) -> bool:
    return bool(event._no_default_action and event._stop_propagation)


def _drive_key(harness: _GuardHarness, key: str, now: float, monkeypatch: pytest.MonkeyPatch) -> events.Key:
    monkeypatch.setattr(app_mod._t, "monotonic", lambda: now)
    event = _key(key)
    TelecApp.on_key(harness, event)
    return event


@pytest.mark.spec(_SPEC, "UC-TIS1")
def test_bracketed_paste_is_blocked_on_bare_tui_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _GuardHarness()
    monkeypatch.setattr(app_mod._t, "monotonic", lambda: _BARE_TIME)
    event = events.Paste("payload")

    TelecApp.on_paste(harness, event)

    assert _event_was_blocked(event)
    assert harness.notifications == [(PASTE_IGNORED_NOTIFICATION, "warning")]
    assert harness.posted == []


@pytest.mark.spec(_SPEC, "UC-TIS2")
def test_raw_rapid_burst_fails_closed_on_bare_tui_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _GuardHarness()

    first = _drive_key(harness, _KEY_A, _BARE_TIME, monkeypatch)
    second = _drive_key(harness, _KEY_B, _BARE_TIME + 0.001, monkeypatch)
    third = _drive_key(harness, _KEY_C, _BARE_TIME + 0.002, monkeypatch)

    assert _event_was_blocked(first)
    assert _event_was_blocked(second)
    assert _event_was_blocked(third)
    assert harness.posted == []
    assert harness.notifications == [(PASTE_IGNORED_NOTIFICATION, "warning")]
    assert not harness._paste_guard_keys
    assert harness.timers[-1].stopped


@pytest.mark.spec(_SPEC, "UC-TIS3")
def test_quiet_manual_keys_release_through_normal_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _GuardHarness()

    _drive_key(harness, _KEY_QUIT, _BARE_TIME, monkeypatch)
    _drive_key(harness, _KEY_THEME, _BARE_TIME + 0.001, monkeypatch)
    harness.timers[-1].fire()

    assert [event.key for event in harness.posted] == [_KEY_QUIT, _KEY_THEME]
    for released in harness.posted:
        TelecApp.on_key(harness, released)
        assert not _event_was_blocked(released)
    assert harness.notifications == []


@pytest.mark.spec(_SPEC, "UC-TIS4")
def test_textual_input_bypasses_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _GuardHarness()
    harness.focused = Input()

    key_event = _drive_key(harness, _KEY_A, _BARE_TIME, monkeypatch)
    paste_event = events.Paste("payload")
    TelecApp.on_paste(harness, paste_event)

    assert not _event_was_blocked(key_event)
    assert not _event_was_blocked(paste_event)
    assert harness.timers == []
    assert harness.notifications == []


@pytest.mark.spec(_SPEC, "UC-TIS5")
def test_modal_screen_bypasses_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _GuardHarness()
    harness.screen = ModalScreen()

    key_event = _drive_key(harness, _KEY_QUIT, _BARE_TIME, monkeypatch)
    paste_event = events.Paste("payload")
    TelecApp.on_paste(harness, paste_event)

    assert not _event_was_blocked(key_event)
    assert not _event_was_blocked(paste_event)
    assert harness.timers == []
    assert harness.notifications == []


@pytest.mark.spec(_SPEC, "UC-TIS6")
def test_config_inline_editing_bypasses_guard_only_while_editing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _GuardHarness()
    config_view = ConfigView()
    state = SimpleNamespace(is_editing=True)
    monkeypatch.setattr(config_view, "_content_or_none", lambda: state)
    harness.focused = config_view

    editing_key = _drive_key(harness, _KEY_A, _BARE_TIME, monkeypatch)
    state.is_editing = False
    control_key = _drive_key(harness, _KEY_QUIT, _BARE_TIME + RAW_KEY_BURST_WINDOW_SECONDS * 2, monkeypatch)

    assert config_view.paste_safe is False
    state.is_editing = True
    assert not _event_was_blocked(editing_key)
    assert _event_was_blocked(control_key)
    assert len(harness.timers) == 1
