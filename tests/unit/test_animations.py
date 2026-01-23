"""Unit tests for TUI animations."""

import unittest
from unittest.mock import MagicMock

from teleclaude.cli.tui.animation_colors import ColorPalette, SpectrumPalette
from teleclaude.cli.tui.animation_engine import AnimationEngine
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

        engine.update()
        self.assertEqual(engine.get_color(0, 0, is_big=True), 10)

        # Test clearing
        engine.stop()
        self.assertIsNone(engine.get_color(0, 0, is_big=True))


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


if __name__ == "__main__":
    unittest.main()
