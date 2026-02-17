/**
 * Bottom-up fire simulation.
 *
 * Hot pixels ignite at the bottom row and cool as heat rises upward.
 * Each pixel averages the heat of its neighbors below plus random
 * decay, producing a flickering flame effect mapped to the palette.
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

export const fire: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { width, height } = target
  const paletteLen = config.palette.length
  if (paletteLen === 0 || width === 0 || height === 0) return grid

  const validPixels = new Set(target.pixels.map(([x, y]) => colorKey(x, y)))
  const rng = seededRandom(frame * 9973 + 1)

  // Heat buffer: rows bottom-to-top, values 0.0-1.0
  const heat: number[][] = Array.from({ length: height }, () =>
    new Array<number>(width).fill(0),
  )

  // Seed bottom row with random hot spots
  for (let x = 0; x < width; x++) {
    heat[height - 1][x] = rng() < config.intensity ? 0.7 + rng() * 0.3 : rng() * 0.3
  }

  // Propagate heat upward: average neighbors below with decay
  for (let y = height - 2; y >= 0; y--) {
    for (let x = 0; x < width; x++) {
      const below = heat[y + 1][x]
      const belowL = x > 0 ? heat[y + 1][x - 1] : below
      const belowR = x < width - 1 ? heat[y + 1][x + 1] : below
      const avg = (below + belowL + belowR) / 3
      const decay = 0.12 + rng() * 0.12
      heat[y][x] = Math.max(0, avg - decay)
    }
  }

  // Map heat to palette indices
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const key = colorKey(x, y)
      if (!validPixels.has(key)) continue
      const h = heat[y][x]
      if (h < 0.05) {
        grid.set(key, -1)
      } else {
        grid.set(key, Math.floor(h * (paletteLen - 1)))
      }
    }
  }

  return grid
}
