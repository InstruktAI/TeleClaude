/**
 * Main preparation view component for the TeleClaude TUI.
 *
 * Builds the todo tree from store data, flattens it with expansion state,
 * and handles keyboard navigation (up/down, expand/collapse, enter to open).
 *
 * Source: teleclaude/cli/tui/views/preparation.py (PreparationView)
 */

import React, { useMemo, useCallback } from "react";
import { Box, Text, useInput } from "ink";

import { useTuiStore } from "@/lib/store/index.js";
import { buildPrepTree } from "@/lib/tree/builder.js";
import { flattenTree } from "@/lib/tree/flatten.js";
import { themeText } from "@/lib/theme/ink-colors.js";
import type { ProjectWithTodosInfo } from "@/lib/api/types.js";
import type { FlatTreeItem } from "@/lib/tree/types.js";

import { TreeContainer } from "./TreeContainer.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PreparationViewProps {
  /** Projects with embedded todos, fetched from the API layer */
  projects: ProjectWithTodosInfo[];
  /** Viewport height (rows available for the tree) */
  viewportHeight?: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_VIEWPORT_HEIGHT = 20;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PreparationView({
  projects,
  viewportHeight = DEFAULT_VIEWPORT_HEIGHT,
}: PreparationViewProps) {
  const dispatch = useTuiStore((s) => s.dispatch);
  const selectedIndex = useTuiStore((s) => s.preparation.selectedIndex);
  const scrollOffset = useTuiStore((s) => s.preparation.scrollOffset);
  const expandedTodos = useTuiStore((s) => s.preparation.expandedTodos);

  // Build the tree from projects data
  const tree = useMemo(() => buildPrepTree(projects), [projects]);

  // Compute which todo IDs should be collapsed (inverse of expandedTodos).
  // flattenTree skips children of nodes whose IDs are in the collapsed set.
  // For the preparation tree, projects are always expanded and todos are
  // collapsed by default. We compute the set of todo IDs that are NOT in
  // expandedTodos.
  const collapsedIds = useMemo(() => {
    const allTodoIds = new Set<string>();
    for (const projNode of tree) {
      for (const child of projNode.children) {
        if (child.type === "todo") {
          allTodoIds.add(child.id);
        }
      }
    }
    const collapsed = new Set<string>();
    for (const id of allTodoIds) {
      if (!expandedTodos.has(id)) {
        collapsed.add(id);
      }
    }
    return collapsed;
  }, [tree, expandedTodos]);

  // Flatten tree respecting expansion state
  const flatItems: FlatTreeItem[] = useMemo(
    () => flattenTree(tree, collapsedIds),
    [tree, collapsedIds],
  );

  // -- Navigation helpers ---------------------------------------------------

  const clampIndex = useCallback(
    (idx: number): number => Math.max(0, Math.min(idx, flatItems.length - 1)),
    [flatItems.length],
  );

  const updateSelection = useCallback(
    (newIndex: number) => {
      const clamped = clampIndex(newIndex);
      dispatch({
        type: "SET_SELECTION",
        view: "preparation",
        index: clamped,
        source: "user",
      });

      // Adjust scroll to keep selection visible
      if (clamped < scrollOffset) {
        dispatch({
          type: "SET_SCROLL_OFFSET",
          view: "preparation",
          offset: clamped,
        });
      } else if (clamped >= scrollOffset + viewportHeight) {
        dispatch({
          type: "SET_SCROLL_OFFSET",
          view: "preparation",
          offset: clamped - viewportHeight + 1,
        });
      }
    },
    [clampIndex, dispatch, scrollOffset, viewportHeight],
  );

  const toggleTodo = useCallback(
    (todoNodeId: string) => {
      if (expandedTodos.has(todoNodeId)) {
        dispatch({ type: "COLLAPSE_TODO", todoId: todoNodeId });
      } else {
        dispatch({ type: "EXPAND_TODO", todoId: todoNodeId });
      }
    },
    [dispatch, expandedTodos],
  );

  const expandAll = useCallback(() => {
    const todoIds: string[] = [];
    for (const item of flatItems) {
      if (item.node.type === "todo") {
        todoIds.push(item.node.id);
      }
    }
    dispatch({ type: "EXPAND_ALL_TODOS", todoIds });
  }, [dispatch, flatItems]);

  const collapseAll = useCallback(() => {
    dispatch({ type: "COLLAPSE_ALL_TODOS" });
  }, [dispatch]);

  // -- Keyboard input -------------------------------------------------------

  useInput((input, key) => {
    if (flatItems.length === 0) return;

    // Navigation
    if (key.upArrow) {
      updateSelection(selectedIndex - 1);
      return;
    }
    if (key.downArrow) {
      updateSelection(selectedIndex + 1);
      return;
    }

    // Page up/down
    if (key.pageUp) {
      updateSelection(selectedIndex - viewportHeight);
      return;
    }
    if (key.pageDown) {
      updateSelection(selectedIndex + viewportHeight);
      return;
    }

    // Home/End
    if (key.home) {
      updateSelection(0);
      return;
    }
    if (key.end) {
      updateSelection(flatItems.length - 1);
      return;
    }

    // Expand/collapse selected
    if (input === " " || key.rightArrow) {
      const selected = flatItems[selectedIndex];
      if (selected && selected.node.type === "todo") {
        toggleTodo(selected.node.id);
      }
      return;
    }

    // Left arrow: collapse todo or navigate to parent
    if (key.leftArrow) {
      const selected = flatItems[selectedIndex];
      if (!selected) return;

      if (selected.node.type === "todo" && expandedTodos.has(selected.node.id)) {
        toggleTodo(selected.node.id);
      } else if (selected.node.type === "file" && selected.parentId) {
        // Navigate to parent todo
        const parentIdx = flatItems.findIndex((fi) => fi.node.id === selected.parentId);
        if (parentIdx >= 0) {
          updateSelection(parentIdx);
        }
      }
      return;
    }

    // Enter: drill down or activate
    if (key.return) {
      const selected = flatItems[selectedIndex];
      if (!selected) return;

      if (selected.node.type === "todo") {
        toggleTodo(selected.node.id);
      }
      // File activation deferred to action system (WI-18+)
      return;
    }

    // Global expand/collapse
    if (input === "+" || input === "=") {
      expandAll();
      return;
    }
    if (input === "-") {
      collapseAll();
      return;
    }
  });

  // -- Render ---------------------------------------------------------------

  if (projects.length === 0) {
    const mutedFn = themeText("muted");
    return (
      <Box flexDirection="column" paddingLeft={1} paddingTop={1}>
        <Text>{mutedFn("No projects with todos found.")}</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      <TreeContainer
        items={flatItems}
        selectedIndex={selectedIndex}
        expandedTodos={expandedTodos}
        scrollOffset={scrollOffset}
        viewportHeight={viewportHeight}
      />
    </Box>
  );
}
