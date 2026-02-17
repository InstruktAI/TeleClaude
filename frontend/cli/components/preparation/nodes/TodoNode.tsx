/**
 * Tree row for a single todo item.
 *
 * Renders the tree prefix, expand/collapse indicator, todo header (name +
 * status badges). Selection highlighting is applied when this row is the
 * currently focused item.
 *
 * Source: teleclaude/cli/tui/views/preparation.py (_render_todo)
 */

import React from "react";
import { Box, Text } from "ink";

import type { FlatTreeItem, TodoNode as TodoNodeType } from "@/lib/tree/types.js";
import { treePrefix } from "@/lib/tree/flatten.js";

import { TodoHeader } from "./TodoHeader.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TodoNodeProps {
  /** The flat tree item carrying the todo node */
  item: FlatTreeItem;
  /** Whether this row is the currently selected item */
  isSelected: boolean;
  /** Whether this todo's children are expanded */
  isExpanded: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TodoNode({ item, isSelected, isExpanded }: TodoNodeProps) {
  const node = item.node as TodoNodeType;
  const prefix = treePrefix(item);

  return (
    <Box>
      <Text dimColor>{prefix}</Text>
      <TodoHeader
        slug={node.label}
        todo={node.data.todo}
        isExpanded={isExpanded}
        isSelected={isSelected}
      />
    </Box>
  );
}
