/**
 * Animated banner integrating the animation engine with the braille canvas.
 *
 * Replaces the static ASCII banner when animation mode is enabled. Chooses
 * the render target based on terminal width (big banner >= 82 cols, else
 * small logo), wires the engine's color grid into PixelCanvas, and provides
 * the static "TELECLAUDE" fallback when idle or disabled.
 */

import React, { useMemo } from 'react'
import { Box } from 'ink'

import { BIG_BANNER_TARGET, LOGO_TARGET } from '@/lib/animation/pixel-map.js'
import { useTuiStore } from '@/lib/store/index.js'

import { useAnimation } from './useAnimation.js'
import { PixelCanvas } from './PixelCanvas.js'

// ---------------------------------------------------------------------------
// Static fallback text
// ---------------------------------------------------------------------------

const STATIC_BANNER = [
  ' _____ _____ _     _____ _____ _       _   _   _ ____  _____',
  '|_   _| ____| |   | ____/ ____| |     / \\ | | | |  _ \\| ____|',
  '  | | |  _| | |   |  _|| |   | |    / _ \\| | | | | | |  _|',
  '  | | | |___| |___| |__| |___| |__ / ___ \\ |_| | |_| | |___',
  '  |_| |_____|_____|_____\\____|____/_/   \\_\\___/|____/|_____|',
].join('\n')

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AnimatedBanner(): React.ReactElement {
  const animationMode = useTuiStore((s) => s.animationMode)
  const { engine, colorGrid } = useAnimation('banner')

  // Responsive target selection
  const target = useMemo(() => {
    const cols = process.stdout?.columns ?? 80
    return cols >= 82 ? BIG_BANNER_TARGET : LOGO_TARGET
  }, [])

  // Current animation palette from the engine
  const palette = engine.getCurrentPalette('banner')

  return (
    <Box flexDirection="column" paddingBottom={0}>
      <PixelCanvas
        target={target}
        colorGrid={animationMode === 'off' ? new Map() : colorGrid}
        palette={palette}
        fallbackText={STATIC_BANNER}
      />
    </Box>
  )
}
