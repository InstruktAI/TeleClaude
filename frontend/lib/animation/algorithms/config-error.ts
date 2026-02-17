/**
 * Error flash: rapid on/off blinking across the full width.
 *
 * The entire target row blinks on and off in a rapid pattern, using the
 * first palette color (typically red for error palettes). The blink rate
 * is tied to frame progression -- approximately 5 blinks per cycle.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

const BLINK_DIVISOR = 2

export const configError: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const width = target.width
  if (width === 0) return grid

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  // Alternate between on and off every other frame
  const isOn = Math.floor(frame / BLINK_DIVISOR) % 2 === 0

  if (isOn) {
    for (let x = 0; x < width; x++) {
      grid.set(colorKey(x, 0), 0)
    }
  }
  return grid
}
