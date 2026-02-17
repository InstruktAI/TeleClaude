/**
 * Rhythmic heartbeat pulse with agent colors.
 *
 * All pixels follow a 6-frame repeating pattern that simulates a
 * double-beat followed by rest: highlight, subtle, highlight, subtle,
 * subtle, subtle. Uses palette indices where the last index is highlight
 * and index 0 is subtle.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

/** Beat pattern: indices into palette. Last = highlight, 0 = subtle. */
const HEARTBEAT_PATTERN = [2, 0, 2, 0, 0, 0]

export const agentHeartbeat: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const patternIdx = HEARTBEAT_PATTERN[frame % HEARTBEAT_PATTERN.length]
  const colorIdx = Math.min(patternIdx, paletteLen - 1)

  for (const [x, y] of target.pixels) {
    grid.set(colorKey(x, y), colorIdx)
  }
  return grid
}
