"""Characterization tests for animation_triggers.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from teleclaude.cli.tui.animation_engine import AnimationEngine
from teleclaude.cli.tui.animation_triggers import (
    ActivityTrigger,
    PeriodicTrigger,
    StateDrivenTrigger,
    filter_animations,
)
from teleclaude.cli.tui.animations.base import Animation


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


class TestFilterAnimations:
    def _make_cls(self, name: str, theme: str | None = None) -> type[Animation]:
        return type(name, (_UniversalAnimation,), {"theme_filter": theme})

    def test_empty_subset_returns_all(self) -> None:
        cls1 = self._make_cls("A")
        cls2 = self._make_cls("B")
        result = filter_animations([cls1, cls2], subset=[], dark_mode=True)
        assert result == [cls1, cls2]

    def test_subset_filters_by_name(self) -> None:
        cls1 = self._make_cls("Alpha")
        cls2 = self._make_cls("Beta")
        result = filter_animations([cls1, cls2], subset=["Alpha"], dark_mode=True)
        assert cls1 in result
        assert cls2 not in result

    def test_dark_filter_excludes_light_only(self) -> None:
        dark_cls = type("D", (_DarkOnlyAnimation,), {})
        light_cls = type("L", (_LightOnlyAnimation,), {})
        result = filter_animations([dark_cls, light_cls], subset=[], dark_mode=True)
        assert dark_cls in result
        assert light_cls not in result

    def test_light_filter_excludes_dark_only(self) -> None:
        dark_cls = type("D", (_DarkOnlyAnimation,), {})
        light_cls = type("L", (_LightOnlyAnimation,), {})
        result = filter_animations([dark_cls, light_cls], subset=[], dark_mode=False)
        assert light_cls in result
        assert dark_cls not in result

    def test_universal_included_in_both_modes(self) -> None:
        uni = self._make_cls("U", theme=None)
        assert uni in filter_animations([uni], subset=[], dark_mode=True)
        assert uni in filter_animations([uni], subset=[], dark_mode=False)


class TestPeriodicTrigger:
    def test_init_stores_engine_and_interval(self) -> None:
        engine = AnimationEngine()
        trigger = PeriodicTrigger(engine, interval_sec=30)
        assert trigger.engine is engine
        assert trigger.interval_sec == 30

    def test_animations_subset_defaults_empty(self) -> None:
        engine = AnimationEngine()
        trigger = PeriodicTrigger(engine)
        assert trigger.animations_subset == []

    def test_stop_cancels_task(self) -> None:
        engine = AnimationEngine()
        trigger = PeriodicTrigger(engine)
        mock_task = MagicMock()
        trigger.task = mock_task
        trigger.stop()
        mock_task.cancel.assert_called_once()
        assert trigger.task is None

    def test_stop_with_no_task_no_error(self) -> None:
        engine = AnimationEngine()
        trigger = PeriodicTrigger(engine)
        trigger.stop()  # Should not raise


class TestActivityTrigger:
    def test_init_stores_engine(self) -> None:
        engine = AnimationEngine()
        trigger = ActivityTrigger(engine)
        assert trigger.engine is engine

    def test_on_agent_activity_disabled_engine_skips(self) -> None:
        engine = AnimationEngine()
        engine.is_enabled = False
        trigger = ActivityTrigger(engine)
        trigger.on_agent_activity("claude")
        assert not engine.has_active_animation

    @patch("teleclaude.cli.tui.theme.is_dark_mode", return_value=True)
    def test_on_agent_activity_plays_animation(self, _mock_dark: MagicMock) -> None:
        engine = AnimationEngine()
        trigger = ActivityTrigger(engine)
        trigger.on_agent_activity("claude", is_big=True)
        assert engine.has_active_animation

    @patch("teleclaude.cli.tui.theme.is_dark_mode", return_value=True)
    def test_on_agent_activity_unknown_agent_falls_back_to_claude(self, _mock_dark: MagicMock) -> None:
        engine = AnimationEngine()
        trigger = ActivityTrigger(engine)
        trigger.on_agent_activity("unknown_agent_xyz")
        # Should still play something using claude fallback
        assert engine.has_active_animation

    @patch("teleclaude.cli.tui.theme.is_dark_mode", return_value=True)
    def test_on_agent_activity_small_only_supports_small(self, _mock_dark: MagicMock) -> None:
        engine = AnimationEngine()
        trigger = ActivityTrigger(engine)
        # is_big=False should still play if any animation supports_small
        trigger.on_agent_activity("claude", is_big=False)
        # Some animations support small; engine may or may not have active depending on pool


class TestStateDrivenTrigger:
    def test_init_stores_engine(self) -> None:
        engine = AnimationEngine()
        trigger = StateDrivenTrigger(engine)
        assert trigger.engine is engine

    def test_register_and_set_context_plays_animation(self) -> None:
        engine = AnimationEngine()
        trigger = StateDrivenTrigger(engine)

        class BannerAnim(Animation):
            def update(self, frame: int) -> dict[tuple[int, int], str | int]:
                return {}

        trigger.register("mySection", "idle", BannerAnim)
        trigger.set_context("banner", "mySection", "idle")
        assert engine.has_active_animation

    def test_set_context_same_context_no_replay(self) -> None:
        engine = AnimationEngine()
        trigger = StateDrivenTrigger(engine)

        class BannerAnim(Animation):
            def update(self, frame: int) -> dict[tuple[int, int], str | int]:
                return {}

        trigger.register("sec", "active", BannerAnim)
        trigger.set_context("banner", "sec", "active")
        first_anim = engine._targets["banner"].animation

        trigger.set_context("banner", "sec", "active")
        # Same context → animation not replaced
        assert engine._targets["banner"].animation is first_anim

    def test_set_context_disabled_engine_skips(self) -> None:
        engine = AnimationEngine()
        engine.is_enabled = False
        trigger = StateDrivenTrigger(engine)

        class BannerAnim(Animation):
            def update(self, frame: int) -> dict[tuple[int, int], str | int]:
                return {}

        trigger.register("sec", "active", BannerAnim)
        trigger.set_context("banner", "sec", "active")
        assert not engine.has_active_animation

    def test_set_context_unregistered_section_no_error(self) -> None:
        engine = AnimationEngine()
        trigger = StateDrivenTrigger(engine)
        trigger.set_context("banner", "unknown_section", "idle")
        # Should not raise, and no animation

    def test_set_context_idle_enables_looping(self) -> None:
        engine = AnimationEngine()
        trigger = StateDrivenTrigger(engine)

        class BannerAnim(Animation):
            def update(self, frame: int) -> dict[tuple[int, int], str | int]:
                return {}

        trigger.register("sec", "idle", BannerAnim)
        trigger.set_context("banner", "sec", "idle")
        assert engine._targets["banner"].looping

    def test_set_context_non_idle_no_looping(self) -> None:
        engine = AnimationEngine()
        trigger = StateDrivenTrigger(engine)

        class BannerAnim(Animation):
            def update(self, frame: int) -> dict[tuple[int, int], str | int]:
                return {}

        trigger.register("sec", "active", BannerAnim)
        trigger.set_context("banner", "sec", "active")
        # Non-idle → looping not set
        assert not engine._targets["banner"].looping

    def test_set_context_palette_fallback_to_spectrum(self) -> None:
        engine = AnimationEngine()
        trigger = StateDrivenTrigger(engine)

        class BannerAnim(Animation):
            def update(self, frame: int) -> dict[tuple[int, int], str | int]:
                return {}

        trigger.register("unknown_palette_section", "idle", BannerAnim)
        trigger.set_context("banner", "unknown_palette_section", "idle")
        # Engine should still play (spectrum fallback)
        assert engine.has_active_animation
