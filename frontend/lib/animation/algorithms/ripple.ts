/**
 * Concentric circle ripples expanding from multiple points.
 *
 * Each ripple source emits rings that grow outward and fade with
 * distance. Multiple overlapping ripples combine additively,
 * mapped to palette indices for a water-drop interference pattern.
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

export const ripple: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { width, height } = target
  const paletteLen = config.palette.length
  if (paletteLen === 0 || width === 0 || height === 0) return grid

  // Generate ripple sources deterministically
  const numSources = Math.max(2, Math.ceil(4 * config.intensity))
  const sources: { cx: number; cy: number; startFrame: number }[] = []

  for (let i = 0; i < numSources; i++) {
    const rng = seededRandom(i * 3571 + 7)
    const cycleLen = 30 + Math.floor(rng() * 30)
    // Each source restarts at a staggered interval
    const offset = Math.floor(rng() * cycleLen)
    const epoch = Math.floor((frame + offset) / cycleLen)
    const epochRng = seededRandom(epoch * 8291 + i * 1117)
    sources.push({
      cx: Math.floor(epochRng() * width),
      cy: Math.floor(epochRng() * height),
      startFrame: epoch * cycleLen - offset,
    })
  }

  const maxRadius = Math.sqrt(width * width + height * height)

  for (const [x, y] of target.pixels) {
    let totalIntensity = 0

    for (const src of sources) {
      const age = frame - src.startFrame
      if (age < 0) continue

      const dx = x - src.cx
      const dy = y - src.cy
      const dist = Math.sqrt(dx * dx + dy * dy)

      // Ripple ring: sine wave expanding outward
      const radius = age * config.speed * 0.8
      const ringDist = Math.abs(dist - radius)
      const ringWidth = 2.5

      if (ringDist < ringWidth) {
        // Fade with age and ring position
        const fadeFactor = Math.max(0, 1 - radius / maxRadius)
        const ringFactor = 1 - ringDist / ringWidth
        totalIntensity += ringFactor * fadeFactor
      }
    }

    if (totalIntensity > 0.05) {
      const clamped = Math.min(1, totalIntensity)
      const colorIdx = Math.floor(clamped * (paletteLen - 1))
      grid.set(colorKey(x, y), colorIdx)
    } else {
      grid.set(colorKey(x, y), -1)
    }
  }

  return grid
}
