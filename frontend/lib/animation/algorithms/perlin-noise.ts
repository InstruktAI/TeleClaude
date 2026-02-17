/**
 * Animated Perlin noise mapped to palette colors.
 *
 * Implements a lightweight 2D gradient noise function. The z-coordinate
 * shifts with each frame, producing a smoothly evolving organic pattern
 * that flows across the banner.
 */

import type { AnimationAlgorithm } from '../types.js'
import { colorKey } from '../types.js'

// Permutation table seeded deterministically (no randomness needed at init)
const PERM: number[] = (() => {
  const p = new Array<number>(256)
  for (let i = 0; i < 256; i++) p[i] = i
  // Fisher-Yates with fixed seed
  let s = 42
  for (let i = 255; i > 0; i--) {
    s = (s * 1664525 + 1013904223) & 0xffffffff
    const j = (s >>> 0) % (i + 1)
    const tmp = p[i]
    p[i] = p[j]
    p[j] = tmp
  }
  // Double for wrapping
  return [...p, ...p]
})()

function fade(t: number): number {
  return t * t * t * (t * (t * 6 - 15) + 10)
}

function lerp(a: number, b: number, t: number): number {
  return a + t * (b - a)
}

function grad(hash: number, x: number, y: number): number {
  const h = hash & 3
  const u = h < 2 ? x : y
  const v = h < 2 ? y : x
  return (h & 1 ? -u : u) + (h & 2 ? -v : v)
}

function noise2d(x: number, y: number): number {
  const xi = Math.floor(x) & 255
  const yi = Math.floor(y) & 255
  const xf = x - Math.floor(x)
  const yf = y - Math.floor(y)

  const u = fade(xf)
  const v = fade(yf)

  const aa = PERM[PERM[xi] + yi]
  const ab = PERM[PERM[xi] + yi + 1]
  const ba = PERM[PERM[xi + 1] + yi]
  const bb = PERM[PERM[xi + 1] + yi + 1]

  return lerp(
    lerp(grad(aa, xf, yf), grad(ba, xf - 1, yf), u),
    lerp(grad(ab, xf, yf - 1), grad(bb, xf - 1, yf - 1), u),
    v,
  )
}

export const perlinNoise: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const paletteLen = config.palette.length
  if (paletteLen === 0) return grid

  const scale = 0.12
  const timeShift = frame * config.speed * 0.03

  for (const [x, y] of target.pixels) {
    // Sample noise with time-shifted coordinates
    const n = noise2d(x * scale + timeShift, y * scale + timeShift * 0.7)
    // Map from [-1,1] to [0,1]
    const value = (n + 1) / 2
    const colorIdx = Math.floor(value * (paletteLen - 1))
    grid.set(colorKey(x, y), colorIdx)
  }

  return grid
}
