/**
 * Thinking mode radio selection component.
 *
 * Displays fast, med, and slow as radio options with brief descriptions.
 * Navigation: Up/Down to move, Enter/Space to select.
 */

import React, { useState, useEffect } from "react";
import { Box, Text, useInput } from "ink";

import type { ThinkingMode } from "@/lib/api/types.js";
import { themeText } from "@/lib/theme/ink-colors.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MODES: { value: ThinkingMode; label: string; description: string }[] = [
  { value: "fast", label: "Fast", description: "cheapest, fastest output" },
  { value: "med", label: "Med", description: "balanced cost and quality" },
  { value: "slow", label: "Slow", description: "most capable reasoning" },
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ModeSelectorProps {
  value: ThinkingMode;
  onChange: (mode: ThinkingMode) => void;
  isFocused?: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ModeSelector({
  value,
  onChange,
  isFocused = false,
}: ModeSelectorProps) {
  const currentIndex = MODES.findIndex((m) => m.value === value);
  const [highlightIndex, setHighlightIndex] = useState(
    currentIndex >= 0 ? currentIndex : 2, // default to "slow"
  );

  // Sync highlight when value changes externally
  useEffect(() => {
    const idx = MODES.findIndex((m) => m.value === value);
    if (idx >= 0) setHighlightIndex(idx);
  }, [value]);

  useInput(
    (input, key) => {
      if (!isFocused) return;

      if (key.upArrow || input === "k") {
        setHighlightIndex((prev) => Math.max(0, prev - 1));
      } else if (key.downArrow || input === "j") {
        setHighlightIndex((prev) => Math.min(MODES.length - 1, prev + 1));
      } else if (key.return || input === " ") {
        const mode = MODES[highlightIndex];
        if (mode) onChange(mode.value);
      }
    },
    { isActive: isFocused },
  );

  const secondaryFn = themeText("secondary");

  return (
    <Box flexDirection="column">
      {MODES.map((mode, i) => {
        const selected = mode.value === value;
        const highlighted = isFocused && i === highlightIndex;
        const marker = selected ? "\u25CF" : "\u25CB"; // ● or ○

        return (
          <Box key={mode.value}>
            <Text bold={highlighted} inverse={highlighted}>
              {" "}
              {marker} {mode.label}
              {"  "}
            </Text>
            <Text>{secondaryFn(mode.description)}</Text>
          </Box>
        );
      })}
    </Box>
  );
}
