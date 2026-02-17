/**
 * Flatten a hierarchical tree into a scrollable list.
 *
 * DFS traversal produces FlatTreeItem[] where each item carries its depth
 * (for indentation), global index (for selection), and tree-drawing hints.
 *
 * Collapsed nodes appear in the output but their children are skipped.
 *
 * Source: teleclaude/cli/tui/views/sessions.py (_flatten_tree)
 *         teleclaude/cli/tui/views/preparation.py (_flatten_tree)
 */

import type { FlatTreeItem, TreeNode } from "./types";

/**
 * Flatten a tree of nodes into a scrollable list.
 *
 * @param roots       - Root nodes of the tree (ComputerNode[] or ProjectNode[])
 * @param collapsedIds - Set of node IDs whose children should be hidden.
 *                       The collapsed node itself still appears in the list.
 * @returns Flat list with depth, index, and tree-drawing metadata.
 */
export function flattenTree(
  roots: readonly TreeNode[],
  collapsedIds: ReadonlySet<string> = new Set(),
): FlatTreeItem[] {
  const result: FlatTreeItem[] = [];
  let globalIndex = 0;

  function walk(
    nodes: readonly TreeNode[],
    depth: number,
    parentId: string | null,
  ): void {
    for (let i = 0; i < nodes.length; i++) {
      const node = nodes[i];
      const isLast = i === nodes.length - 1;

      result.push({
        node,
        depth,
        index: globalIndex,
        isLast,
        parentId,
      });
      globalIndex++;

      // If this node is collapsed, skip its children
      if (collapsedIds.has(node.id)) {
        continue;
      }

      // Recurse into children
      if (node.children.length > 0) {
        walk(node.children, depth + 1, node.id);
      }
    }
  }

  walk(roots, 0, null);
  return result;
}

/**
 * Find a flat item by its node ID.
 *
 * Useful for restoring selection after a tree rebuild.
 */
export function findFlatItemById(
  items: readonly FlatTreeItem[],
  nodeId: string,
): FlatTreeItem | undefined {
  return items.find((item) => item.node.id === nodeId);
}

/**
 * Find a flat item by session ID (convenience for session-centric lookups).
 *
 * Searches for a node with id === `session:<sessionId>`.
 */
export function findFlatItemBySessionId(
  items: readonly FlatTreeItem[],
  sid: string,
): FlatTreeItem | undefined {
  const target = `session:${sid}`;
  return items.find((item) => item.node.id === target);
}

/**
 * Collect all session IDs from a flat list.
 *
 * Returns the raw session IDs (without the `session:` prefix).
 */
export function collectSessionIds(
  items: readonly FlatTreeItem[],
): string[] {
  const ids: string[] = [];
  for (const item of items) {
    if (item.node.type === "session") {
      ids.push(item.node.data.session.session_id);
    }
  }
  return ids;
}

/**
 * Build tree-drawing prefix characters for a flat item.
 *
 * Returns a string like "  ├─ " or "  └─ " based on depth and position.
 * Depth 0 nodes get no prefix (they are root-level).
 */
export function treePrefix(
  item: FlatTreeItem,
  indent: string = "  ",
): string {
  if (item.depth === 0) return "";
  const connector = item.isLast ? "\u2514\u2500 " : "\u251C\u2500 ";
  return indent.repeat(item.depth - 1) + connector;
}
