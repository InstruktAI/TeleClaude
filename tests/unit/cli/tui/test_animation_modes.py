from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
os.environ["TELECLAUDE_CONFIG_PATH"] = str(_REPO_ROOT / "config.yml")

from teleclaude.cli.tui.animation_colors import palette_registry
from teleclaude.cli.tui.animations.base import Z0, Z10, Z20
from teleclaude.cli.tui.animations.general import GlobalSky
from teleclaude.cli.tui.animations.sprites import get_optional_motion_groups, get_weather_clouds
from teleclaude.cli.tui.app import TelecApp


class _DummyTimer:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _DummyTask:
    def __init__(self, coro: object) -> None:
        close = getattr(coro, "close", None)
        if callable(close):
            close()


def _optional_motion_sprites() -> set[object]:
    sprites: set[object] = set()
    for group in get_optional_motion_groups():
        for sprite, _weight, _count_range in group.entries:
            sprites.add(id(sprite))
    return sprites


@pytest.mark.unit
def test_off_mode_global_sky_keeps_ambient_clouds_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("teleclaude.cli.tui.theme.is_dark_mode", lambda: False)
    sky = GlobalSky(
        palette=palette_registry.get("spectrum"),
        is_big=True,
        duration_seconds=3600,
        dark_mode=False,
        show_extra_motion=False,
        seed=7,
    )

    cloud_sprites = {id(sprite) for sprite, _weight, _count_range in get_weather_clouds(sky._weather).entries}
    optional_sprites = _optional_motion_sprites()

    assert sky._sky_entities
    assert {id(entity["sprite"]) for entity in sky._sky_entities}.issubset(cloud_sprites)
    assert not any(id(entity["sprite"]) in optional_sprites for entity in sky._sky_entities)

    buffer = sky.update(0)
    assert buffer.layers[Z0]
    assert buffer.layers[Z20]


@pytest.mark.unit
def test_off_mode_global_sky_keeps_night_sky(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("teleclaude.cli.tui.theme.is_dark_mode", lambda: True)
    sky = GlobalSky(
        palette=palette_registry.get("spectrum"),
        is_big=True,
        duration_seconds=3600,
        dark_mode=True,
        show_extra_motion=False,
        seed=11,
    )

    buffer = sky.update(0)

    assert buffer.layers[Z0]
    assert buffer.layers[Z10]
    assert buffer.layers[Z20]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mode", "expect_motion", "expect_periodic", "expect_activity"),
    [
        ("off", False, False, False),
        ("periodic", True, True, False),
        ("party", True, True, True),
    ],
)
def test_animation_mode_controls_banner_cadence_not_ambient_scene(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expect_motion: bool,
    expect_periodic: bool,
    expect_activity: bool,
) -> None:
    app = TelecApp(api=MagicMock())
    timer = _DummyTimer()

    monkeypatch.setattr(app, "set_interval", lambda _seconds, _callback: timer)
    monkeypatch.setattr("teleclaude.cli.tui.app.asyncio.ensure_future", lambda coro: _DummyTask(coro))

    app._start_animation_mode(mode)

    header_slot = app._animation_engine._targets["header"]
    assert isinstance(header_slot.animation, GlobalSky)
    assert header_slot.animation.show_extra_motion is expect_motion
    assert (app._periodic_trigger is not None) is expect_periodic
    assert (app._activity_trigger is not None) is expect_activity
    assert app._animation_timer is timer


@pytest.mark.unit
def test_watch_app_focus_only_updates_haze(monkeypatch: pytest.MonkeyPatch) -> None:
    app = TelecApp(api=MagicMock())
    pause_runtime = MagicMock()
    register_interaction = MagicMock()
    refresh_focus = MagicMock()

    monkeypatch.setattr(app, "_pause_animation_runtime", pause_runtime, raising=False)
    monkeypatch.setattr(app, "_register_user_interaction", register_interaction, raising=False)
    monkeypatch.setattr(app, "_refresh_focus_sensitive_widgets", refresh_focus, raising=False)

    app._watch_app_focus(False)

    refresh_focus.assert_called_once()
    pause_runtime.assert_not_called()
    register_interaction.assert_not_called()
