/**
 * ConfigurationView — Main configuration view container.
 *
 * Displays SubTabBar at top, active tab content below.
 * Subtabs: Adapters, People, Notifications
 * Keyboard: left/right to switch subtabs, up/down within tabs.
 * Loads settings from API on mount.
 */

import React, { useEffect, useState } from 'react'
import { Box, Text, useInput } from 'ink'

import { TelecAPIClient } from '../../../lib/api/client.js'
import type { PersonInfo, Settings } from '../../../lib/api/types.js'
import { useTuiStore } from '../../../lib/store/index.js'

import { AdaptersTab, type AdapterInfo } from './AdaptersTab.js'
import { NotificationsTab } from './NotificationsTab.js'
import { PeopleTab } from './PeopleTab.js'
import { SubTabBar } from './SubTabBar.js'

const SUBTABS = ['adapters', 'people', 'notifications'] as const
type Subtab = typeof SUBTABS[number]

export interface ConfigurationViewProps {
  api: TelecAPIClient
}

export function ConfigurationView({ api }: ConfigurationViewProps) {
  const { config, dispatch } = useTuiStore()
  const [settings, setSettings] = useState<Settings | null>(null)
  const [people, setPeople] = useState<PersonInfo[]>([])
  const [adapters, setAdapters] = useState<AdapterInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Map config subtab to array index
  const activeIndex = SUBTABS.indexOf(config.activeSubtab as Subtab)
  const currentSubtab = SUBTABS[activeIndex >= 0 ? activeIndex : 0]

  // Load data on mount
  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true)
        const [settingsData, peopleData] = await Promise.all([
          api.getSettings(),
          api.getPeople(),
        ])
        setSettings(settingsData)
        setPeople(peopleData)

        // Mock adapter data (in real implementation, fetch from API)
        setAdapters([
          { name: 'Telegram', type: 'telegram', connected: true },
          { name: 'Discord', type: 'discord', connected: false },
        ])
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load configuration')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [api])

  // Keyboard navigation
  useInput((input, key) => {
    if (key.leftArrow && activeIndex > 0) {
      dispatch({
        type: 'SET_CONFIG_SUBTAB',
        subtab: SUBTABS[activeIndex - 1],
      })
    } else if (key.rightArrow && activeIndex < SUBTABS.length - 1) {
      dispatch({
        type: 'SET_CONFIG_SUBTAB',
        subtab: SUBTABS[activeIndex + 1],
      })
    }
  })

  // Toggle TTS handler
  const handleToggleTTS = async () => {
    if (!settings) return
    try {
      const updated = await api.patchSettings({
        tts: { enabled: !settings.tts.enabled },
      })
      setSettings(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update settings')
    }
  }

  if (loading) {
    return (
      <Box paddingLeft={2} paddingTop={1}>
        <Text dimColor>Loading configuration...</Text>
      </Box>
    )
  }

  if (error) {
    return (
      <Box paddingLeft={2} paddingTop={1}>
        <Text color="red">Error: {error}</Text>
      </Box>
    )
  }

  if (!settings) {
    return (
      <Box paddingLeft={2} paddingTop={1}>
        <Text dimColor>No settings loaded</Text>
      </Box>
    )
  }

  return (
    <Box flexDirection="column">
      <Box paddingLeft={2} paddingTop={1}>
        <SubTabBar tabs={SUBTABS.map(String)} activeIndex={activeIndex} />
      </Box>

      {currentSubtab === 'adapters' && <AdaptersTab adapters={adapters} />}
      {currentSubtab === 'people' && <PeopleTab people={people} />}
      {currentSubtab === 'notifications' && (
        <NotificationsTab settings={settings} onToggleTTS={handleToggleTTS} />
      )}
    </Box>
  )
}
