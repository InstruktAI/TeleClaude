/**
 * Color wave travels across the width with a trailing brightness gradient.
 *
 * A single column is fully lit; columns within 5 positions trail with
 * the previous palette color. All other columns are cleared.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const wavePulse: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { width } = target

  const paletteLen = config.palette.length
  if (paletteLen === 0 || width === 0) return grid

  const activeX = frame % width
  const primaryIdx = Math.floor(frame / width) % paletteLen
  const trailIdx = (primaryIdx - 1 + paletteLen) % paletteLen

  for (let x = 0; x < width; x++) {
    const dist = Math.abs(x - activeX)
    let value: number
    if (dist === 0) {
      value = primaryIdx
    } else if (dist < 5) {
      value = trailIdx
    } else {
      value = -1
    }

    const colPixels = target.getColumnPixels(x)
    for (const [px, py] of colPixels) {
      grid.set(colorKey(px, py), value)
    }
  }
  return grid
}
