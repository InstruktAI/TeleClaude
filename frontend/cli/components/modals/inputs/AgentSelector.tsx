/**
 * Agent radio selection component.
 *
 * Displays Claude, Gemini, and Codex as radio options with agent-colored dots.
 * Unavailable agents are grayed out and not selectable.
 * Navigation: Up/Down or j/k to move, Enter/Space to select.
 */

import React, { useState, useCallback, useEffect } from "react";
import { Box, Text, useInput } from "ink";

import type { AgentName, AgentAvailabilityInfo } from "@/lib/api/types.js";
import { agentColor, themeText } from "@/lib/theme/ink-colors.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const AGENTS: { name: AgentName; label: string }[] = [
  { name: "claude", label: "Claude" },
  { name: "gemini", label: "Gemini" },
  { name: "codex", label: "Codex" },
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AgentSelectorProps {
  value: AgentName;
  onChange: (agent: AgentName) => void;
  availability?: Record<string, AgentAvailabilityInfo>;
  isFocused?: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isSelectable(
  agent: AgentName,
  availability?: Record<string, AgentAvailabilityInfo>,
): boolean {
  if (!availability) return true;
  const info = availability[agent];
  if (!info) return true;
  // "available" and "degraded" are selectable; "unavailable" is not
  return info.status !== "unavailable";
}

function isDegraded(
  agent: AgentName,
  availability?: Record<string, AgentAvailabilityInfo>,
): boolean {
  if (!availability) return false;
  const info = availability[agent];
  return info?.status === "degraded";
}

function getSelectableIndices(
  availability?: Record<string, AgentAvailabilityInfo>,
): number[] {
  return AGENTS.map((a, i) => ({ a, i }))
    .filter(({ a }) => isSelectable(a.name, availability))
    .map(({ i }) => i);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AgentSelector({
  value,
  onChange,
  availability,
  isFocused = false,
}: AgentSelectorProps) {
  const currentIndex = AGENTS.findIndex((a) => a.name === value);
  const [highlightIndex, setHighlightIndex] = useState(
    currentIndex >= 0 ? currentIndex : 0,
  );

  // Sync highlight when value changes externally
  useEffect(() => {
    const idx = AGENTS.findIndex((a) => a.name === value);
    if (idx >= 0) setHighlightIndex(idx);
  }, [value]);

  const navigateToSelectable = useCallback(
    (direction: 1 | -1) => {
      const selectable = getSelectableIndices(availability);
      if (selectable.length === 0) return;

      const currentPos = selectable.indexOf(highlightIndex);
      let nextPos: number;
      if (currentPos === -1) {
        nextPos = direction === 1 ? 0 : selectable.length - 1;
      } else {
        nextPos =
          (currentPos + direction + selectable.length) % selectable.length;
      }
      setHighlightIndex(selectable[nextPos]!);
    },
    [highlightIndex, availability],
  );

  useInput(
    (input, key) => {
      if (!isFocused) return;

      if (key.upArrow || input === "k") {
        navigateToSelectable(-1);
      } else if (key.downArrow || input === "j") {
        navigateToSelectable(1);
      } else if (key.return || input === " ") {
        const agent = AGENTS[highlightIndex];
        if (agent && isSelectable(agent.name, availability)) {
          onChange(agent.name);
        }
      }
    },
    { isActive: isFocused },
  );

  const mutedFn = themeText("muted");

  return (
    <Box flexDirection="column">
      {AGENTS.map((agent, i) => {
        const selected = agent.name === value;
        const selectable = isSelectable(agent.name, availability);
        const degraded = isDegraded(agent.name, availability);
        const highlighted = isFocused && i === highlightIndex;

        // Determine marker
        let marker: string;
        if (!selectable) {
          marker = "\u2591"; // ░ blocked
        } else if (selected) {
          marker = "\u25CF"; // ● filled
        } else {
          marker = "\u25CB"; // ○ empty
        }

        const colorFn = selectable ? agentColor(agent.name, "normal") : mutedFn;
        const labelText = degraded ? `${agent.label} (degraded)` : agent.label;

        return (
          <Box key={agent.name}>
            <Text bold={highlighted} inverse={highlighted}>
              {selectable ? (
                <Text>
                  {" "}{colorFn(marker)} {colorFn(labelText)}{" "}
                </Text>
              ) : (
                <Text dimColor>
                  {" "}{marker} {labelText}{" "}
                </Text>
              )}
            </Text>
          </Box>
        );
      })}
    </Box>
  );
}
