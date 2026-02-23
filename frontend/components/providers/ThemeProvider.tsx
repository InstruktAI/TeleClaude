'use client'

/**
 * Unified theme provider that wraps next-themes and injects TeleClaude CSS variables.
 *
 * Responsibilities:
 * - Preserve next-themes dark/light mode toggle via `attribute="class"`
 * - Inject CSS variables on mount
 * - Re-inject CSS variables when theme changes (dark <-> light)
 *
 * Usage:
 *   Wrap the app in layout.tsx with this provider instead of next-themes directly.
 */

import { ThemeProvider as NextThemesProvider, useTheme } from 'next-themes'
import { useEffect, type ReactNode } from 'react'
import { injectCSSVariables, type ThemeMode } from '@/lib/theme/css-variables'

interface ThemeProviderProps {
  children: ReactNode
  attribute?: 'class' | 'data-theme'
  defaultTheme?: string
  enableSystem?: boolean
}

/**
 * Inner component that reads the resolved theme and injects CSS variables.
 *
 * Must be inside NextThemesProvider to access useTheme().
 */
function CSSVariableInjector() {
  const { resolvedTheme } = useTheme()

  useEffect(() => {
    // Map next-themes resolved theme to our ThemeMode type
    const mode: ThemeMode = resolvedTheme === 'light' ? 'light' : 'dark'
    injectCSSVariables(mode)
  }, [resolvedTheme])

  return null
}

/**
 * Unified theme provider.
 *
 * Wraps next-themes and injects TeleClaude CSS variables on mount and theme change.
 */
export function ThemeProvider({
  children,
  attribute = 'class',
  defaultTheme = 'system',
  enableSystem = true,
}: ThemeProviderProps) {
  return (
    <NextThemesProvider
      attribute={attribute}
      defaultTheme={defaultTheme}
      enableSystem={enableSystem}
    >
      <CSSVariableInjector />
      {children}
    </NextThemesProvider>
  )
}
