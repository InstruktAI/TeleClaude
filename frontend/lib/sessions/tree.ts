import type { SessionInfo, ComputerInfo } from '@/lib/api/types';

// ---------------------------------------------------------------------------
// Tree node types (discriminated union on `type` field)
// ---------------------------------------------------------------------------

export interface SessionTreeNode {
  type: 'session';
  session: SessionInfo;
  index: number;
  displayIndex: string;
  children: SessionTreeNode[];
}

export interface ProjectGroup {
  type: 'project';
  name: string;
  path: string;
  sessionCount: number;
  sessions: SessionTreeNode[];
}

export interface ComputerGroup {
  type: 'computer';
  name: string;
  status: string;
  isLocal: boolean;
  sessionCount: number;
  projects: ProjectGroup[];
}

export type NodeId = string;

export function computerNodeId(name: string): NodeId {
  return `computer:${name}`;
}

export function projectNodeId(computer: string, path: string): NodeId {
  return `project:${computer}:${path}`;
}

export function sessionNodeId(sessionId: string): NodeId {
  return `session:${sessionId}`;
}

// ---------------------------------------------------------------------------
// Orphan project sentinel
// ---------------------------------------------------------------------------

const ORPHAN_PROJECT_NAME = '\u2014';
const ORPHAN_PROJECT_PATH = '__orphan__';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function lastSegment(path: string): string {
  return path.split('/').filter(Boolean).pop() ?? path;
}

function sortByCreatedDesc(a: SessionInfo, b: SessionInfo): number {
  const ta = a.created_at ?? '';
  const tb = b.created_at ?? '';
  if (!ta && !tb) return 0;
  if (!ta) return 1;
  if (!tb) return -1;
  return tb.localeCompare(ta);
}

function nestChildren(sessions: SessionInfo[]): SessionTreeNode[] {
  const byId = new Map<string, SessionInfo>();
  for (const s of sessions) byId.set(s.session_id, s);

  const childMap = new Map<string, SessionInfo[]>();
  const topLevel: SessionInfo[] = [];

  for (const s of sessions) {
    const parentId = s.initiator_session_id;
    if (parentId && byId.has(parentId)) {
      const existing = childMap.get(parentId) ?? [];
      existing.push(s);
      childMap.set(parentId, existing);
    } else {
      topLevel.push(s);
    }
  }

  topLevel.sort(sortByCreatedDesc);

  function buildNode(session: SessionInfo, index: number, parentDisplayIndex?: string): SessionTreeNode {
    const kids = (childMap.get(session.session_id) ?? []).sort(sortByCreatedDesc);
    const displayIndex = parentDisplayIndex ? `${parentDisplayIndex}.${index}` : String(index);
    return {
      type: 'session',
      session,
      index,
      displayIndex,
      children: kids.map((c, i) => buildNode(c, i + 1, displayIndex)),
    };
  }

  return topLevel.map((s, i) => buildNode(s, i + 1));
}

function countAllSessions(nodes: SessionTreeNode[]): number {
  let count = 0;
  for (const node of nodes) {
    count += 1 + countAllSessions(node.children);
  }
  return count;
}

// ---------------------------------------------------------------------------
// Main builder
// ---------------------------------------------------------------------------

export function buildSessionTree(sessions: SessionInfo[], computers: ComputerInfo[]): ComputerGroup[] {
  const computerInfoMap = new Map<string, ComputerInfo>();
  for (const c of computers) computerInfoMap.set(c.name, c);

  // Collect all computer names (from sessions + from ComputerInfo)
  const computerNames = new Set<string>();
  for (const c of computers) computerNames.add(c.name);
  for (const s of sessions) {
    if (s.computer) computerNames.add(s.computer);
  }

  if (computerNames.size === 0) return [];

  // Group sessions by computer
  const sessionsByComputer = new Map<string, SessionInfo[]>();
  for (const name of computerNames) sessionsByComputer.set(name, []);
  for (const s of sessions) {
    const key = s.computer ?? 'unknown';
    const list = sessionsByComputer.get(key) ?? [];
    list.push(s);
    sessionsByComputer.set(key, list);
  }

  // Build computer groups
  const result: ComputerGroup[] = [];

  for (const computerName of computerNames) {
    const info = computerInfoMap.get(computerName);
    const computerSessions = sessionsByComputer.get(computerName) ?? [];

    // Group by project
    const sessionsByProject = new Map<string, SessionInfo[]>();
    for (const s of computerSessions) {
      const projectKey = s.project_path ?? ORPHAN_PROJECT_PATH;
      const list = sessionsByProject.get(projectKey) ?? [];
      list.push(s);
      sessionsByProject.set(projectKey, list);
    }

    // Build project groups
    const projects: ProjectGroup[] = [];
    let orphanProject: ProjectGroup | undefined;

    for (const [projectPath, projectSessions] of sessionsByProject) {
      const treeNodes = nestChildren(projectSessions);
      const sessionCount = countAllSessions(treeNodes);

      const project: ProjectGroup = {
        type: 'project',
        name: projectPath === ORPHAN_PROJECT_PATH ? ORPHAN_PROJECT_NAME : lastSegment(projectPath),
        path: projectPath,
        sessionCount,
        sessions: treeNodes,
      };

      if (projectPath === ORPHAN_PROJECT_PATH) {
        orphanProject = project;
      } else {
        projects.push(project);
      }
    }

    // Sort named projects alphabetically, orphan last
    projects.sort((a, b) => a.name.localeCompare(b.name));
    if (orphanProject) projects.push(orphanProject);

    result.push({
      type: 'computer',
      name: computerName,
      status: info?.status ?? 'unknown',
      isLocal: info?.is_local ?? false,
      sessionCount: computerSessions.length,
      projects,
    });
  }

  // Sort computers alphabetically
  result.sort((a, b) => a.name.localeCompare(b.name));

  return result;
}
