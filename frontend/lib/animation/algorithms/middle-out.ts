/**
 * Color expanding from the middle rows outward.
 *
 * Two rows symmetrically placed around the vertical center are active
 * on each frame. The expansion repeats every `halfHeight` frames,
 * advancing the palette index on each full cycle.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const middleOut: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { height } = target
  if (height === 0) return grid

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const halfHeight = Math.ceil(height / 2)
  const step = frame % halfHeight
  const midLow = Math.floor((height - 1) / 2)
  const midHigh = Math.ceil((height - 1) / 2)

  const activeRows = new Set<number>()
  activeRows.add(midLow - step)
  activeRows.add(midHigh + step)

  const colorIdx = Math.floor(frame / halfHeight) % paletteLen

  for (let r = 0; r < height; r++) {
    const rowPixels = target.getRowPixels(r)
    const value = activeRows.has(r) ? colorIdx : -1
    for (const [x, y] of rowPixels) {
      grid.set(colorKey(x, y), value)
    }
  }
  return grid
}
