/**
 * Horizontal line sweep top-to-bottom with agent color progression.
 *
 * One row is active at a time; all others are cleared (-1). The active
 * row advances each frame. The palette color cycles on each full pass
 * through the rows.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const agentLineSweep: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const height = target.height
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
