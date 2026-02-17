/**
 * Leaf node rendering a file path under a todo item.
 *
 * Shows a numbered file entry with the filename as display text.
 * Dimmed when the file does not exist; uses tree prefix for connector lines.
 *
 * Source: teleclaude/cli/tui/views/preparation.py (_render_file)
 */

import React from "react";
import { Box, Text } from "ink";

import { themeText } from "@/lib/theme/ink-colors.js";
import type { FlatTreeItem, FileNode as FileNodeType } from "@/lib/tree/types.js";
import { treePrefix } from "@/lib/tree/flatten.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FileNodeProps {
  /** The flat tree item carrying the file node */
  item: FlatTreeItem;
  /** Whether this row is selected */
  isSelected: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function FileNode({ item, isSelected }: FileNodeProps) {
  const node = item.node as FileNodeType;
  const { displayName, exists, index } = node.data;
  const prefix = treePrefix(item);

  const mutedFn = themeText("muted");
  const secondaryFn = themeText("secondary");

  // File index is 0-based in data, display as 1-based
  const displayIndex = `${index + 1}.`;

  return (
    <Box>
      <Text dimColor>{prefix}</Text>
      {isSelected ? (
        <Text bold inverse>
          {displayIndex}
        </Text>
      ) : (
        <Text dimColor={!exists}>{mutedFn(displayIndex)}</Text>
      )}
      <Text dimColor={!exists} bold={isSelected} color={isSelected ? "yellow" : undefined}>
        {" "}
        {exists ? secondaryFn(displayName) : mutedFn(displayName)}
      </Text>
    </Box>
  );
}
