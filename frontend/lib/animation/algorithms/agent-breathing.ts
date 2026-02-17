/**
 * Slow sine-wave intensity modulation with agent colors.
 *
 * All pixels follow an 8-frame breathing pattern that dwells at each
 * intensity level for 2 frames, creating a gentle inhale-exhale rhythm:
 * subtle, subtle, normal, normal, highlight, highlight, normal, normal.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

/** Breathing sequence with doubled steps for smooth easing. */
const BREATHING_SEQUENCE = [0, 0, 1, 1, 2, 2, 1, 1]

export const agentBreathing: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const seqIdx = BREATHING_SEQUENCE[frame % BREATHING_SEQUENCE.length]
  const colorIdx = Math.min(seqIdx, paletteLen - 1)

  for (const [x, y] of target.pixels) {
    grid.set(colorKey(x, y), colorIdx)
  }
  return grid
}
