/**
 * Status bar / footer rendered at the bottom of the terminal.
 *
 * Shows:
 * - Key hints for the active view context
 * - Connection status indicator
 * - Agent availability pills
 */

import React from "react";
import { Box, Text } from "ink";

import { getFooterHints } from "@/lib/keys/bindings.js";
import type { ViewContext } from "@/lib/keys/types.js";
import {
  statusColor,
  agentColor,
  statusBarFg,
} from "@/lib/theme/ink-colors.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FooterProps {
  viewContext: ViewContext;
  connected: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Footer({ viewContext, connected }: FooterProps) {
  const hints = getFooterHints(viewContext);
  const fgFn = statusBarFg();

  // Connection indicator
  const connIndicator = connected ? statusColor("active")("●") : statusColor("error")("○");
  const connLabel = connected ? "Connected" : "Disconnected";

  return (
    <Box flexDirection="column">
      {/* Separator */}
      <Text dimColor>{"─".repeat(80)}</Text>

      {/* Key hints */}
      <Box flexDirection="row" gap={1}>
        {hints.slice(0, 10).map((hint, i) => (
          <Text key={i}>
            {fgFn(`[${hint.key}]`)} <Text dimColor>{hint.description}</Text>
          </Text>
        ))}
      </Box>

      {/* Status line: connection + agent pills */}
      <Box flexDirection="row" gap={2}>
        <Text>
          {connIndicator} {fgFn(connLabel)}
        </Text>
        <AgentPill name="Claude" agent="claude" />
        <AgentPill name="Gemini" agent="gemini" />
        <AgentPill name="Codex" agent="codex" />
      </Box>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Agent pill sub-component
// ---------------------------------------------------------------------------

function AgentPill({ name, agent }: { name: string; agent: string }) {
  const colorFn = agentColor(agent, "normal");
  return <Text>{colorFn(`● ${name}`)}</Text>;
}
