/**
 * Moving starfield with parallax depth.
 *
 * Stars spawn near the center and drift outward, brightening as they
 * approach the edges. Creates a classic flying-through-space effect
 * on the banner pixels.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

function seededRandom(seed: number): () => number {
  let s = seed
  return () => {
    s = (s * 1664525 + 1013904223) & 0xffffffff
    return (s >>> 0) / 0xffffffff
  }
}

export const starfield: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { width, height } = target
  const paletteLen = config.palette.length
  if (paletteLen === 0 || width === 0 || height === 0) return grid

  const validPixels = new Set(target.pixels.map(([x, y]) => colorKey(x, y)))
  const cx = width / 2
  const cy = height / 2
  const maxDist = Math.sqrt(cx * cx + cy * cy)
  const numStars = Math.max(4, Math.ceil(width * height * config.intensity * 0.06))
  const cycleLen = Math.max(10, Math.ceil(maxDist))

  for (let i = 0; i < numStars; i++) {
    const rng = seededRandom(i * 4919 + 17)
    // Star direction from center (angle + speed layer)
    const angle = rng() * 2 * Math.PI
    const speedLayer = 0.3 + rng() * 0.7

    // Progress along the ray: cycles based on frame
    const t = ((frame * config.speed * speedLayer + rng() * cycleLen) % cycleLen) / cycleLen
    const dist = t * maxDist

    const sx = Math.round(cx + Math.cos(angle) * dist)
    const sy = Math.round(cy + Math.sin(angle) * dist)
    const key = colorKey(sx, sy)
    if (!validPixels.has(key)) continue

    // Brightness increases with distance from center (parallax)
    const brightness = t
    const colorIdx = Math.floor(brightness * (paletteLen - 1))
    const existing = grid.get(key)
    if (existing === undefined || colorIdx > existing) {
      grid.set(key, colorIdx)
    }
  }

  return grid
}
