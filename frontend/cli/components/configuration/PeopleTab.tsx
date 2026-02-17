/**
 * PeopleTab — Lists known people/contacts.
 *
 * Each person shows: name, role, email (if available).
 * Scrollable list with selection and role badge.
 */

import React, { useState } from 'react'
import { Box, Text, useInput } from 'ink'
import type { PersonInfo } from '../../../lib/api/types.js'

export interface PeopleTabProps {
  people: PersonInfo[]
}

export function PeopleTab({ people }: PeopleTabProps) {
  const [selectedIndex, setSelectedIndex] = useState(0)

  useInput((input, key) => {
    if (key.upArrow && selectedIndex > 0) {
      setSelectedIndex(selectedIndex - 1)
    } else if (key.downArrow && selectedIndex < people.length - 1) {
      setSelectedIndex(selectedIndex + 1)
    }
  })

  if (people.length === 0) {
    return (
      <Box paddingLeft={2} paddingTop={1}>
        <Text dimColor>No people configured</Text>
      </Box>
    )
  }

  return (
    <Box flexDirection="column" paddingLeft={2} paddingTop={1}>
      {people.map((person, i) => {
        const isSelected = i === selectedIndex

        return (
          <Box key={person.email ?? person.name} marginBottom={0}>
            <Text color={isSelected ? 'yellow' : undefined} bold={isSelected}>
              {isSelected ? '▶ ' : '  '}
            </Text>
            <Text bold={isSelected}>{person.name}</Text>
            <Text dimColor> [{person.role}]</Text>
            {person.email && (
              <>
                <Text dimColor> - </Text>
                <Text dimColor>{person.email}</Text>
              </>
            )}
          </Box>
        )
      })}
    </Box>
  )
}
