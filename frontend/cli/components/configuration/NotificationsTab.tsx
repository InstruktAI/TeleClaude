/**
 * NotificationsTab — Shows notification configuration.
 *
 * Displays TTS settings (enabled/disabled, voice selection)
 * and notification channels (which adapters receive notifications).
 * Toggle settings with Enter key.
 */

import React, { useState } from 'react'
import { Box, Text, useInput } from 'ink'
import type { Settings } from '../../../lib/api/types.js'

export interface NotificationsTabProps {
  settings: Settings
  onToggleTTS: () => void
}

export function NotificationsTab({ settings, onToggleTTS }: NotificationsTabProps) {
  const [selectedIndex, setSelectedIndex] = useState(0)

  const items = [
    {
      label: 'Text-to-Speech (TTS)',
      value: settings.tts.enabled ? 'Enabled' : 'Disabled',
      color: settings.tts.enabled ? 'green' : 'red',
      action: onToggleTTS,
    },
    {
      label: 'Pane Theming Mode',
      value: settings.pane_theming_mode,
      color: 'cyan',
      action: () => {
        // TODO: Implement pane theming toggle
      },
    },
  ]

  useInput((input, key) => {
    if (key.upArrow && selectedIndex > 0) {
      setSelectedIndex(selectedIndex - 1)
    } else if (key.downArrow && selectedIndex < items.length - 1) {
      setSelectedIndex(selectedIndex + 1)
    } else if (key.return) {
      items[selectedIndex]?.action()
    }
  })

  return (
    <Box flexDirection="column" paddingLeft={2} paddingTop={1}>
      <Box marginBottom={1}>
        <Text bold>Notification Settings</Text>
      </Box>
      {items.map((item, i) => {
        const isSelected = i === selectedIndex

        return (
          <Box key={item.label} marginBottom={0}>
            <Text color={isSelected ? 'yellow' : undefined} bold={isSelected}>
              {isSelected ? '▶ ' : '  '}
            </Text>
            <Text bold={isSelected}>{item.label}</Text>
            <Text dimColor>: </Text>
            <Text color={item.color}>{item.value}</Text>
          </Box>
        )
      })}
      <Box marginTop={1}>
        <Text dimColor>Press Enter to toggle selected setting</Text>
      </Box>
    </Box>
  )
}
