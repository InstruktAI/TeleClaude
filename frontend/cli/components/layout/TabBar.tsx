/**
 * Tab bar component for switching between Sessions, Preparation, and
 * Configuration views.
 *
 * Renders three tabs horizontally with the active tab highlighted.
 * Tab numbers (1/2/3) are shown for keyboard shortcut discoverability.
 */

import React from "react";
import { Box, Text } from "ink";

import { agentColor, tabLineColor } from "@/lib/theme/ink-colors.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TabBarProps {
  activeTab: "sessions" | "preparation" | "configuration";
}

// ---------------------------------------------------------------------------
// Tab definitions
// ---------------------------------------------------------------------------

const TABS = [
  { key: "sessions" as const, label: "Sessions", number: "1" },
  { key: "preparation" as const, label: "Preparation", number: "2" },
  { key: "configuration" as const, label: "Configuration", number: "3" },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TabBar({ activeTab }: TabBarProps) {
  const lineFn = tabLineColor();

  return (
    <Box flexDirection="column">
      <Box flexDirection="row" gap={1}>
        {TABS.map((tab) => {
          const isActive = tab.key === activeTab;

          if (isActive) {
            // Active tab: agent-colored highlight with brackets
            const highlight = agentColor("claude", "normal");
            return (
              <Text key={tab.key}>
                {highlight(`[ ${tab.number}: ${tab.label} ]`)}
              </Text>
            );
          }

          // Inactive tab: muted
          return (
            <Text key={tab.key} dimColor>
              {"  "}
              {tab.number}: {tab.label}
              {"  "}
            </Text>
          );
        })}
      </Box>
      <Text>{lineFn("─".repeat(80))}</Text>
    </Box>
  );
}
