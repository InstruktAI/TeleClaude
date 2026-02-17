/**
 * Scrollable tree container for the preparation view.
 *
 * Receives a flat list of tree items and renders only the visible viewport
 * window. Shows scroll indicators when content overflows above or below.
 * Delegates rendering of individual rows to TodoNode, FileNode, or generic
 * computer/project nodes.
 *
 * Source: teleclaude/cli/tui/views/preparation.py (render, _render_item)
 */

import React from "react";
import { Box, Text } from "ink";

import { themeText } from "@/lib/theme/ink-colors.js";
import type { FlatTreeItem } from "@/lib/tree/types.js";
import { treePrefix } from "@/lib/tree/flatten.js";

import { TodoNode } from "./nodes/TodoNode.js";
import { FileNode } from "./nodes/FileNode.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TreeContainerProps {
  /** Flattened tree items for display */
  items: readonly FlatTreeItem[];
  /** Currently selected index */
  selectedIndex: number;
  /** Set of expanded todo node IDs */
  expandedTodos: ReadonlySet<string>;
  /** Scroll offset (index of first visible item) */
  scrollOffset: number;
  /** Maximum number of visible rows */
  viewportHeight: number;
}

// ---------------------------------------------------------------------------
// Generic node renderers (computer and project)
// ---------------------------------------------------------------------------

function ComputerRow({ item, isSelected }: { item: FlatTreeItem; isSelected: boolean }) {
  const node = item.node;
  // ComputerNode carries data.computer.name and data with counts
  const data = node.data as { computer: { name: string }; sessionCount?: number };
  const name = data.computer.name;
  const prefix = treePrefix(item);

  return (
    <Box>
      <Text dimColor>{prefix}</Text>
      <Text bold={isSelected} color={isSelected ? "yellow" : undefined}>
        {name}
      </Text>
    </Box>
  );
}

function ProjectRow({ item, isSelected }: { item: FlatTreeItem; isSelected: boolean }) {
  const node = item.node;
  const label = node.label;
  const childCount = node.children.length;
  const suffix = childCount > 0 ? ` (${childCount})` : "";
  const prefix = treePrefix(item);
  const mutedFn = themeText("muted");

  return (
    <Box>
      <Text dimColor>{prefix}</Text>
      <Text
        bold={isSelected}
        color={isSelected ? "yellow" : undefined}
        dimColor={childCount === 0 && !isSelected}
      >
        {label}
      </Text>
      {childCount > 0 && <Text>{mutedFn(suffix)}</Text>}
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TreeContainer({
  items,
  selectedIndex,
  expandedTodos,
  scrollOffset,
  viewportHeight,
}: TreeContainerProps) {
  if (items.length === 0) {
    return (
      <Box paddingLeft={1}>
        <Text dimColor>(no items)</Text>
      </Box>
    );
  }

  // Calculate visible window
  const endIndex = Math.min(scrollOffset + viewportHeight, items.length);
  const visibleItems = items.slice(scrollOffset, endIndex);

  const hasAbove = scrollOffset > 0;
  const hasBelow = endIndex < items.length;

  const mutedFn = themeText("muted");

  return (
    <Box flexDirection="column">
      {hasAbove && (
        <Box paddingLeft={1}>
          <Text>{mutedFn(`  \u25B2 ${scrollOffset} more above`)}</Text>
        </Box>
      )}

      {visibleItems.map((flatItem) => {
        const isSelected = flatItem.index === selectedIndex;
        const { node } = flatItem;

        let row: React.ReactNode;

        switch (node.type) {
          case "computer":
            row = <ComputerRow item={flatItem} isSelected={isSelected} />;
            break;

          case "project":
            row = <ProjectRow item={flatItem} isSelected={isSelected} />;
            break;

          case "todo":
            row = (
              <TodoNode
                item={flatItem}
                isSelected={isSelected}
                isExpanded={expandedTodos.has(node.id)}
              />
            );
            break;

          case "file":
            row = <FileNode item={flatItem} isSelected={isSelected} />;
            break;

          default:
            row = <Text dimColor>{node.label}</Text>;
        }

        return (
          <Box key={node.id} paddingLeft={1}>
            {isSelected ? (
              <Box>
                <Text inverse bold>
                  {" "}
                </Text>
                {row}
              </Box>
            ) : (
              <Box>
                <Text> </Text>
                {row}
              </Box>
            )}
          </Box>
        );
      })}

      {hasBelow && (
        <Box paddingLeft={1}>
          <Text>{mutedFn(`  \u25BC ${items.length - endIndex} more below`)}</Text>
        </Box>
      )}
    </Box>
  );
}
