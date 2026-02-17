/**
 * Random lightning bolts with branching and flash decay.
 *
 * A bolt starts at the top of the grid and random-walks downward,
 * occasionally branching. After the bolt is drawn it flashes bright
 * then fades over several frames. A new bolt fires every N frames.
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

interface BoltSegment {
  x: number
  y: number
}

function generateBolt(
  rng: () => number,
  startX: number,
  width: number,
  height: number,
): BoltSegment[] {
  const segments: BoltSegment[] = []
  const branches: { x: number; y: number }[] = [{ x: startX, y: 0 }]

  while (branches.length > 0) {
    const branch = branches.pop()!
    let { x, y } = branch

    while (y < height) {
      segments.push({ x, y })
      // Random walk horizontally
      const drift = rng()
      if (drift < 0.3) x = Math.max(0, x - 1)
      else if (drift < 0.6) x = Math.min(width - 1, x + 1)

      // Chance to branch
      if (rng() < 0.12 && branches.length < 3) {
        branches.push({ x: Math.min(width - 1, Math.max(0, x + (rng() < 0.5 ? -2 : 2))), y })
      }
      y++
    }
  }

  return segments
}

export const lightning: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { width, height } = target
  const paletteLen = config.palette.length
  if (paletteLen === 0 || width === 0 || height === 0) return grid

  const validPixels = new Set(target.pixels.map(([x, y]) => colorKey(x, y)))
  const boltInterval = Math.max(6, Math.ceil(18 / config.speed))
  const flashDuration = 5

  // Determine which bolt epoch we are in and how far into flash
  const boltEpoch = Math.floor(frame / boltInterval)
  const frameInEpoch = frame % boltInterval

  // Only show bolt during flash phase
  if (frameInEpoch >= flashDuration) return grid

  // Generate bolt for this epoch
  const rng = seededRandom(boltEpoch * 8761 + 59)
  const startX = Math.floor(rng() * width)
  const bolt = generateBolt(rng, startX, width, height)

  // Flash brightness decays over the flash duration
  const brightness = 1.0 - frameInEpoch / flashDuration

  const colorIdx = Math.floor(brightness * (paletteLen - 1))

  // Draw bolt with thickness
  for (const seg of bolt) {
    for (let dx = -1; dx <= 1; dx++) {
      const px = seg.x + dx
      const key = colorKey(px, seg.y)
      if (!validPixels.has(key)) continue
      // Center pixel brightest, sides dimmer
      const sideAttenuation = dx === 0 ? 1.0 : 0.5
      const sideIdx = Math.floor(brightness * sideAttenuation * (paletteLen - 1))
      const existing = grid.get(key)
      if (existing === undefined || sideIdx > existing) {
        grid.set(key, sideIdx)
      }
    }
  }

  return grid
}
