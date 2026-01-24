"""Unit tests for TUI animations."""

import time
import unittest
from unittest.mock import MagicMock

from teleclaude.cli.tui.animation_colors import ColorPalette
from teleclaude.cli.tui.animation_engine import AnimationEngine, AnimationPriority
from teleclaude.cli.tui.animation_triggers import filter_animations
from teleclaude.cli.tui.animations.base import Animation
from teleclaude.cli.tui.animations.general import FullSpectrumCycle
from teleclaude.cli.tui.pixel_mapping import PixelMap


class TestPixelMapping(unittest.TestCase):
    def test_get_all_pixels(self):
        big_pixels = PixelMap.get_all_pixels(is_big=True)
        self.assertEqual(len(big_pixels), 82 * 6)

        logo_pixels = PixelMap.get_all_pixels(is_big=False)
        self.assertEqual(len(logo_pixels), 39 * 3)

    def test_get_row_pixels(self):
        row0 = PixelMap.get_row_pixels(is_big=True, row_idx=0)
        self.assertEqual(len(row0), 82)
        for x, y in row0:
            self.assertEqual(y, 0)


class TestAnimationEngine(unittest.TestCase):
    def test_engine_update(self):
        engine = AnimationEngine()
        palette = MagicMock(spec=ColorPalette)
        palette.get.return_value = 10
        palette.__len__.return_value = 7

        animation = FullSpectrumCycle(palette, is_big=True, duration_seconds=1.0, speed_ms=100)
        engine.play(animation)

        # Wait for enough time to pass for first frame
        time.sleep(0.11)
        engine.update()
        self.assertEqual(engine.get_color(0, 0, is_big=True), 10)

        # Test clearing
        engine.stop()
        self.assertIsNone(engine.get_color(0, 0, is_big=True))

    def test_engine_clear_on_completion(self):
        """Test that colors are cleared when animation completes."""
        engine = AnimationEngine()
        palette = MagicMock(spec=ColorPalette)
        palette.get.return_value = 10
        palette.__len__.return_value = 7

        # Very short animation (1 frame)
        animation = FullSpectrumCycle(palette, is_big=True, duration_seconds=0.1, speed_ms=100)
        engine.play(animation)

        # First update should set colors
        engine.update()
        time.sleep(0.11)  # Wait for animation to be ready for next frame
        engine.update()

        # After completion, colors should be cleared
        self.assertIsNone(engine.get_color(0, 0, is_big=True))

    def test_priority_queue(self):
        """Test that activity animations interrupt periodic animations."""
        engine = AnimationEngine()
        palette = MagicMock(spec=ColorPalette)
        palette.get.return_value = 10
        palette.__len__.return_value = 7

        # Start periodic animation
        periodic_anim = FullSpectrumCycle(palette, is_big=True, duration_seconds=5.0, speed_ms=100)
        engine.play(periodic_anim, priority=AnimationPriority.PERIODIC)
        self.assertEqual(engine._big_priority, AnimationPriority.PERIODIC)

        # Activity animation should interrupt
        activity_anim = FullSpectrumCycle(palette, is_big=True, duration_seconds=2.0, speed_ms=100)
        engine.play(activity_anim, priority=AnimationPriority.ACTIVITY)
        self.assertEqual(engine._big_priority, AnimationPriority.ACTIVITY)

    def test_small_and_big_simultaneous(self):
        """Test that big and small animations run simultaneously."""
        engine = AnimationEngine()
        palette = MagicMock(spec=ColorPalette)
        palette.get.return_value = 10
        palette.__len__.return_value = 7

        big_anim = FullSpectrumCycle(palette, is_big=True, duration_seconds=1.0, speed_ms=100)
        small_anim = FullSpectrumCycle(palette, is_big=False, duration_seconds=1.0, speed_ms=100)

        engine.play(big_anim)
        engine.play(small_anim)

        # Wait for enough time to pass for first frame
        time.sleep(0.11)
        engine.update()

        # Both should have colors
        self.assertIsNotNone(engine.get_color(0, 0, is_big=True))
        self.assertIsNotNone(engine.get_color(0, 0, is_big=False))

    def test_engine_disabled(self):
        """Test that animations don't play when engine is disabled."""
        engine = AnimationEngine()
        engine.is_enabled = False

        palette = MagicMock(spec=ColorPalette)
        palette.get.return_value = 10
        palette.__len__.return_value = 7

        animation = FullSpectrumCycle(palette, is_big=True, duration_seconds=1.0, speed_ms=100)
        engine.play(animation)

        # Animation should not have started
        self.assertIsNone(engine._big_animation)


class TestAnimations(unittest.TestCase):
    def test_full_spectrum_cycle(self):
        palette = MagicMock(spec=ColorPalette)
        palette.__len__.return_value = 7
        palette.get.side_effect = lambda i: 30 + (i % 7)

        anim = FullSpectrumCycle(palette, is_big=True, duration_seconds=1.0)

        # Frame 0
        colors = anim.update(0)
        self.assertEqual(colors[(0, 0)], 30)

        # Frame 1
        colors = anim.update(1)
        self.assertEqual(colors[(0, 0)], 31)


class TestAnimationTriggers(unittest.TestCase):
    def test_filter_animations_empty_subset(self):
        """Test that empty subset returns all animations."""
        from teleclaude.cli.tui.animations.general import GENERAL_ANIMATIONS

        filtered = filter_animations(GENERAL_ANIMATIONS, [])
        self.assertEqual(filtered, GENERAL_ANIMATIONS)

    def test_filter_animations_by_name(self):
        """Test that subset filters animations by class name."""
        from teleclaude.cli.tui.animations.general import GENERAL_ANIMATIONS

        subset = ["FullSpectrumCycle"]
        filtered = filter_animations(GENERAL_ANIMATIONS, subset)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].__name__, "FullSpectrumCycle")

    def test_filter_animations_no_match(self):
        """Test that non-matching subset returns empty list."""
        from teleclaude.cli.tui.animations.general import GENERAL_ANIMATIONS

        subset = ["NonExistentAnimation"]
        filtered = filter_animations(GENERAL_ANIMATIONS, subset)
        self.assertEqual(len(filtered), 0)


if __name__ == "__main__":
    unittest.main()
