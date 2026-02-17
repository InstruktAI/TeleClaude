/**
 * Tree node types for hierarchical TUI views.
 *
 * Two tree hierarchies:
 *   Sessions: Computer -> Project -> Session (with AI-to-AI nesting)
 *   Preparation: Project -> Todo -> File
 *
 * Source: teleclaude/cli/tui/tree.py, teleclaude/cli/tui/views/preparation.py
 */

import type {
  ComputerInfo,
  ProjectInfo,
  SessionInfo,
  TodoInfo,
} from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Node type discriminator
// ---------------------------------------------------------------------------

export type NodeType = "computer" | "project" | "session" | "todo" | "file";

// ---------------------------------------------------------------------------
// Display-enriched data (carried inside nodes, not exposed raw)
// ---------------------------------------------------------------------------

export interface ComputerDisplayInfo {
  computer: ComputerInfo;
  sessionCount: number;
  recentActivity: boolean;
}

export interface SessionDisplayInfo {
  session: SessionInfo;
  displayIndex: string;
}

export interface TodoDisplayInfo {
  todo: TodoInfo;
  projectPath: string;
  computer: string;
}

export interface FileDisplayInfo {
  filename: string;
  displayName: string;
  exists: boolean;
  index: number;
  slug: string;
  projectPath: string;
  computer: string;
}

// ---------------------------------------------------------------------------
// Tree node types (discriminated union on `type`)
// ---------------------------------------------------------------------------

export interface ComputerNode {
  type: "computer";
  id: string;
  label: string;
  data: ComputerDisplayInfo;
  children: TreeNode[];
}

export interface ProjectNode {
  type: "project";
  id: string;
  label: string;
  data: ProjectInfo;
  children: TreeNode[];
}

export interface SessionNode {
  type: "session";
  id: string;
  label: string;
  data: SessionDisplayInfo;
  children: TreeNode[];
}

export interface TodoNode {
  type: "todo";
  id: string;
  label: string;
  data: TodoDisplayInfo;
  children: TreeNode[];
}

export interface FileNode {
  type: "file";
  id: string;
  label: string;
  data: FileDisplayInfo;
  children: TreeNode[];
}

export type TreeNode =
  | ComputerNode
  | ProjectNode
  | SessionNode
  | TodoNode
  | FileNode;

// ---------------------------------------------------------------------------
// Type guards
// ---------------------------------------------------------------------------

export function isComputerNode(node: TreeNode): node is ComputerNode {
  return node.type === "computer";
}

export function isProjectNode(node: TreeNode): node is ProjectNode {
  return node.type === "project";
}

export function isSessionNode(node: TreeNode): node is SessionNode {
  return node.type === "session";
}

export function isTodoNode(node: TreeNode): node is TodoNode {
  return node.type === "todo";
}

export function isFileNode(node: TreeNode): node is FileNode {
  return node.type === "file";
}

// ---------------------------------------------------------------------------
// Flattened tree item (output of flattenTree)
// ---------------------------------------------------------------------------

export interface FlatTreeItem {
  node: TreeNode;
  depth: number;
  index: number;
  isLast: boolean;
  parentId: string | null;
}
