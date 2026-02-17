'use client'

/**
 * Canvas-based web animation renderer.
 *
 * Renders animations from the AnimationEngine onto an HTML5 canvas element.
 * Uses requestAnimationFrame for smooth 60 FPS rendering while the engine
 * updates at 10 FPS. Automatically scales to container size and handles
 * responsive resizing.
 *
 * The engine provides palette indices; this component resolves them to hex
 * colors via the engine's getCurrentPalette method.
 */

import React, { useRef, useEffect, useState } from 'react'
import { AnimationEngine } from '@/lib/animation/engine'
import { AnimationTarget, parseColorKey } from '@/lib/animation/types'
import { BIG_BANNER_TARGET } from '@/lib/animation/pixel-map'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface CanvasAnimationProps {
  /** The animation target to render. Defaults to BIG_BANNER_TARGET. */
  target?: AnimationTarget
  /** The animation engine instance. */
  engine: AnimationEngine
  /** Target ID for engine color queries. Defaults to 'banner'. */
  targetId?: string
  /** Size of each pixel square in CSS pixels. Defaults to 4. */
  pixelSize?: number
  /** Optional className for the canvas element. */
  className?: string
  /** Whether to render a glow effect behind bright pixels. Defaults to true. */
  glow?: boolean
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CanvasAnimation({
  target = BIG_BANNER_TARGET,
  engine,
  targetId = 'banner',
  pixelSize = 4,
  className = '',
  glow = true,
}: CanvasAnimationProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 })

  // Calculate canvas dimensions based on target and pixelSize
  const canvasWidth = target.width * pixelSize
  const canvasHeight = target.height * pixelSize

  // Update dimensions when target or pixelSize changes
  useEffect(() => {
    setDimensions({ width: canvasWidth, height: canvasHeight })
  }, [canvasWidth, canvasHeight])

  // Main rendering loop
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d', { alpha: true })
    if (!ctx) return

    let animFrameId: number

    const draw = () => {
      // Get current colors from engine
      const colors = engine.getColors(targetId)
      const palette = engine.getCurrentPalette(targetId)

      // Clear canvas
      ctx.clearRect(0, 0, canvas.width, canvas.height)

      // Draw glow layer first (if enabled)
      if (glow) {
        for (const [key, paletteIndex] of colors) {
          if (paletteIndex < 0 || paletteIndex >= palette.length) continue

          const [x, y] = parseColorKey(key)
          const color = palette[paletteIndex]

          // Only glow for brighter colors (skip first 2 palette indices)
          if (paletteIndex >= 2) {
            ctx.fillStyle = color
            ctx.globalAlpha = 0.3
            ctx.fillRect(
              x * pixelSize - 1,
              y * pixelSize - 1,
              pixelSize + 2,
              pixelSize + 2,
            )
          }
        }
        ctx.globalAlpha = 1.0
      }

      // Draw main pixel layer
      for (const [key, paletteIndex] of colors) {
        if (paletteIndex < 0 || paletteIndex >= palette.length) continue

        const [x, y] = parseColorKey(key)
        const color = palette[paletteIndex]

        ctx.fillStyle = color
        ctx.fillRect(x * pixelSize, y * pixelSize, pixelSize, pixelSize)
      }

      animFrameId = requestAnimationFrame(draw)
    }

    // Start render loop
    animFrameId = requestAnimationFrame(draw)

    // Cleanup on unmount
    return () => {
      if (animFrameId) cancelAnimationFrame(animFrameId)
    }
  }, [engine, targetId, target, pixelSize, glow])

  // Handle responsive resizing (optional, for future enhancement)
  useEffect(() => {
    const handleResize = () => {
      // Could adjust pixelSize based on container size here
      // For now, just use the provided pixelSize
    }

    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  return (
    <canvas
      ref={canvasRef}
      width={dimensions.width}
      height={dimensions.height}
      className={className}
      style={{
        imageRendering: 'pixelated',
        background: 'var(--bg-base)',
      }}
    />
  )
}
