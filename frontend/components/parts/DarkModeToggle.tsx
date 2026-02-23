'use client'

import { Moon, Sun, Monitor } from 'lucide-react'
import { useTheme } from 'next-themes'
import { useEffect, useState } from 'react'

export function DarkModeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme()
  const [mounted, setMounted] = useState(false)

  // Avoid hydration mismatch
  useEffect(() => {
    setMounted(true)
  }, [])

  if (!mounted) {
    return <div className="h-8 w-8" />
  }

  const cycleTheme = () => {
    if (theme === 'system') {
      setTheme('light')
    } else if (theme === 'light') {
      setTheme('dark')
    } else {
      setTheme('system')
    }
  }

  // Determine which icon to show based on the CURRENT setting (theme)
  // but we can also use resolvedTheme to show what's actually active.
  // The user specifically mentioned "Setting it to system doesn't work".
  const Icon = theme === 'system' ? Monitor : theme === 'dark' ? Moon : Sun

  return (
    <button
      onClick={cycleTheme}
      className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent transition-colors"
      aria-label="Toggle dark mode"
      title={`Theme setting: ${theme} (currently ${resolvedTheme})`}
    >
      <Icon className="h-4 w-4" />
    </button>
  )
}
