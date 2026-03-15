"""Characterization tests for animation_triggers.py."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from itertools import count
from unittest.mock import MagicMock, patch

from teleclaude.cli.tui.animation_colors import ColorPalette
from teleclaude.cli.tui.animation_engine import AnimationEngine
from teleclaude.cli.tui.animation_triggers import (
    ActivityTrigger,
    PeriodicTrigger,
    StateDrivenTrigger,
    filter_animations,
)
from teleclaude.cli.tui.animations.base import Animation


@contextmanager
def _patched_engine_runtime() -> Iterator[None]:
    with (
        patch("teleclaude.cli.tui.theme.is_dark_mode", return_value=True),
        patch("teleclaude.cli.tui.theme.get_terminal_background", return_value="#000000"),
        patch("teleclaude.cli.tui.animation_engine.time.time", side_effect=count()),
    ):
        yield


class _DarkOnlyAnimation(Animation):
    theme_filter = "dark"

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        return {}


class _LightOnlyAnimation(Animation):
    theme_filter = "light"

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        return {}


class _UniversalAnimation(Animation):
    theme_filter = None

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        return {}


class _BannerAnimation(Animation):
    def __init__(
        self,
        *,
        palette: ColorPalette,
        is_big: bool,
        duration_seconds: float,
        target: str | None = None,
    ) -> None:
        super().__init__(
            palette=palette,
            is_big=is_big,
            duration_seconds=duration_seconds,
            speed_ms=100,
            seed=0,
            target=target,
        )
        self.duration_frames = 1

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        return {(0, 0): self.palette.get(0)}


class TestFilterAnimations:
    def _make_cls(self, name: str, theme: str | None = None) -> type[Animation]:
        return type(name, (_UniversalAnimation,), {"theme_filter": theme})

    def test_empty_subset_returns_all(self) -> None:
        cls1 = self._make_cls("A")
        cls2 = self._make_cls("B")

        assert filter_animations([cls1, cls2], subset=[], dark_mode=True) == [cls1, cls2]

    def test_subset_filters_by_name(self) -> None:
        cls1 = self._make_cls("Alpha")
        cls2 = self._make_cls("Beta")
        result = filter_animations([cls1, cls2], subset=["Alpha"], dark_mode=True)

        assert result == [cls1]

    def test_dark_filter_excludes_light_only(self) -> None:
        dark_cls = type("D", (_DarkOnlyAnimation,), {})
        light_cls = type("L", (_LightOnlyAnimation,), {})
        result = filter_animations([dark_cls, light_cls], subset=[], dark_mode=True)

        assert result == [dark_cls]

    def test_light_filter_excludes_dark_only(self) -> None:
        dark_cls = type("D", (_DarkOnlyAnimation,), {})
        light_cls = type("L", (_LightOnlyAnimation,), {})
        result = filter_animations([dark_cls, light_cls], subset=[], dark_mode=False)

        assert result == [light_cls]

    def test_universal_included_in_both_modes(self) -> None:
        universal = self._make_cls("U", theme=None)

        assert universal in filter_animations([universal], subset=[], dark_mode=True)
        assert universal in filter_animations([universal], subset=[], dark_mode=False)


class TestPeriodicTrigger:
    def test_init_stores_engine_and_interval(self) -> None:
        engine = AnimationEngine()
        trigger = PeriodicTrigger(engine, interval_sec=30)

        assert trigger.engine is engine
        assert trigger.interval_sec == 30

    def test_animations_subset_defaults_empty(self) -> None:
        trigger = PeriodicTrigger(AnimationEngine())

        assert trigger.animations_subset == []

    def test_stop_cancels_task(self) -> None:
        trigger = PeriodicTrigger(AnimationEngine())
        mock_task = MagicMock()
        trigger.task = mock_task

        trigger.stop()

        mock_task.cancel.assert_called_once()
        assert trigger.task is None

    def test_stop_with_no_task_no_error(self) -> None:
        PeriodicTrigger(AnimationEngine()).stop()


class TestActivityTrigger:
    def test_init_stores_engine(self) -> None:
        engine = AnimationEngine()
        trigger = ActivityTrigger(engine)

        assert trigger.engine is engine

    def test_on_agent_activity_disabled_engine_skips(self) -> None:
        engine = AnimationEngine()
        engine.is_enabled = False

        ActivityTrigger(engine).on_agent_activity("claude")

        assert not engine.has_active_animation

    def test_on_agent_activity_plays_animation(self) -> None:
        engine = AnimationEngine()
        seen: list[tuple[str, Animation]] = []
        engine.on_animation_start = lambda target, animation: seen.append((target, animation))

        with _patched_engine_runtime():
            ActivityTrigger(engine).on_agent_activity("claude", is_big=True)

        assert engine.has_active_animation
        assert seen[0][0] == "banner"
        assert seen[0][1].is_big is True

    def test_on_agent_activity_unknown_agent_falls_back_to_claude_palette(self) -> None:
        engine = AnimationEngine()
        seen: list[Animation] = []
        engine.on_animation_start = lambda target, animation: seen.append(animation)

        with _patched_engine_runtime():
            ActivityTrigger(engine).on_agent_activity("unknown_agent_xyz")

        assert seen[0].palette.name == "agent_claude"

    def test_on_agent_activity_small_request_uses_small_capable_animation(self) -> None:
        engine = AnimationEngine()
        seen: list[tuple[str, Animation]] = []
        engine.on_animation_start = lambda target, animation: seen.append((target, animation))

        with _patched_engine_runtime():
            ActivityTrigger(engine).on_agent_activity("claude", is_big=False)

        assert seen[0][0] == "logo"
        assert seen[0][1].is_big is False
        assert seen[0][1].supports_small is True


class TestStateDrivenTrigger:
    def test_init_stores_engine(self) -> None:
        engine = AnimationEngine()
        trigger = StateDrivenTrigger(engine)

        assert trigger.engine is engine

    def test_register_and_set_context_plays_animation(self) -> None:
        engine = AnimationEngine()
        trigger = StateDrivenTrigger(engine)
        trigger.register("mySection", "idle", _BannerAnimation)

        with _patched_engine_runtime():
            trigger.set_context("banner", "mySection", "idle")

        assert engine.has_active_animation

    def test_set_context_same_context_does_not_replay_animation(self) -> None:
        engine = AnimationEngine()
        trigger = StateDrivenTrigger(engine)
        trigger.register("sec", "active", _BannerAnimation)
        starts: list[tuple[str, Animation]] = []
        engine.on_animation_start = lambda target, animation: starts.append((target, animation))

        with _patched_engine_runtime():
            trigger.set_context("banner", "sec", "active")
            trigger.set_context("banner", "sec", "active")

        assert len(starts) == 1

    def test_set_context_disabled_engine_skips(self) -> None:
        engine = AnimationEngine()
        engine.is_enabled = False
        trigger = StateDrivenTrigger(engine)
        trigger.register("sec", "active", _BannerAnimation)

        with _patched_engine_runtime():
            trigger.set_context("banner", "sec", "active")

        assert not engine.has_active_animation

    def test_set_context_unregistered_section_leaves_engine_idle(self) -> None:
        engine = AnimationEngine()
        trigger = StateDrivenTrigger(engine)

        with _patched_engine_runtime():
            trigger.set_context("banner", "unknown_section", "idle")

        assert not engine.has_active_animation

    def test_idle_context_loops_after_initial_completion(self) -> None:
        engine = AnimationEngine()
        trigger = StateDrivenTrigger(engine)
        trigger.register("sec", "idle", _BannerAnimation)

        with _patched_engine_runtime():
            trigger.set_context("banner", "sec", "idle")
            engine.update()
            engine.update()

        assert engine.has_active_animation
        assert engine.get_color(0, 0) == "#ff0000"

    def test_non_idle_context_stops_after_completion(self) -> None:
        engine = AnimationEngine()
        trigger = StateDrivenTrigger(engine)
        trigger.register("sec", "active", _BannerAnimation)

        with _patched_engine_runtime():
            trigger.set_context("banner", "sec", "active")
            engine.update()
            engine.update()

        assert not engine.has_active_animation
        assert engine.get_color(0, 0) is None

    def test_set_context_palette_falls_back_to_spectrum(self) -> None:
        engine = AnimationEngine()
        trigger = StateDrivenTrigger(engine)
        trigger.register("unknown_palette_section", "idle", _BannerAnimation)
        seen: list[Animation] = []
        engine.on_animation_start = lambda target, animation: seen.append(animation)

        with _patched_engine_runtime():
            trigger.set_context("banner", "unknown_palette_section", "idle")

        assert seen[0].palette.name == "spectrum"
