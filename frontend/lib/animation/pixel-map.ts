/**
 * Pixel mapping for animation render targets.
 *
 * Ports the Python PixelMap / TargetRegistry to TypeScript. Provides
 * pre-built targets for the big banner (82x6) and small logo (39x3),
 * plus a factory for dynamic config-section targets.
 *
 * No side effects on import.
 */

import type { AnimationTarget, LetterBoundary } from './types'

// ---------------------------------------------------------------------------
// Constants ported from pixel_mapping.py
// ---------------------------------------------------------------------------

const BIG_BANNER_WIDTH = 82
const BIG_BANNER_HEIGHT = 6

/** [startCol, endCol] per letter in "TELECLAUDE" (big banner). */
const BIG_BANNER_LETTER_COLS: [number, number][] = [
  [0, 8],   // T
  [9, 16],  // E
  [17, 24], // L
  [25, 32], // E
  [33, 40], // C
  [41, 48], // L
  [49, 56], // A
  [57, 65], // U
  [66, 73], // D
  [74, 81], // E
]

const LOGO_WIDTH = 39
const LOGO_HEIGHT = 3

/** [startCol, endCol] per letter in "TELECLAUDE" (small logo). */
const LOGO_LETTER_COLS: [number, number][] = [
  [0, 2],   // T
  [4, 6],   // E
  [8, 10],  // L
  [12, 14], // E
  [16, 18], // C
  [20, 22], // L
  [24, 26], // A
  [28, 30], // U
  [32, 34], // D
  [36, 38], // E
]

const TELECLAUDE_LABELS = ['T', 'E', 'L', 'E', 'C', 'L', 'A', 'U', 'D', 'E']

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function buildPixels(width: number, height: number): [number, number][] {
  const pixels: [number, number][] = []
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      pixels.push([x, y])
    }
  }
  return pixels
}

function buildBoundaries(
  cols: [number, number][],
  labels: string[],
): LetterBoundary[] {
  return cols.map(([startCol, endCol], i) => ({
    index: i,
    startCol,
    endCol,
    label: labels[i] ?? '',
  }))
}

function makeGetLetterPixels(
  boundaries: LetterBoundary[],
  height: number,
): (letterIndex: number) => [number, number][] {
  return (letterIndex: number): [number, number][] => {
    const b = boundaries[letterIndex]
    if (!b) return []
    const pixels: [number, number][] = []
    for (let y = 0; y < height; y++) {
      for (let x = b.startCol; x <= b.endCol; x++) {
        pixels.push([x, y])
      }
    }
    return pixels
  }
}

function makeGetRowPixels(
  width: number,
  height: number,
): (row: number) => [number, number][] {
  return (row: number): [number, number][] => {
    if (row < 0 || row >= height) return []
    const pixels: [number, number][] = []
    for (let x = 0; x < width; x++) {
      pixels.push([x, row])
    }
    return pixels
  }
}

function makeGetColumnPixels(
  width: number,
  height: number,
): (col: number) => [number, number][] {
  return (col: number): [number, number][] => {
    if (col < 0 || col >= width) return []
    const pixels: [number, number][] = []
    for (let y = 0; y < height; y++) {
      pixels.push([col, y])
    }
    return pixels
  }
}

// ---------------------------------------------------------------------------
// Target builders
// ---------------------------------------------------------------------------

function buildTarget(
  width: number,
  height: number,
  cols: [number, number][],
  labels: string[],
): AnimationTarget {
  const boundaries = buildBoundaries(cols, labels)
  return {
    width,
    height,
    pixels: buildPixels(width, height),
    letterBoundaries: boundaries,
    getLetterPixels: makeGetLetterPixels(boundaries, height),
    getRowPixels: makeGetRowPixels(width, height),
    getColumnPixels: makeGetColumnPixels(width, height),
  }
}

// ---------------------------------------------------------------------------
// Exported targets
// ---------------------------------------------------------------------------

/** Big banner target: 82 x 6 pixels, 10 letters "TELECLAUDE". */
export const BIG_BANNER_TARGET: AnimationTarget = buildTarget(
  BIG_BANNER_WIDTH,
  BIG_BANNER_HEIGHT,
  BIG_BANNER_LETTER_COLS,
  TELECLAUDE_LABELS,
)

/** Small logo target: 39 x 3 pixels, 10 letters "TELECLAUDE". */
export const LOGO_TARGET: AnimationTarget = buildTarget(
  LOGO_WIDTH,
  LOGO_HEIGHT,
  LOGO_LETTER_COLS,
  TELECLAUDE_LABELS,
)

/**
 * Create a dynamic target for config-section animations or arbitrary areas.
 *
 * The target has no letter boundaries; all pixels form one contiguous block.
 */
export function createDynamicTarget(
  width: number,
  height: number,
): AnimationTarget {
  return buildTarget(width, height, [], [])
}

// ---------------------------------------------------------------------------
// Dimensional exports (useful for algorithms that need raw constants)
// ---------------------------------------------------------------------------

export {
  BIG_BANNER_WIDTH,
  BIG_BANNER_HEIGHT,
  BIG_BANNER_LETTER_COLS,
  LOGO_WIDTH,
  LOGO_HEIGHT,
  LOGO_LETTER_COLS,
}
