"""Characterization tests for animation_engine.py."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from itertools import count
from unittest.mock import patch

from teleclaude.cli.tui.animation_colors import SpectrumPalette
from teleclaude.cli.tui.animation_engine import AnimationEngine, AnimationPriority, AnimationSlot
from teleclaude.cli.tui.animations.base import Z0, Z50, Animation, RenderBuffer


@contextmanager
def _patched_engine_runtime(
    *,
    dark_mode: bool = True,
    background_hex: str = "#000000",
) -> Iterator[None]:
    with (
        patch("teleclaude.cli.tui.theme.is_dark_mode", return_value=dark_mode),
        patch("teleclaude.cli.tui.theme.get_terminal_background", return_value=background_hex),
        patch("teleclaude.cli.tui.animation_engine.time.time", side_effect=count()),
    ):
        yield


class _PixelAnimation(Animation):
    """Minimal animation that paints a single pixel with a deterministic color."""

    def __init__(
        self,
        color: str = "#ff0000",
        *,
        frames_to_complete: int = 2,
        is_big: bool = True,
        target: str | None = None,
    ) -> None:
        super().__init__(
            palette=SpectrumPalette(),
            is_big=is_big,
            duration_seconds=0.5,
            speed_ms=100,
            seed=0,
            target=target,
        )
        self.color = color
        self.duration_frames = frames_to_complete

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        return {(0, 0): self.color}


class _BufferAnimation(Animation):
    """Animation that exercises multi-layer RenderBuffer output."""

    def __init__(self) -> None:
        super().__init__(
            palette=SpectrumPalette(),
            is_big=True,
            duration_seconds=0.5,
            speed_ms=100,
            seed=0,
        )
        self.duration_frames = 2

    def update(self, frame: int) -> RenderBuffer:
        buffer = RenderBuffer()
        buffer.add_pixel(Z0, 0, 0, "#000000")
        buffer.add_pixel(Z50, 1, 0, "#00ff00")
        return buffer


class TestAnimationPriority:
    def test_activity_higher_than_periodic(self) -> None:
        assert AnimationPriority.ACTIVITY > AnimationPriority.PERIODIC


class TestAnimationSlot:
    def test_default_state(self) -> None:
        slot = AnimationSlot()

        assert slot.animation is None
        assert slot.frame_count == 0
        assert slot.priority == AnimationPriority.PERIODIC
        assert not slot.looping
        assert len(slot.queue) == 0


class TestAnimationEngine:
    def _make_engine(self) -> AnimationEngine:
        return AnimationEngine()

    def test_is_enabled_default_true(self) -> None:
        engine = self._make_engine()

        assert engine.is_enabled

    def test_has_active_animation_default_false(self) -> None:
        engine = self._make_engine()

        assert not engine.has_active_animation

    def test_animation_mode_default_periodic(self) -> None:
        engine = self._make_engine()

        assert engine.animation_mode == "periodic"

    def test_animation_mode_setter(self) -> None:
        engine = self._make_engine()
        engine.animation_mode = "party"

        assert engine.animation_mode == "party"

    def test_play_marks_engine_active_and_reports_target(self) -> None:
        engine = self._make_engine()
        started: list[tuple[str, Animation]] = []
        engine.on_animation_start = lambda target, animation: started.append((target, animation))

        with _patched_engine_runtime():
            engine.play(_PixelAnimation())

        assert engine.has_active_animation
        assert started[0][0] == "banner"

    def test_play_disabled_engine_ignores_animation(self) -> None:
        engine = self._make_engine()
        engine.is_enabled = False

        with _patched_engine_runtime():
            engine.play(_PixelAnimation())

        assert not engine.has_active_animation
        assert engine.get_color(0, 0) is None

    def test_is_enabled_false_stops_running_animation_and_clears_pixels(self) -> None:
        engine = self._make_engine()

        with _patched_engine_runtime():
            engine.play(_PixelAnimation())
            engine.update()
            engine.is_enabled = False

        assert not engine.has_active_animation
        assert engine.get_color(0, 0) is None

    def test_stop_clears_all_targets(self) -> None:
        engine = self._make_engine()

        with _patched_engine_runtime():
            engine.play(_PixelAnimation(color="#ff0000"))
            engine.play(_PixelAnimation(color="#0000ff", is_big=False), target="logo")
            engine.update()
            engine.stop()

        assert not engine.has_active_animation
        assert engine.get_color(0, 0, "banner") is None
        assert engine.get_color(0, 0, "logo") is None

    def test_stop_target_only_clears_requested_target(self) -> None:
        engine = self._make_engine()

        with _patched_engine_runtime():
            engine.play(_PixelAnimation(color="#ff0000"))
            engine.play(_PixelAnimation(color="#0000ff", is_big=False), target="logo")
            engine.update()
            engine.stop_target("logo")

        assert engine.has_active_animation
        assert engine.get_color(0, 0, "banner") == "#ff0000"
        assert engine.get_color(0, 0, "logo") is None

    def test_play_higher_priority_preempts_lower_priority(self) -> None:
        engine = self._make_engine()

        with _patched_engine_runtime():
            engine.play(_PixelAnimation(color="#ff0000"), priority=AnimationPriority.PERIODIC)
            engine.play(_PixelAnimation(color="#0000ff"), priority=AnimationPriority.ACTIVITY)
            engine.update()

        assert engine.get_color(0, 0) == "#0000ff"

    def test_lower_priority_animation_runs_after_active_animation_completes(self) -> None:
        engine = self._make_engine()

        with _patched_engine_runtime():
            engine.play(_PixelAnimation(color="#ff0000", frames_to_complete=1), priority=AnimationPriority.ACTIVITY)
            engine.play(_PixelAnimation(color="#0000ff"), priority=AnimationPriority.PERIODIC)
            engine.update()
            first_color = engine.get_color(0, 0)
            engine.update()
            second_color = engine.get_color(0, 0)

        assert first_color == "#ff0000"
        assert second_color == "#0000ff"

    def test_clear_colors_removes_rendered_pixels(self) -> None:
        engine = self._make_engine()

        with _patched_engine_runtime():
            engine.play(_PixelAnimation())
            engine.update()
            engine.clear_colors()

        assert engine.get_color(0, 0) is None

    def test_update_returns_false_when_nothing_is_running(self) -> None:
        engine = self._make_engine()

        with _patched_engine_runtime():
            assert engine.update() is False

    def test_looping_animation_stays_active_after_completion(self) -> None:
        engine = self._make_engine()

        with _patched_engine_runtime():
            engine.play(_PixelAnimation(frames_to_complete=1))
            engine.set_looping("banner", True)
            engine.update()
            engine.update()

        assert engine.has_active_animation
        assert engine.get_color(0, 0) == "#ff0000"

    def test_update_handles_crashing_animation_without_leaving_visible_pixels(self) -> None:
        engine = self._make_engine()

        class CrashingAnimation(Animation):
            def __init__(self) -> None:
                super().__init__(
                    palette=SpectrumPalette(),
                    is_big=True,
                    duration_seconds=0.5,
                    speed_ms=100,
                    seed=0,
                )
                self.duration_frames = 2

            def update(self, frame: int) -> dict[tuple[int, int], str | int]:
                raise RuntimeError("boom")

        with _patched_engine_runtime():
            engine.play(CrashingAnimation())
            engine.update()
            engine.update()

        assert not engine.has_active_animation
        assert engine.get_color(0, 0) is None

    def test_get_entity_z_levels_excludes_background_layer(self) -> None:
        engine = self._make_engine()

        with _patched_engine_runtime():
            engine.play(_BufferAnimation())
            engine.update()

        assert engine.get_entity_z_levels("banner") == [50]
        assert engine.get_layer_color(Z50, 1, 0, "banner") == "#00ff00"

    def test_refresh_theme_updates_running_animation_context(self) -> None:
        engine = self._make_engine()
        animation = _PixelAnimation()

        with _patched_engine_runtime(dark_mode=False, background_hex="#123456"):
            engine.play(animation)

        with _patched_engine_runtime(dark_mode=True, background_hex="#abcdef"):
            engine.refresh_theme()

        assert animation.dark_mode is True
        assert animation.background_hex == "#abcdef"
