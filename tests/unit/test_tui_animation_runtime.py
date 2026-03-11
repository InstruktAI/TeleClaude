"""Unit tests for TUI animation runtime throttling."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from teleclaude.cli.tui.app import ANIMATION_IDLE_TIMEOUT_S, TelecApp


@pytest.mark.unit
def test_register_user_interaction_resumes_requested_mode() -> None:
    app = TelecApp(SimpleNamespace())
    app._animation_requested_mode = "party"
    app._animation_runtime_paused = True
    app._animation_timer = None
    app._start_animation_mode = MagicMock()
    app.app_focus = True

    app._register_user_interaction()

    app._start_animation_mode.assert_called_once_with("party")
    assert app._animation_runtime_paused is False


@pytest.mark.unit
def test_check_animation_idle_pauses_requested_mode() -> None:
    app = TelecApp(SimpleNamespace())
    app._animation_requested_mode = "periodic"
    app._animation_runtime_paused = False
    app._stop_animation = MagicMock()
    app.app_focus = True
    app._last_user_interaction_at = 0.0

    app._check_animation_idle()

    app._stop_animation.assert_called_once()
    assert app._animation_runtime_paused is True


@pytest.mark.unit
def test_apply_animation_runtime_keeps_requested_mode_paused_when_unfocused() -> None:
    app = TelecApp(SimpleNamespace())
    app._animation_requested_mode = "party"
    app._animation_runtime_paused = False
    app._stop_animation = MagicMock()
    app._should_pause_animation = MagicMock(return_value=True)

    app._apply_animation_runtime()

    app._stop_animation.assert_called_once()
    assert app._animation_runtime_paused is True


@pytest.mark.unit
def test_should_pause_animation_after_idle_threshold() -> None:
    app = TelecApp(SimpleNamespace())
    app.app_focus = True
    app._last_user_interaction_at = 10.0

    assert app._should_pause_animation(now=10.0 + ANIMATION_IDLE_TIMEOUT_S + 0.1) is True
    assert app._should_pause_animation(now=10.0 + ANIMATION_IDLE_TIMEOUT_S - 0.1) is False
