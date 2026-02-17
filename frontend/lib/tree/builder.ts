/**
 * Build hierarchical trees from flat API data.
 *
 * Two builders:
 *   buildSessionTree  - Computer -> Project -> Session (with AI-to-AI nesting)
 *   buildPrepTree     - Project -> Todo -> File
 *
 * All functions are pure and produce no side effects.
 *
 * Source: teleclaude/cli/tui/tree.py (build_tree, _build_session_node)
 *         teleclaude/cli/tui/views/preparation.py (_build_tree)
 */

import type {
  ComputerInfo,
  ProjectInfo,
  ProjectWithTodosInfo,
  SessionInfo,
  TodoInfo,
} from "@/lib/api/types";

import type {
  ComputerDisplayInfo,
  ComputerNode,
  FileNode,
  ProjectNode,
  SessionNode,
  TodoNode,
  TreeNode,
} from "./types";

// ---------------------------------------------------------------------------
// ID helpers (namespaced to avoid collisions across node types)
// ---------------------------------------------------------------------------

export function computerId(hostname: string): string {
  return `computer:${hostname}`;
}

export function projectId(hostname: string, path: string): string {
  return `project:${hostname}:${path}`;
}

export function sessionId(id: string): string {
  return `session:${id}`;
}

export function todoId(
  computer: string,
  projectPath: string,
  slug: string,
): string {
  // Matches the Python JSON-serialized key: [computer, project_path, slug]
  return `todo:${computer}:${projectPath}:${slug}`;
}

export function fileId(
  computer: string,
  projectPath: string,
  slug: string,
  filename: string,
): string {
  return `file:${computer}:${projectPath}:${slug}:${filename}`;
}

// ---------------------------------------------------------------------------
// Session tree builder
// ---------------------------------------------------------------------------

/**
 * Build the session hierarchy: Computer -> Project -> Session.
 *
 * Sticky session IDs appear at the top of their project group.
 * Orphan sessions (computer/project missing from lists) get synthetic parents.
 */
export function buildSessionTree(
  computers: ComputerInfo[],
  projects: ProjectInfo[],
  sessions: SessionInfo[],
  stickyIds: ReadonlySet<string> = new Set(),
): ComputerNode[] {
  // Build stable computer list. Sessions may reference computers not
  // currently in the heartbeat list (stale windows). Create synthetic
  // entries for those so every session has a parent.
  const allComputers: ComputerDisplayInfo[] = [];
  const knownComputers = new Set<string>();

  for (const comp of computers) {
    knownComputers.add(comp.name);
    allComputers.push({
      computer: comp,
      sessionCount: 0,
      recentActivity: false,
    });
  }

  for (const session of sessions) {
    const compName = (session.computer ?? "").trim();
    if (!compName || knownComputers.has(compName)) continue;
    knownComputers.add(compName);
    allComputers.push({
      computer: {
        name: compName,
        status: "offline",
        user: null,
        host: null,
        is_local: compName === "local",
        tmux_binary: null,
      },
      sessionCount: 0,
      recentActivity: false,
    });
  }

  // Alphabetical computer sort
  allComputers.sort((a, b) =>
    a.computer.name.localeCompare(b.computer.name),
  );

  // Aggregate counts and recent-activity flags
  const now = Date.now();
  const sessionCounts: Record<string, number> = {};
  const recentActivity: Record<string, boolean> = {};

  for (const session of sessions) {
    const compName = (session.computer ?? "").trim();
    if (!compName) continue;
    sessionCounts[compName] = (sessionCounts[compName] ?? 0) + 1;

    if (session.last_activity) {
      try {
        const lastDt = new Date(session.last_activity).getTime();
        if (now - lastDt <= 300_000) {
          recentActivity[compName] = true;
        }
      } catch {
        // Ignore parse errors
      }
    }
  }

  for (const entry of allComputers) {
    const name = entry.computer.name;
    entry.sessionCount = sessionCounts[name] ?? 0;
    entry.recentActivity = recentActivity[name] ?? false;
  }

  // Index sessions by initiator for AI-to-AI nesting
  const sessionMap = new Set(sessions.map((s) => s.session_id));
  const sessionsByInitiator: Record<string, SessionInfo[]> = {};
  const rootSessions: SessionInfo[] = [];

  for (const session of sessions) {
    const initiator = session.initiator_session_id;
    if (initiator && sessionMap.has(initiator)) {
      (sessionsByInitiator[initiator] ??= []).push(session);
    } else {
      rootSessions.push(session);
    }
  }

  // Build the tree
  const tree: ComputerNode[] = [];

  for (const compDisplay of allComputers) {
    const compName = compDisplay.computer.name;

    const compNode: ComputerNode = {
      type: "computer",
      id: computerId(compName),
      label: compName,
      data: compDisplay,
      children: [],
    };

    const compProjects = projects
      .filter((p) => p.computer === compName)
      .slice()
      .sort((a, b) => a.path.localeCompare(b.path));

    const matchedSessionIds = new Set<string>();

    for (const project of compProjects) {
      const projNode: ProjectNode = {
        type: "project",
        id: projectId(compName, project.path),
        label: project.name || project.path,
        data: project,
        children: [],
      };

      // Collect root sessions for this project
      const projSessions = rootSessions.filter(
        (s) =>
          (s.computer ?? "") === compName && s.project_path === project.path,
      );

      // Sort: sticky first, then by created_at desc
      const sorted = sortSessionsWithSticky(projSessions, stickyIds);

      for (let idx = 0; idx < sorted.length; idx++) {
        const session = sorted[idx];
        const sessNode = buildSessionNode(
          session,
          String(idx + 1),
          sessionsByInitiator,
          stickyIds,
        );
        projNode.children.push(sessNode);
        matchedSessionIds.add(session.session_id);
      }

      compNode.children.push(projNode);
    }

    // Orphan sessions: not matched to any known project
    const orphanSessions = rootSessions.filter(
      (s) =>
        (s.computer ?? "") === compName &&
        !matchedSessionIds.has(s.session_id),
    );

    // Group orphans by project_path to create synthetic project nodes
    const orphansByPath: Record<string, SessionInfo[]> = {};
    for (const session of orphanSessions) {
      const path = session.project_path ?? "";
      (orphansByPath[path] ??= []).push(session);
    }

    const orphanPaths = Object.keys(orphansByPath).sort();
    for (const path of orphanPaths) {
      const projNode: ProjectNode = {
        type: "project",
        id: projectId(compName, path),
        label: path || "(unknown project)",
        data: {
          computer: compName,
          name: "",
          path,
          description: null,
        },
        children: [],
      };

      const sorted = sortSessionsWithSticky(orphansByPath[path], stickyIds);
      for (let idx = 0; idx < sorted.length; idx++) {
        const session = sorted[idx];
        const sessNode = buildSessionNode(
          session,
          String(idx + 1),
          sessionsByInitiator,
          stickyIds,
        );
        projNode.children.push(sessNode);
      }

      compNode.children.push(projNode);
    }

    tree.push(compNode);
  }

  return tree;
}

// ---------------------------------------------------------------------------
// Session node builder (recursive for AI-to-AI nesting)
// ---------------------------------------------------------------------------

function buildSessionNode(
  session: SessionInfo,
  displayIndex: string,
  sessionsByInitiator: Record<string, SessionInfo[]>,
  stickyIds: ReadonlySet<string>,
): SessionNode {
  const node: SessionNode = {
    type: "session",
    id: sessionId(session.session_id),
    label: session.title || session.session_id,
    data: {
      session,
      displayIndex,
    },
    children: [],
  };

  // AI-to-AI child sessions
  const children = sessionsByInitiator[session.session_id];
  if (children) {
    const sorted = sortSessionsWithSticky(children, stickyIds);
    for (let idx = 0; idx < sorted.length; idx++) {
      const child = sorted[idx];
      const childNode = buildSessionNode(
        child,
        `${displayIndex}.${idx + 1}`,
        sessionsByInitiator,
        stickyIds,
      );
      node.children.push(childNode);
    }
  }

  return node;
}

// ---------------------------------------------------------------------------
// Session sort helper
// ---------------------------------------------------------------------------

/**
 * Sort sessions: sticky first (preserving sticky order), then by created_at desc.
 */
function sortSessionsWithSticky(
  sessions: SessionInfo[],
  stickyIds: ReadonlySet<string>,
): SessionInfo[] {
  return sessions.slice().sort((a, b) => {
    const aSticky = stickyIds.has(a.session_id);
    const bSticky = stickyIds.has(b.session_id);

    // Sticky sessions come first
    if (aSticky && !bSticky) return -1;
    if (!aSticky && bSticky) return 1;

    // Among non-sticky, sort by created_at descending (newest first)
    const aTime = a.created_at ?? "";
    const bTime = b.created_at ?? "";
    if (aTime > bTime) return -1;
    if (aTime < bTime) return 1;
    return 0;
  });
}

// ---------------------------------------------------------------------------
// Preparation tree builder
// ---------------------------------------------------------------------------

/**
 * Build the preparation hierarchy: Project -> Todo -> File.
 *
 * Each ProjectWithTodosInfo contains its todos; each todo lists its files.
 * File nodes include special entries for requirements.md and
 * implementation-plan.md when the todo indicates they exist.
 */
export function buildPrepTree(
  projects: ProjectWithTodosInfo[],
): ProjectNode[] {
  const tree: ProjectNode[] = [];

  const sorted = projects.slice().sort((a, b) => a.path.localeCompare(b.path));

  for (const project of sorted) {
    const compName = project.computer ?? "";

    const projNode: ProjectNode = {
      type: "project",
      id: projectId(compName, project.path),
      label: project.name || project.path,
      data: project,
      children: [],
    };

    for (const todo of project.todos) {
      const todoNodeItem = buildTodoNode(todo, compName, project.path);
      projNode.children.push(todoNodeItem);
    }

    tree.push(projNode);
  }

  return tree;
}

// ---------------------------------------------------------------------------
// Todo node builder
// ---------------------------------------------------------------------------

function buildTodoNode(
  todo: TodoInfo,
  computer: string,
  projectPath: string,
): TodoNode {
  const node: TodoNode = {
    type: "todo",
    id: todoId(computer, projectPath, todo.slug),
    label: todo.slug,
    data: {
      todo,
      projectPath,
      computer,
    },
    children: [],
  };

  // Build file children from the todo's file list.
  // Special files (requirements.md, implementation-plan.md) are surfaced
  // based on the has_requirements / has_impl_plan flags.
  const filenames = [...todo.files];

  // Ensure special files appear first if present
  if (todo.has_impl_plan && !filenames.includes("implementation-plan.md")) {
    filenames.unshift("implementation-plan.md");
  }
  if (todo.has_requirements && !filenames.includes("requirements.md")) {
    filenames.unshift("requirements.md");
  }

  for (let idx = 0; idx < filenames.length; idx++) {
    const filename = filenames[idx];
    const fileNode: FileNode = {
      type: "file",
      id: fileId(computer, projectPath, todo.slug, filename),
      label: filename,
      data: {
        filename,
        displayName: filename,
        exists: true,
        index: idx,
        slug: todo.slug,
        projectPath,
        computer,
      },
      children: [],
    };
    node.children.push(fileNode);
  }

  return node;
}
