"""Characterization tests for animation_engine.py."""

from __future__ import annotations

from teleclaude.cli.tui.animation_colors import SpectrumPalette
from teleclaude.cli.tui.animation_engine import AnimationEngine, AnimationPriority, AnimationSlot
from teleclaude.cli.tui.animations.base import Z50, Animation, RenderBuffer


class _FakeAnimation(Animation):
    """Minimal animation for engine testing."""

    def __init__(self, frames_to_complete: int = 5, **kwargs) -> None:  # type: ignore[no-untyped-def]
        palette = SpectrumPalette()
        super().__init__(palette=palette, is_big=True, duration_seconds=0.5, speed_ms=100, seed=0, **kwargs)
        self._frames_to_complete = frames_to_complete
        self.duration_frames = frames_to_complete

    def update(self, frame: int) -> dict[tuple[int, int], str | int]:
        return {(0, 0): "#ff0000", (1, 0): "#00ff00"}


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

    def test_default_targets_exist(self) -> None:
        engine = self._make_engine()
        assert "banner" in engine._targets
        assert "logo" in engine._targets

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

    def test_play_sets_active_animation(self) -> None:
        engine = self._make_engine()
        anim = _FakeAnimation()
        engine.play(anim)
        assert engine._targets["banner"].animation is anim

    def test_play_disabled_engine_ignores(self) -> None:
        engine = self._make_engine()
        engine.is_enabled = False
        anim = _FakeAnimation()
        engine.play(anim)
        assert engine._targets["banner"].animation is None

    def test_is_enabled_false_stops_animations(self) -> None:
        engine = self._make_engine()
        engine.play(_FakeAnimation())
        engine.is_enabled = False
        assert engine._targets["banner"].animation is None

    def test_stop_clears_all_targets(self) -> None:
        engine = self._make_engine()
        engine.play(_FakeAnimation())
        engine.stop()
        for slot in engine._targets.values():
            assert slot.animation is None

    def test_stop_sets_has_active_false(self) -> None:
        engine = self._make_engine()
        engine.play(_FakeAnimation())
        engine.stop()
        assert not engine.has_active_animation

    def test_stop_target_only_stops_named(self) -> None:
        engine = self._make_engine()
        engine.play(_FakeAnimation())
        # Also play logo
        logo_anim = _FakeAnimation()
        engine.play(logo_anim, target="logo")
        engine.stop_target("logo")
        assert engine._targets["banner"].animation is not None
        assert engine._targets["logo"].animation is None

    def test_stop_nonexistent_target_no_error(self) -> None:
        engine = self._make_engine()
        engine.stop_target("nonexistent")  # Should not raise

    def test_set_looping(self) -> None:
        engine = self._make_engine()
        engine.play(_FakeAnimation())
        engine.set_looping("banner", True)
        assert engine._targets["banner"].looping

    def test_play_higher_priority_preempts(self) -> None:
        engine = self._make_engine()
        periodic = _FakeAnimation()
        activity = _FakeAnimation()
        engine.play(periodic, priority=AnimationPriority.PERIODIC)
        engine.play(activity, priority=AnimationPriority.ACTIVITY)
        assert engine._targets["banner"].animation is activity

    def test_play_lower_priority_goes_to_queue(self) -> None:
        engine = self._make_engine()
        activity = _FakeAnimation()
        periodic = _FakeAnimation()
        engine.play(activity, priority=AnimationPriority.ACTIVITY)
        engine.play(periodic, priority=AnimationPriority.PERIODIC)
        assert engine._targets["banner"].animation is activity
        assert len(engine._targets["banner"].queue) == 1

    def test_get_color_returns_none_when_disabled(self) -> None:
        engine = self._make_engine()
        engine.is_enabled = False
        assert engine.get_color(0, 0) is None

    def test_get_color_returns_none_no_buffer(self) -> None:
        engine = self._make_engine()
        assert engine.get_color(0, 0) is None

    def test_get_layer_color_returns_none_empty(self) -> None:
        engine = self._make_engine()
        assert engine.get_layer_color(Z50, 0, 0) is None

    def test_get_entity_z_levels_empty_target(self) -> None:
        engine = self._make_engine()
        assert engine.get_entity_z_levels("banner") == []

    def test_clear_colors(self) -> None:
        engine = self._make_engine()
        engine.play(_FakeAnimation())
        engine.update()  # Populate buffers
        engine.clear_colors()
        # All front/back buffers should be empty
        for buf in engine._buffers_front.values():
            assert len(buf) == 0

    def test_update_returns_bool(self) -> None:
        engine = self._make_engine()
        result = engine.update()
        assert isinstance(result, bool)

    def test_update_with_animation_returns_true(self) -> None:
        engine = self._make_engine()
        engine.play(_FakeAnimation())
        # Force elapsed time by setting last_update_ms far in the past
        engine._targets["banner"].last_update_ms = 0
        result = engine.update()
        assert result is True

    def test_update_animation_completes_clears(self) -> None:
        engine = self._make_engine()
        anim = _FakeAnimation(frames_to_complete=1)
        engine.play(anim)
        engine._targets["banner"].last_update_ms = 0
        engine.update()
        # After completion, animation is None
        assert engine._targets["banner"].animation is None

    def test_on_animation_start_callback(self) -> None:
        engine = self._make_engine()
        called_with: list[tuple[str, Animation]] = []
        engine.on_animation_start = lambda t, a: called_with.append((t, a))
        anim = _FakeAnimation()
        engine.play(anim)
        assert len(called_with) == 1
        assert called_with[0][0] == "banner"
        assert called_with[0][1] is anim

    def test_is_external_light_false_default(self) -> None:
        engine = self._make_engine()
        assert not engine.is_external_light("banner")

    def test_refresh_theme_no_error_empty(self) -> None:
        engine = self._make_engine()
        engine.refresh_theme()  # Should not raise

    def test_invalidate_term_width_no_error(self) -> None:
        engine = self._make_engine()
        engine.invalidate_term_width(100)  # Should not raise

    def test_update_animation_looping_resets_frame(self) -> None:
        engine = self._make_engine()
        anim = _FakeAnimation(frames_to_complete=1)
        engine.play(anim)
        engine.set_looping("banner", True)
        engine._targets["banner"].last_update_ms = 0
        engine.update()
        # With looping, animation stays but frame resets
        assert engine._targets["banner"].animation is anim
        assert engine._targets["banner"].frame_count == 0

    def test_update_dequeues_next_animation(self) -> None:
        engine = self._make_engine()
        anim1 = _FakeAnimation(frames_to_complete=1)
        anim2 = _FakeAnimation(frames_to_complete=5)
        engine.play(anim1, priority=AnimationPriority.ACTIVITY)
        # Queue the second one (lower priority)
        engine._targets["banner"].queue.append((anim2, AnimationPriority.PERIODIC))
        engine._targets["banner"].last_update_ms = 0
        engine.update()
        # anim1 completes, anim2 should now be active
        assert engine._targets["banner"].animation is anim2

    def test_update_handles_crashing_animation(self) -> None:
        engine = self._make_engine()

        class CrashingAnimation(Animation):
            def __init__(self) -> None:
                palette = SpectrumPalette()
                super().__init__(palette=palette, is_big=True, duration_seconds=5.0, seed=0)

            def update(self, frame: int) -> dict[tuple[int, int], str | int]:
                raise RuntimeError("crash!")

        engine.play(CrashingAnimation())
        engine._targets["banner"].last_update_ms = 0
        # Should not raise — engine swallows animation errors
        engine.update()
        assert engine._targets["banner"].animation is None

    def test_get_color_after_update_returns_value(self) -> None:
        engine = self._make_engine()
        engine.play(_FakeAnimation())
        engine._targets["banner"].last_update_ms = 0
        engine.update()
        color = engine.get_color(0, 0, "banner")
        # The fake animation puts "#ff0000" at (0,0) and it is a 7-char string
        assert color is not None
        assert len(color) == 7

    def test_update_renders_renderbuffer(self) -> None:
        """Animation returning RenderBuffer (multi-layer) is handled correctly."""

        class BufferAnimation(Animation):
            def __init__(self) -> None:
                palette = SpectrumPalette()
                super().__init__(palette=palette, is_big=True, duration_seconds=5.0, seed=0)

            def update(self, frame: int) -> RenderBuffer:
                buf = RenderBuffer()
                buf.add_pixel(Z50, 0, 0, "#0000ff")
                return buf

        engine = self._make_engine()
        engine.play(BufferAnimation())
        engine._targets["banner"].last_update_ms = 0
        engine.update()
        color = engine.get_layer_color(Z50, 0, 0, "banner")
        assert color == "#0000ff"
