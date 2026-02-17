/**
 * Smooth fade cycle through agent color levels.
 *
 * All pixels uniformly transition through the palette in a
 * ping-pong pattern: subtle -> normal -> highlight -> normal -> (repeat).
 * This creates a smooth continuous fade rather than a sharp jump.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

/** Ping-pong sequence: up then back down (excluding endpoints on return). */
const FADE_SEQUENCE = [0, 1, 2, 1]

export const agentFadeCycle: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const seqIdx = FADE_SEQUENCE[frame % FADE_SEQUENCE.length]
  const colorIdx = Math.min(seqIdx, paletteLen - 1)

  for (const [x, y] of target.pixels) {
    grid.set(colorKey(x, y), colorIdx)
  }
  return grid
}
