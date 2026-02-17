/**
 * Success burst: expanding ring from center then fade.
 *
 * A thin ring of color expands outward from the horizontal center of the
 * target. The ring radius grows with frame progress and the palette color
 * advances as it expands. Creates a celebratory radial flash effect.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const configSuccess: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const width = target.width
  if (width === 0) return grid

  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const halfWidth = Math.floor(width / 2)
  const maxRadius = halfWidth
  if (maxRadius === 0) return grid

  // Ring expands over time, cycling through the full radius
  const radius = frame % (maxRadius + 1)
  const colorIdx = Math.floor(frame / (maxRadius + 1)) % paletteLen
  const centerX = halfWidth

  for (let x = 0; x < width; x++) {
    const dist = Math.abs(x - centerX)
    // Thin expanding ring: only illuminate pixels near the ring edge
    if (Math.abs(dist - radius) < 2) {
      grid.set(colorKey(x, 0), colorIdx)
    }
  }
  return grid
}
