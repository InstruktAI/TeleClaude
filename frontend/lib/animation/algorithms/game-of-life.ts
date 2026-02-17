/**
 * Conway's Game of Life running on the pixel grid.
 *
 * The initial state is seeded from the frame number so the simulation
 * is deterministic. Standard B3/S23 rules run each frame. Living cells
 * receive a palette color; dead cells are cleared.
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

export const gameOfLife: AnimationAlgorithm = (frame, config, target) => {
  const grid = new Map<string, number>()
  const { width, height } = target
  const paletteLen = config.palette.length
  if (paletteLen === 0 || width === 0 || height === 0) return grid

  const validPixels = new Set(target.pixels.map(([x, y]) => colorKey(x, y)))

  // Determine generation epoch: reinitialize every 60 frames so it stays lively
  const epoch = Math.floor(frame / 60)
  const genInEpoch = frame % 60

  // Initialize board from epoch seed
  const rng = seededRandom(epoch * 6271 + 43)
  let board: boolean[][] = Array.from({ length: height }, () =>
    Array.from({ length: width }, () => rng() < config.intensity * 0.5),
  )

  // Run genInEpoch generations
  for (let g = 0; g < genInEpoch; g++) {
    const next: boolean[][] = Array.from({ length: height }, () =>
      new Array<boolean>(width).fill(false),
    )
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        let neighbors = 0
        for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            if (dx === 0 && dy === 0) continue
            const ny = (y + dy + height) % height
            const nx = (x + dx + width) % width
            if (board[ny][nx]) neighbors++
          }
        }
        if (board[y][x]) {
          next[y][x] = neighbors === 2 || neighbors === 3
        } else {
          next[y][x] = neighbors === 3
        }
      }
    }
    board = next
  }

  // Map to color grid
  const colorIdx = epoch % paletteLen
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const key = colorKey(x, y)
      if (!validPixels.has(key)) continue
      grid.set(key, board[y][x] ? colorIdx : -1)
    }
  }

  return grid
}
