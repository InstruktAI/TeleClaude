/**
 * Moving spotlight across the banner using agent colors.
 *
 * A bright cluster travels horizontally across the target. Pixels within
 * 2 columns of the center are highlighted, within 4 columns are normal,
 * and the rest are subtle. Creates a scanning/searchlight effect.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

const SPOTLIGHT_RADIUS = 4
const INNER_RADIUS = 2

export const agentSpotlight: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const width = target.width
  if (width === 0) return grid

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const activeX = frame % width

  const highlightIdx = Math.min(2, paletteLen - 1)
  const normalIdx = Math.min(1, paletteLen - 1)
  const subtleIdx = 0

  for (let col = 0; col < width; col++) {
    const dist = Math.abs(col - activeX)
    let colorIdx: number
    if (dist < INNER_RADIUS) {
      colorIdx = highlightIdx
    } else if (dist < SPOTLIGHT_RADIUS) {
      colorIdx = normalIdx
    } else {
      colorIdx = subtleIdx
    }
    const colPixels = target.getColumnPixels(col)
    for (const [x, y] of colPixels) {
      grid.set(colorKey(x, y), colorIdx)
    }
  }
  return grid
}
