/**
 * Braille-character pixel renderer for terminal animations.
 *
 * Converts a ColorGrid (pixel coordinates mapped to palette indices) into
 * a grid of Unicode braille characters, each representing a 2x4 sub-pixel
 * block. Dominant color within each cell determines the chalk color applied
 * to the entire braille character.
 *
 * When no animation is active (empty color grid), renders fallbackText
 * in the banner's muted theme color.
 */

import React, { useMemo } from 'react'
import { Box, Text } from 'ink'
import chalk from 'chalk'

import type { AnimationTarget, ColorGrid } from '@/lib/animation/types.js'
import { bannerColor } from '@/lib/theme/ink-colors.js'

// ---------------------------------------------------------------------------
// Braille encoding
// ---------------------------------------------------------------------------

/**
 * Braille dot layout per terminal character cell (2 columns x 4 rows):
 *
 *   [dot1][dot4]     (0,0) (1,0)
 *   [dot2][dot5]     (0,1) (1,1)
 *   [dot3][dot6]     (0,2) (1,2)
 *   [dot7][dot8]     (0,3) (1,3)
 *
 * Unicode: 0x2800 + bit pattern
 */
const DOT_BITS: number[][] = [
  // [x][y] -> bit value
  [0x01, 0x02, 0x04, 0x40], // x=0: dots 1,2,3,7
  [0x08, 0x10, 0x20, 0x80], // x=1: dots 4,5,6,8
]

/** Convert a 2x4 dot array to a single braille character. */
function toBraille(dots: boolean[][]): string {
  let code = 0x2800
  for (let x = 0; x < 2; x++) {
    for (let y = 0; y < 4; y++) {
      if (dots[x]?.[y]) {
        code |= DOT_BITS[x][y]
      }
    }
  }
  return String.fromCharCode(code)
}

// ---------------------------------------------------------------------------
// Color resolution
// ---------------------------------------------------------------------------

/**
 * Find the dominant palette index among the 8 sub-pixels of a braille cell.
 *
 * Counts occurrences of each palette index within the cell. The most
 * frequent non-negative index wins. Returns -1 when no active pixels
 * exist in the cell.
 */
function dominantColor(
  cellX: number,
  cellY: number,
  colorGrid: ColorGrid,
): number {
  const counts = new Map<number, number>()
  const pixelX = cellX * 2
  const pixelY = cellY * 4

  for (let dx = 0; dx < 2; dx++) {
    for (let dy = 0; dy < 4; dy++) {
      const key = `${pixelX + dx},${pixelY + dy}`
      const idx = colorGrid.get(key)
      if (idx !== undefined && idx >= 0) {
        counts.set(idx, (counts.get(idx) ?? 0) + 1)
      }
    }
  }

  if (counts.size === 0) return -1

  let best = -1
  let bestCount = 0
  for (const [idx, count] of counts) {
    if (count > bestCount) {
      bestCount = count
      best = idx
    }
  }
  return best
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface PixelCanvasProps {
  target: AnimationTarget
  colorGrid: ColorGrid
  /** Current palette hex colors. */
  palette: string[]
  /** Text to show when no animation is active. */
  fallbackText?: string
}

export function PixelCanvas({
  target,
  colorGrid,
  palette,
  fallbackText,
}: PixelCanvasProps): React.ReactElement {
  // When no pixels are lit, show the fallback banner text
  if (colorGrid.size === 0) {
    return <FallbackBanner text={fallbackText} />
  }

  // Terminal cell dimensions for braille grid
  const cellCols = Math.ceil(target.width / 2)
  const cellRows = Math.ceil(target.height / 4)

  // Build rows of styled braille characters
  const rows = useMemo(() => {
    const result: React.ReactElement[] = []

    for (let cy = 0; cy < cellRows; cy++) {
      const segments: React.ReactNode[] = []

      for (let cx = 0; cx < cellCols; cx++) {
        // Determine which sub-pixels are active in this cell
        const dots: boolean[][] = [
          [false, false, false, false],
          [false, false, false, false],
        ]
        const pixelX = cx * 2
        const pixelY = cy * 4

        for (let dx = 0; dx < 2; dx++) {
          for (let dy = 0; dy < 4; dy++) {
            const key = `${pixelX + dx},${pixelY + dy}`
            const idx = colorGrid.get(key)
            if (idx !== undefined && idx >= 0) {
              dots[dx][dy] = true
            }
          }
        }

        const brailleChar = toBraille(dots)
        const paletteIdx = dominantColor(cx, cy, colorGrid)

        if (paletteIdx >= 0 && paletteIdx < palette.length) {
          const hex = palette[paletteIdx]
          segments.push(
            <Text key={cx}>{chalk.hex(hex)(brailleChar)}</Text>,
          )
        } else {
          // Uncolored active pixel (palette index out of range): use dim
          segments.push(<Text key={cx} dimColor>{brailleChar}</Text>)
        }
      }

      result.push(
        <Box key={cy} flexDirection="row">
          {segments}
        </Box>,
      )
    }

    return result
  }, [colorGrid, palette, cellCols, cellRows])

  return (
    <Box flexDirection="column">
      {rows}
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Fallback
// ---------------------------------------------------------------------------

function FallbackBanner({
  text,
}: {
  text?: string
}): React.ReactElement {
  const colorFn = bannerColor()
  if (!text) {
    return <Text>{colorFn('TELECLAUDE')}</Text>
  }

  return (
    <Box flexDirection="column">
      {text.split('\n').map((line, i) => (
        <Text key={i}>{colorFn(line)}</Text>
      ))}
    </Box>
  )
}
