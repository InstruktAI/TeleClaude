/**
 * Individual letters shimmer through colors independently.
 *
 * Each letter gets a palette index offset by its letter index, so
 * adjacent letters display different colors. The offset uses
 * `i * 3` to spread colors across the palette.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const letterShimmer: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { letterBoundaries } = target

  const paletteLen = config.palette.length
  if (paletteLen === 0 || letterBoundaries.length === 0) return grid

  for (let i = 0; i < letterBoundaries.length; i++) {
    const colorIdx = (frame + i * 3) % paletteLen
    const pixels = target.getLetterPixels(i)
    for (const [x, y] of pixels) {
      grid.set(colorKey(x, y), colorIdx)
    }
  }
  return grid
}
