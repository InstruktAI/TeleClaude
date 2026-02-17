/**
 * AdaptersTab — Lists configured adapters (Telegram, Discord, etc.)
 *
 * Each adapter shows: name, type, connection status.
 * Status indicator: green ● for connected, red ● for disconnected.
 */

import React, { useState } from 'react'
import { Box, Text, useInput } from 'ink'

export interface AdapterInfo {
  name: string
  type: string
  connected: boolean
}

export interface AdaptersTabProps {
  adapters: AdapterInfo[]
}

export function AdaptersTab({ adapters }: AdaptersTabProps) {
  const [selectedIndex, setSelectedIndex] = useState(0)

  useInput((input, key) => {
    if (key.upArrow && selectedIndex > 0) {
      setSelectedIndex(selectedIndex - 1)
    } else if (key.downArrow && selectedIndex < adapters.length - 1) {
      setSelectedIndex(selectedIndex + 1)
    }
  })

  if (adapters.length === 0) {
    return (
      <Box paddingLeft={2} paddingTop={1}>
        <Text dimColor>No adapters configured</Text>
      </Box>
    )
  }

  return (
    <Box flexDirection="column" paddingLeft={2} paddingTop={1}>
      {adapters.map((adapter, i) => {
        const isSelected = i === selectedIndex
        const statusColor = adapter.connected ? 'green' : 'red'
        const statusIcon = adapter.connected ? '●' : '●'

        return (
          <Box key={adapter.name} marginBottom={0}>
            <Text color={isSelected ? 'yellow' : undefined} bold={isSelected}>
              {isSelected ? '▶ ' : '  '}
            </Text>
            <Text color={statusColor}>{statusIcon}</Text>
            <Text> </Text>
            <Text bold={isSelected}>{adapter.name}</Text>
            <Text dimColor> ({adapter.type})</Text>
            <Text dimColor> - </Text>
            <Text color={statusColor}>
              {adapter.connected ? 'connected' : 'disconnected'}
            </Text>
          </Box>
        )
      })}
    </Box>
  )
}
