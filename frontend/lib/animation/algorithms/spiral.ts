/**
 * Archimedean spiral emanating from the center.
 *
 * The spiral rotates over time and pixels near the spiral arm receive
 * palette colors based on their distance along it. Non-spiral pixels
 * are cleared, producing a spinning helix through the banner.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

export const spiral: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { width, height } = target
  const paletteLen = config.palette.length
  if (paletteLen === 0 || width === 0 || height === 0) return grid

  const cx = width / 2
  const cy = height / 2
  const maxDist = Math.sqrt(cx * cx + cy * cy)
  const rotation = frame * config.speed * 0.06
  // Aspect ratio correction: pixels on terminal are taller than wide
  const aspect = width / height

  for (const [x, y] of target.pixels) {
    const dx = x - cx
    const dy = (y - cy) * aspect
    const dist = Math.sqrt(dx * dx + dy * dy)
    const angle = Math.atan2(dy, dx)

    // Archimedean spiral: r = a * theta
    // For each pixel, check if it lies near a spiral arm
    const spiralSpacing = 4.0
    const normDist = dist / maxDist
    const expectedAngle =
      (normDist * spiralSpacing * Math.PI * 2 + rotation) % (Math.PI * 2)
    let angleDiff = Math.abs(
      ((angle - expectedAngle + 3 * Math.PI) % (2 * Math.PI)) - Math.PI,
    )

    // Arm thickness (thinner further out)
    const thickness = 0.6 * config.intensity
    if (angleDiff < thickness) {
      const brightness = 1.0 - angleDiff / thickness
      const colorIdx = Math.floor(brightness * normDist * (paletteLen - 1))
      grid.set(colorKey(x, y), Math.min(colorIdx, paletteLen - 1))
    } else {
      grid.set(colorKey(x, y), -1)
    }
  }

  return grid
}
