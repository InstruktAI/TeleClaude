/**
 * SubTabBar — Horizontal subtab switcher for Configuration view.
 *
 * Renders tabs like: ADAPTERS | people | notifications
 * Active tab is shown in bold/highlighted.
 */

import React from 'react'
import { Box, Text } from 'ink'

export interface SubTabBarProps {
  tabs: string[]
  activeIndex: number
}

export function SubTabBar({ tabs, activeIndex }: SubTabBarProps) {
  return (
    <Box marginBottom={1}>
      {tabs.map((tab, i) => {
        const isActive = i === activeIndex
        const label = isActive ? tab.toUpperCase() : tab
        return (
          <Box key={tab} marginRight={1}>
            <Text bold={isActive} color={isActive ? 'yellow' : 'gray'}>
              {label}
            </Text>
            {i < tabs.length - 1 && (
              <Text dimColor> | </Text>
            )}
          </Box>
        )
      })}
    </Box>
  )
}
