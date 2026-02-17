/**
 * React hook managing the AnimationEngine lifecycle.
 *
 * Creates a single engine instance per mount, wires up periodic and activity
 * triggers based on the store's animationMode, and provides the current
 * color grid to the rendering layer.
 *
 * The hook re-renders its consumer whenever the engine swaps buffers,
 * keeping the visual output in sync at the engine's configured FPS.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'

import { AnimationEngine } from '@/lib/animation/engine.js'
import { GENERAL_ALGORITHMS, AGENT_ALGORITHMS } from '@/lib/animation/algorithms/index.js'
import { BIG_BANNER_TARGET, LOGO_TARGET } from '@/lib/animation/pixel-map.js'
import { getRandomPalette, getAgentPalette } from '@/lib/animation/palettes.js'
import { PeriodicTrigger } from '@/lib/animation/triggers.js'
import { AnimationPriority } from '@/lib/animation/types.js'
import type { AnimationAlgorithm, AnimationSlot, ColorGrid } from '@/lib/animation/types.js'
import { useTuiStore } from '@/lib/store/index.js'

// ---------------------------------------------------------------------------
// Algorithm selection helpers
// ---------------------------------------------------------------------------

const generalAlgoList = Object.values(GENERAL_ALGORITHMS)
const agentAlgoList = Object.values(AGENT_ALGORITHMS)

function pickRandom<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)]
}

function buildSlot(
  algorithm: AnimationAlgorithm,
  palette: string[],
  priority: AnimationPriority,
  targetId: string,
  duration: number | null = 60,
): AnimationSlot {
  return {
    algorithm,
    config: { palette, speed: 1.0, intensity: 0.8 },
    priority,
    startFrame: 0,
    duration,
    targetId,
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseAnimationResult {
  engine: AnimationEngine
  colorGrid: ColorGrid
  isAnimating: boolean
}

export function useAnimation(targetId: string = 'banner'): UseAnimationResult {
  const engineRef = useRef<AnimationEngine | null>(null)
  const periodicRef = useRef<PeriodicTrigger | null>(null)
  const partyIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const [colorGrid, setColorGrid] = useState<ColorGrid>(new Map())
  const [isAnimating, setIsAnimating] = useState(false)

  const animationMode = useTuiStore((s) => s.animationMode)

  // Lazy engine creation (persists across re-renders, torn down on unmount).
  if (engineRef.current === null) {
    engineRef.current = new AnimationEngine()
  }
  const engine = engineRef.current

  // ------------------------------------------------------------------
  // Sync callback: polls engine front buffer on each tick
  // ------------------------------------------------------------------

  const syncFromEngine = useCallback(() => {
    const grid = engine.getColors(targetId)
    setColorGrid(new Map(grid))
    setIsAnimating(grid.size > 0)
  }, [engine, targetId])

  // ------------------------------------------------------------------
  // Register target (responsive to terminal width)
  // ------------------------------------------------------------------

  useEffect(() => {
    const cols = process.stdout?.columns ?? 80
    const target = cols >= 82 ? BIG_BANNER_TARGET : LOGO_TARGET
    engine.registerTarget(targetId, target)
  }, [engine, targetId])

  // ------------------------------------------------------------------
  // Mode-driven lifecycle
  // ------------------------------------------------------------------

  useEffect(() => {
    // Clean up previous mode state
    if (periodicRef.current) {
      periodicRef.current.stop()
      periodicRef.current = null
    }
    if (partyIntervalRef.current) {
      clearInterval(partyIntervalRef.current)
      partyIntervalRef.current = null
    }

    if (animationMode === 'off') {
      engine.stopAll()
      engine.stop()
      setColorGrid(new Map())
      setIsAnimating(false)
      return
    }

    // Start the engine tick loop
    engine.start()

    // Frame-sync: poll the front buffer at engine FPS
    const syncInterval = setInterval(syncFromEngine, Math.round(1000 / engine.fps))

    if (animationMode === 'periodic') {
      setupPeriodicMode(engine, targetId, periodicRef)
    } else if (animationMode === 'party') {
      setupPartyMode(engine, targetId, partyIntervalRef)
    }

    return () => {
      clearInterval(syncInterval)
      if (periodicRef.current) {
        periodicRef.current.stop()
        periodicRef.current = null
      }
      if (partyIntervalRef.current) {
        clearInterval(partyIntervalRef.current)
        partyIntervalRef.current = null
      }
      engine.stopAll()
      engine.stop()
    }
  }, [animationMode, engine, targetId, syncFromEngine])

  // ------------------------------------------------------------------
  // Full teardown on unmount
  // ------------------------------------------------------------------

  useEffect(() => {
    return () => {
      engine.destroy()
      engineRef.current = null
    }
  }, [engine])

  return { engine, colorGrid, isAnimating }
}

// ---------------------------------------------------------------------------
// Mode setup helpers
// ---------------------------------------------------------------------------

function setupPeriodicMode(
  engine: AnimationEngine,
  targetId: string,
  periodicRef: React.MutableRefObject<PeriodicTrigger | null>,
): void {
  const trigger = new PeriodicTrigger(60)
  periodicRef.current = trigger

  trigger.start(engine, (eng) => {
    const algorithm = pickRandom(generalAlgoList)
    const palette = getRandomPalette()
    const slot = buildSlot(algorithm, palette, AnimationPriority.PERIODIC, targetId)
    eng.play(slot)
  })

  // Fire one immediately so the banner isn't blank until the first tick
  const algorithm = pickRandom(generalAlgoList)
  const palette = getRandomPalette()
  engine.play(buildSlot(algorithm, palette, AnimationPriority.PERIODIC, targetId))
}

function setupPartyMode(
  engine: AnimationEngine,
  targetId: string,
  intervalRef: React.MutableRefObject<ReturnType<typeof setInterval> | null>,
): void {
  let index = 0
  const allAlgos = [...generalAlgoList, ...agentAlgoList]

  const cycle = () => {
    const algorithm = allAlgos[index % allAlgos.length]
    const palette = getRandomPalette()
    const slot = buildSlot(algorithm, palette, AnimationPriority.MANUAL, targetId, 40)
    engine.play(slot)
    index++
  }

  // Start first animation immediately
  cycle()
  intervalRef.current = setInterval(cycle, 4000)
}

// ---------------------------------------------------------------------------
// Agent activity helper (callable from outside the hook)
// ---------------------------------------------------------------------------

/**
 * Trigger an agent-specific animation on the given engine.
 *
 * Call this from event handlers that detect agent activity (tool use,
 * streaming, etc.) to overlay agent-colored animations.
 */
export function triggerAgentAnimation(
  engine: AnimationEngine,
  agentType: 'claude' | 'gemini' | 'codex',
  targetId: string = 'banner',
): void {
  const algorithm = pickRandom(agentAlgoList)
  const palette = getAgentPalette(agentType)
  const slot: AnimationSlot = {
    algorithm,
    config: { palette, speed: 1.0, intensity: 0.9, agentType },
    priority: AnimationPriority.ACTIVITY,
    startFrame: 0,
    duration: 30,
    targetId,
  }
  engine.play(slot)
}
