/**
 * Horizontal line of color sweeping top to bottom.
 *
 * One row is active at a time, advancing downward each frame. All
 * other rows are cleared. The palette index advances on each full
 * sweep through the height.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const lineSweepTB: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { height } = target
  if (height === 0) return grid

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const activeRow = frame % height
  const colorIdx = Math.floor(frame / height) % paletteLen

  for (let r = 0; r < height; r++) {
    const rowPixels = target.getRowPixels(r)
    const value = r === activeRow ? colorIdx : -1
    for (const [x, y] of rowPixels) {
      grid.set(colorKey(x, y), value)
    }
  }
  return grid
}
