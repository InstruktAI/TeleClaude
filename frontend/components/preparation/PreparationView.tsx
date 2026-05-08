"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useComputers } from "@/lib/hooks/useComputers";
import { useProjects } from "@/lib/hooks/useProjects";
import {
  buildPreparationTree,
  type PreparationComputerNode,
  type PreparationGroupNode,
  type PreparationProjectNode,
  type PreparationTodoNode,
} from "@/lib/preparation/tree";
import { loadPreparationFixture } from "@/lib/preparation/fixture-mode";
import { TreeNode } from "./TreeNode";
import { NewTodoModal } from "./NewTodoModal";
import { NewBugModal } from "./NewBugModal";
import { findBinding } from "@/lib/keys/bindings";
import { toast } from "@/lib/hooks/useToast";
import type { ComputerInfo, ProjectWithTodosInfo, TodoInfo } from "@/lib/api/types";

interface FlatNode {
  id: string;
  label: string;
  type: "computer" | "project" | "group" | "todo" | "file";
  depth: number;
  hasChildren: boolean;
  computerStatus?: string;
  todo?: TodoInfo;
  slugColWidth?: number;
}

function todoHasChildren(todo: PreparationTodoNode): boolean {
  return todo.todos.length > 0 || todo.files.length > 0;
}

function flattenTodo(
  todo: PreparationTodoNode,
  depth: number,
  slugColWidth: number,
  expandedIds: ReadonlySet<string>,
  out: FlatNode[],
): void {
  const hasChildren = todoHasChildren(todo);
  out.push({
    id: todo.id,
    label: todo.label,
    type: "todo",
    depth,
    hasChildren,
    todo: todo.todo,
    slugColWidth,
  });
  if (!expandedIds.has(todo.id)) return;
  for (const child of todo.todos) {
    flattenTodo(child, depth + 1, slugColWidth, expandedIds, out);
  }
  for (const file of todo.files) {
    out.push({
      id: file.id,
      label: file.label,
      type: "file",
      depth: depth + 1,
      hasChildren: false,
    });
  }
}

function flattenGroup(
  group: PreparationGroupNode,
  depth: number,
  slugColWidth: number,
  expandedIds: ReadonlySet<string>,
  out: FlatNode[],
): void {
  out.push({
    id: group.id,
    label: group.label,
    type: "group",
    depth,
    hasChildren: group.todos.length > 0,
  });
  if (!expandedIds.has(group.id)) return;
  for (const todo of group.todos) {
    flattenTodo(todo, depth + 1, slugColWidth, expandedIds, out);
  }
}

function flattenProject(
  project: PreparationProjectNode,
  depth: number,
  expandedIds: ReadonlySet<string>,
  out: FlatNode[],
): void {
  const hasChildren = project.rootChildren.length > 0;
  out.push({
    id: project.id,
    label: project.label,
    type: "project",
    depth,
    hasChildren,
  });
  if (!expandedIds.has(project.id)) return;
  for (const child of project.rootChildren) {
    if (child.kind === "group") {
      flattenGroup(child.node, depth + 1, project.maxSlugLength, expandedIds, out);
    } else {
      flattenTodo(child.node, depth + 1, project.maxSlugLength, expandedIds, out);
    }
  }
}

function flattenTree(
  tree: readonly PreparationComputerNode[],
  expandedIds: ReadonlySet<string>,
): FlatNode[] {
  const nodes: FlatNode[] = [];

  for (const computer of tree) {
    nodes.push({
      id: computer.id,
      label: computer.label,
      type: "computer",
      depth: 0,
      hasChildren: computer.projects.length > 0,
      computerStatus: computer.computer.status,
    });
    if (!expandedIds.has(computer.id)) continue;

    for (const project of computer.projects) {
      flattenProject(project, 1, expandedIds, nodes);
    }
  }

  return nodes;
}

function collectExpandableTodoIds(todo: PreparationTodoNode, ids: string[]): void {
  if (todoHasChildren(todo)) ids.push(todo.id);
  for (const child of todo.todos) {
    collectExpandableTodoIds(child, ids);
  }
}

function collectAllExpandableIds(tree: readonly PreparationComputerNode[]): string[] {
  const ids: string[] = [];
  for (const c of tree) {
    if (c.projects.length > 0) ids.push(c.id);
    for (const p of c.projects) {
      if (p.rootChildren.length > 0) ids.push(p.id);
      for (const child of p.rootChildren) {
        if (child.kind === "group") {
          if (child.node.todos.length > 0) ids.push(child.node.id);
          for (const t of child.node.todos) {
            collectExpandableTodoIds(t, ids);
          }
        } else {
          collectExpandableTodoIds(child.node, ids);
        }
      }
    }
  }
  return ids;
}

function findFocusedTodo(nodes: FlatNode[], cursorIndex: number): TodoInfo | null {
  const node = nodes[cursorIndex];
  if (!node) return null;
  if (node.type === "todo" && node.todo) return node.todo;
  return null;
}

async function dispatchTodoAction(slug: string, action: string): Promise<void> {
  const res = await fetch(`/api/todos/${encodeURIComponent(slug)}/${action}`, {
    method: "POST",
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(
      (data as { error?: string }).error ?? `HTTP ${res.status}`,
    );
  }
}

const UNAVAILABLE_ACTIONS = new Set([
  "remove_todo",
  "freeze_todo",
  "move_todo_up",
  "move_todo_down",
]);

interface PreparationViewProps {
  isActive?: boolean;
}

export function PreparationView({ isActive = true }: PreparationViewProps) {
  const { data: computersData } = useComputers();
  const { data: projectsData } = useProjects();

  const fixtureName = useMemo(() => {
    if (typeof window === "undefined") return null;
    return new URLSearchParams(window.location.search).get("fixtures");
  }, []);
  const fixture = useMemo(
    () => loadPreparationFixture(fixtureName),
    [fixtureName],
  );

  const computers = fixture ? fixture.computers : computersData;
  const projects = fixture ? fixture.projects : projectsData;

  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [cursorIndex, setCursorIndex] = useState(0);
  const [todoModalOpen, setTodoModalOpen] = useState(false);
  const [bugModalOpen, setBugModalOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const tree = useMemo(() => {
    if (!projects || !computers) return [];
    return buildPreparationTree(
      projects as ProjectWithTodosInfo[],
      computers as ComputerInfo[],
    );
  }, [projects, computers]);

  // In fixture mode the smoke test needs every node visible. Compute the effective
  // expanded set as a derived value rather than syncing it via setState in an effect.
  const effectiveExpandedIds = useMemo(() => {
    if (fixture) return new Set(collectAllExpandableIds(tree));
    return expandedIds;
  }, [fixture, tree, expandedIds]);

  const visibleNodes = useMemo(
    () => flattenTree(tree, effectiveExpandedIds),
    [tree, effectiveExpandedIds],
  );

  const clampedCursor = Math.min(cursorIndex, Math.max(visibleNodes.length - 1, 0));

  const toggleNode = useCallback(
    (nodeId: string) => {
      setExpandedIds((prev) => {
        const next = new Set(prev);
        if (next.has(nodeId)) {
          next.delete(nodeId);
        } else {
          next.add(nodeId);
        }
        return next;
      });
    },
    [],
  );

  const handleAction = useCallback(
    async (action: string) => {
      if (UNAVAILABLE_ACTIONS.has(action)) {
        toast({
          title: "Operation unavailable",
          description: "No daemon endpoint for this operation",
          variant: "destructive",
        });
        return;
      }

      const todo = findFocusedTodo(visibleNodes, clampedCursor);
      if (!todo) {
        toast({
          title: "No todo selected",
          description: "Navigate to a todo node first",
          variant: "destructive",
        });
        return;
      }

      const actionMap: Record<string, string> = {
        prepare_todo: "prepare",
        start_work: "work",
        refine_input: "refine",
      };

      const endpoint = actionMap[action];
      if (!endpoint) return;

      try {
        await dispatchTodoAction(todo.slug, endpoint);
        toast({
          title: `${endpoint.charAt(0).toUpperCase() + endpoint.slice(1)} dispatched`,
          description: todo.slug,
          variant: "success",
        });
      } catch (err) {
        toast({
          title: `${endpoint} failed`,
          description: err instanceof Error ? err.message : "Unknown error",
          variant: "destructive",
        });
      }
    },
    [visibleNodes, clampedCursor],
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!isActive) return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (todoModalOpen || bugModalOpen) return;

      const binding = findBinding(
        e.key,
        { ctrl: e.ctrlKey, shift: e.shiftKey, meta: e.metaKey },
        "preparation",
      );
      if (!binding) return;

      switch (binding.action) {
        case "navigate_up":
          e.preventDefault();
          setCursorIndex((prev) => Math.max(prev - 1, 0));
          break;
        case "navigate_down":
          e.preventDefault();
          setCursorIndex((prev) =>
            Math.min(prev + 1, visibleNodes.length - 1),
          );
          break;
        case "collapse_or_back": {
          e.preventDefault();
          const node = visibleNodes[clampedCursor];
          if (node && effectiveExpandedIds.has(node.id)) {
            toggleNode(node.id);
          }
          break;
        }
        case "drill_down":
        case "open_editor": {
          e.preventDefault();
          const node = visibleNodes[clampedCursor];
          if (node?.hasChildren) {
            toggleNode(node.id);
          }
          break;
        }
        case "expand_all":
          e.preventDefault();
          setExpandedIds(new Set(collectAllExpandableIds(tree)));
          break;
        case "collapse_all":
          e.preventDefault();
          setExpandedIds(new Set());
          setCursorIndex(0);
          break;
        case "new_todo":
          e.preventDefault();
          setTodoModalOpen(true);
          break;
        case "new_bug":
          e.preventDefault();
          setBugModalOpen(true);
          break;
        case "preview_file":
        case "view_file": {
          e.preventDefault();
          const fileNode = visibleNodes[clampedCursor];
          if (fileNode?.type !== "file") {
            toast({
              title: "No file selected",
              description: "Navigate to a file node first",
              variant: "destructive",
            });
          } else {
            toast({
              title: "File preview unavailable",
              description: "File preview requires a daemon endpoint",
              variant: "destructive",
            });
          }
          break;
        }
        case "prepare_todo":
        case "start_work":
        case "refine_input":
        case "remove_todo":
        case "freeze_todo":
        case "move_todo_up":
        case "move_todo_down":
          e.preventDefault();
          handleAction(binding.action);
          break;
        default:
          break;
      }
    },
    [isActive, visibleNodes, clampedCursor, effectiveExpandedIds, tree, toggleNode, handleAction, todoModalOpen, bugModalOpen],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const cursorEl = container.querySelector(`[data-cursor="true"]`);
    if (cursorEl) {
      cursorEl.scrollIntoView({ block: "nearest" });
    }
  }, [clampedCursor]);

  if (!computers || !projects) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-sm text-muted-foreground">Loading preparation data...</p>
      </div>
    );
  }

  if (visibleNodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-sm text-muted-foreground">No preparation data available</p>
      </div>
    );
  }

  return (
    <>
      <div ref={containerRef} className="py-1">
        {visibleNodes.map((node, index) => (
          <div key={node.id} data-cursor={index === clampedCursor ? "true" : undefined}>
            <TreeNode
              label={node.label}
              type={node.type}
              depth={node.depth}
              expanded={effectiveExpandedIds.has(node.id)}
              hasChildren={node.hasChildren}
              isCursor={index === clampedCursor}
              todo={node.todo}
              computerStatus={node.computerStatus}
              slugColWidth={node.slugColWidth}
              onToggle={() => {
                setCursorIndex(index);
                if (node.hasChildren) toggleNode(node.id);
              }}
            />
          </div>
        ))}
      </div>
      <NewTodoModal open={todoModalOpen} onOpenChange={setTodoModalOpen} />
      <NewBugModal open={bugModalOpen} onOpenChange={setBugModalOpen} />
    </>
  );
}
