/**
 * Scrollable tree container for the sessions view.
 *
 * Receives a flat list of tree items and renders only the visible viewport
 * window (viewport windowing). Shows scroll indicators when content
 * overflows above or below.
 *
 * Delegates rendering to the appropriate node component based on item type:
 * ComputerNode, ProjectNode, or SessionNode.
 *
 * Source: teleclaude/cli/tui/views/sessions.py (render, viewport slicing)
 */

import React from "react";
import { Box, Text } from "ink";

import { themeText } from "@/lib/theme/ink-colors.js";
import type { FlatTreeItem } from "@/lib/tree/types.js";
import type { SessionViewState } from "@/lib/store/types.js";

import { ComputerNode } from "./nodes/ComputerNode.js";
import { ProjectNode } from "./nodes/ProjectNode.js";
import { SessionNode } from "./nodes/SessionNode.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TreeContainerProps {
  /** Flattened tree items for display */
  items: readonly FlatTreeItem[];
  /** Currently selected index */
  selectedIndex: number;
  /** Scroll offset (index of first visible item) */
  scrollOffset: number;
  /** Maximum number of visible rows */
  viewportHeight: number;
  /** Session view state for highlights, collapse, sticky */
  sessionsState: SessionViewState;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TreeContainer({
  items,
  selectedIndex,
  scrollOffset,
  viewportHeight,
  sessionsState,
}: TreeContainerProps) {
  if (items.length === 0) {
    const mutedFn = themeText("muted");
    return (
      <Box paddingLeft={1}>
        <Text>{mutedFn("No sessions found.")}</Text>
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
          <Text>{mutedFn(`  \u2191 ${scrollOffset} more`)}</Text>
        </Box>
      )}

      {visibleItems.map((flatItem) => {
        const isSelected = flatItem.index === selectedIndex;
        const { node } = flatItem;

        let row: React.ReactNode;

        switch (node.type) {
          case "computer":
            row = <ComputerNode item={flatItem} isSelected={isSelected} />;
            break;

          case "project":
            row = <ProjectNode item={flatItem} isSelected={isSelected} />;
            break;

          case "session":
            row = (
              <SessionNode
                item={flatItem}
                isSelected={isSelected}
                sessionsState={sessionsState}
              />
            );
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
          <Text>{mutedFn(`  \u2193 ${items.length - endIndex} more`)}</Text>
        </Box>
      )}
    </Box>
  );
}
