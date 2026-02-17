/**
 * Project header row in the sessions tree.
 *
 * Renders: project-name (shortened path) indented under its computer.
 * Shows child session count when available.
 *
 * Source: teleclaude/cli/tui/views/sessions.py (_render_project_line)
 */

import React from "react";
import { Box, Text } from "ink";

import { themeText } from "@/lib/theme/ink-colors.js";
import { shortenPath } from "@/lib/utils/path.js";
import type { FlatTreeItem, ProjectNode as ProjectNodeType } from "@/lib/tree/types.js";
import { treePrefix } from "@/lib/tree/flatten.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ProjectNodeProps {
  /** The flat tree item carrying the project node */
  item: FlatTreeItem;
  /** Whether this row is the currently selected item */
  isSelected: boolean;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PATH_MAX_LEN = 40;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ProjectNode({ item, isSelected }: ProjectNodeProps) {
  const node = item.node as ProjectNodeType;
  const prefix = treePrefix(item);
  const { name, path } = node.data;
  const childCount = node.children.length;

  const primaryFn = themeText("primary");
  const secondaryFn = themeText("secondary");
  const mutedFn = themeText("muted");

  const displayName = name || shortenPath(path, PATH_MAX_LEN);
  const suffix = childCount > 0 ? ` (${childCount})` : "";

  return (
    <Box>
      <Text dimColor>{prefix}</Text>
      <Text bold={isSelected}>
        {isSelected ? primaryFn(displayName) : secondaryFn(displayName)}
      </Text>
      {suffix && <Text>{mutedFn(suffix)}</Text>}
    </Box>
  );
}
