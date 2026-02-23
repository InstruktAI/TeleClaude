'use client'

/**
 * Theme provider that wraps next-themes.
 *
 * All TeleClaude CSS variables are defined in globals.css under @theme (light)
 * and .dark (dark mode). This provider just handles the dark/light mode toggle.
 *
 * Usage:
 *   Wrap the app in layout.tsx with this provider.
 */

import { ThemeProvider as NextThemesProvider } from 'next-themes'
import type { ReactNode } from 'react'

interface ThemeProviderProps {
  children: ReactNode
  attribute?: 'class' | 'data-theme'
  defaultTheme?: string
  enableSystem?: boolean
}

/**
 * Theme provider.
 *
 * Wraps next-themes to handle dark/light mode switching via the 'class' attribute.
 * CSS variables are statically defined in globals.css and respond to .dark class.
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
      {children}
    </NextThemesProvider>
  )
}
