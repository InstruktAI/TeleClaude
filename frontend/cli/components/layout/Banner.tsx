/**
 * ASCII art banner rendering "TELECLAUDE" at the top of the terminal.
 *
 * Uses block-drawing characters matching the Python TUI's hidden-banner logo.
 * Agent-colored when a session is active; falls back to spectrum gradient when
 * idle. Animation integration deferred to WI-19.
 */

import React from "react";
import { Box, Text } from "ink";

import { bannerColor, agentColor } from "@/lib/theme/ink-colors.js";
import { useTuiStore } from "@/lib/store/index.js";

// ---------------------------------------------------------------------------
// Banner ASCII art (matches Python TUI render_banner / hidden_banner_header)
// ---------------------------------------------------------------------------

const BANNER_LINES = [
  " _____ _____ _     _____ _____ _       _   _   _ ____  _____",
  "|_   _| ____| |   | ____/ ____| |     / \\ | | | |  _ \\| ____|",
  "  | | |  _| | |   |  _|| |   | |    / _ \\| | | | | | |  _|",
  "  | | | |___| |___| |__| |___| |__ / ___ \\ |_| | |_| | |___",
  "  |_| |_____|_____|_____\\____|____/_/   \\_\\___/|____/|_____|",
];

export const BANNER_HEIGHT = BANNER_LINES.length + 1; // lines + bottom padding

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Banner() {
  const stickySessions = useTuiStore((s) => s.sessions.stickySessions);

  // Determine coloring: agent color for most recent active, else banner muted
  const hasActiveSessions = stickySessions.length > 0;
  const colorFn = hasActiveSessions
    ? agentColor("claude", "muted")
    : bannerColor();

  return (
    <Box flexDirection="column" paddingBottom={0}>
      {BANNER_LINES.map((line, i) => (
        <Text key={i}>{colorFn(line)}</Text>
      ))}
    </Box>
  );
}
