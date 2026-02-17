/**
 * Computer header row in the sessions tree.
 *
 * Renders: hostname (N sessions) with online/offline status indicator.
 * Bold when selected. Muted when offline.
 *
 * Source: teleclaude/cli/tui/views/sessions.py (_render_computer_line)
 */

import React from "react";
import { Box, Text } from "ink";

import { themeText, statusColor } from "@/lib/theme/ink-colors.js";
import type { FlatTreeItem, ComputerNode as ComputerNodeType } from "@/lib/tree/types.js";
import { treePrefix } from "@/lib/tree/flatten.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ComputerNodeProps {
  /** The flat tree item carrying the computer node */
  item: FlatTreeItem;
  /** Whether this row is the currently selected item */
  isSelected: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ComputerNode({ item, isSelected }: ComputerNodeProps) {
  const node = item.node as ComputerNodeType;
  const prefix = treePrefix(item);
  const { computer, sessionCount, recentActivity } = node.data;
  const isOnline = computer.status === "online";
  const isLocal = computer.is_local;

  const primaryFn = themeText("primary");
  const mutedFn = themeText("muted");
  const activeFn = statusColor("active");

  const nameDisplay = computer.name + (isLocal ? " (local)" : "");
  const countDisplay = sessionCount > 0 ? ` (${sessionCount})` : "";
  const statusDot = isOnline ? activeFn("\u25CF ") : mutedFn("\u25CB ");

  return (
    <Box>
      <Text dimColor>{prefix}</Text>
      <Text>{statusDot}</Text>
      <Text bold={isSelected} dimColor={!isOnline && !isSelected}>
        {isSelected ? primaryFn(nameDisplay) : (isOnline ? primaryFn(nameDisplay) : mutedFn(nameDisplay))}
      </Text>
      {countDisplay && <Text>{mutedFn(countDisplay)}</Text>}
      {recentActivity && <Text>{activeFn(" *")}</Text>}
    </Box>
  );
}
