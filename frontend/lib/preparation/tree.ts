import type {
  ComputerInfo,
  ProjectWithTodosInfo,
  TodoInfo,
} from "@/lib/api/types";

export interface PreparationFileNode {
  id: string;
  label: string;
  name: string;
}

export interface PreparationTodoNode {
  id: string;
  label: string;
  todo: TodoInfo;
  phaseTags: string[];
  files: PreparationFileNode[];
  todos: PreparationTodoNode[];
}

export interface PreparationGroupNode {
  id: string;
  label: string;
  todos: PreparationTodoNode[];
}

export type PreparationRootChild =
  | { kind: "group"; node: PreparationGroupNode }
  | { kind: "todo"; node: PreparationTodoNode };

export interface PreparationProjectNode {
  id: string;
  label: string;
  project: ProjectWithTodosInfo;
  rootChildren: PreparationRootChild[];
  groups: PreparationGroupNode[];
  todos: PreparationTodoNode[];
  hasCyclicDeps: boolean;
  maxSlugLength: number;
}

export interface PreparationComputerNode {
  id: string;
  label: string;
  computer: ComputerInfo;
  projects: PreparationProjectNode[];
}

function sortAlphabetically(values: readonly string[]): string[] {
  return [...values].sort((left, right) => left.localeCompare(right));
}

function resolveComputer(
  computersByName: Map<string, ComputerInfo>,
  project: ProjectWithTodosInfo,
): ComputerInfo {
  const existing = computersByName.get(project.computer);
  if (existing) {
    return existing;
  }

  const synthesized: ComputerInfo = {
    name: project.computer,
    status: "unknown",
    is_local: project.computer === "local",
  };
  computersByName.set(project.computer, synthesized);
  return synthesized;
}

// Mirrors `PREPARE_LIFECYCLE_PHASES` in teleclaude/types/lifecycle.py:51-69.
// When a todo's `lifecycle_phase` is in this set, the prepare-lane branch of the
// cascade is eligible (the phase still needs an entry in `LIFECYCLE_DISPLAY_LABELS`
// to actually emit a tag — see `requirements_human_approval`).
const PREPARE_LANE_PHASES: ReadonlySet<string> = new Set([
  "draft",
  "input_assessment",
  "triangulation",
  "requirements_review",
  "requirements_human_approval",
  "test_spec_build",
  "test_spec_review",
  "plan_drafting",
  "plan_review",
  "gate",
  "grounding_check",
  "re_grounding",
  "prepared",
]);

// Mirrors `_LIFECYCLE_PHASE_LABELS` in teleclaude/cli/tui/widgets/todo_row.py:47-60.
// Phases absent from this map (e.g., `requirements_human_approval`) emit no
// prepare-lane indicator — the cascade falls through to the next priority.
const LIFECYCLE_DISPLAY_LABELS: Readonly<Record<string, string>> = {
  draft: "draft",
  input_assessment: "discovery",
  triangulation: "discovery",
  requirements_review: "requirements",
  test_spec_build: "requirements",
  test_spec_review: "requirements",
  plan_drafting: "planning",
  plan_review: "planning",
  gate: "planning",
  grounding_check: "planning",
  re_grounding: "planning",
  prepared: "ready",
};

const SUCCESS_VALUES: ReadonlySet<string> = new Set([
  "complete",
  "approved",
  "delivered",
  "ready",
  "prepared",
]);

const IN_PROGRESS_VALUES: ReadonlySet<string> = new Set([
  "input_assessment",
  "discovery",
  "requirements",
  "planning",
  "queued",
  "started",
]);

const FAILURE_VALUES: ReadonlySet<string> = new Set(["blocked", "failed"]);

export type PhaseTagColor = "green" | "gold" | "red" | "gray";

export function getPhaseTagColor(value: string): PhaseTagColor {
  if (SUCCESS_VALUES.has(value)) return "green";
  if (IN_PROGRESS_VALUES.has(value)) return "gold";
  if (FAILURE_VALUES.has(value)) return "red";
  return "gray";
}

export interface TodoStatusBlock {
  color: "green" | "gold" | "gray";
  filled: boolean;
}

export function getTodoStatusBlock(todo: TodoInfo): TodoStatusBlock {
  // Rule 1: delivered (terminal success).
  if (todo.status === "delivered" || todo.delivered_at) {
    return { color: "green", filled: true };
  }

  // Rule 2: prepare-lane lifecycle. PREPARED is a settled-success terminal → green.
  const lifecyclePhase = todo.lifecycle_phase ?? null;
  if (lifecyclePhase && PREPARE_LANE_PHASES.has(lifecyclePhase)) {
    if (lifecyclePhase === "prepared") {
      return { color: "green", filled: true };
    }
    return { color: "gold", filled: true };
  }

  // Rule 3: integration phase. `delivered` is terminal-success → green.
  const integrationPhase = todo.integration_phase ?? null;
  const finalizeStatus = todo.finalize_status ?? null;
  if (integrationPhase === "delivered") {
    return { color: "green", filled: true };
  }
  if (
    integrationPhase ||
    finalizeStatus === "ready" ||
    finalizeStatus === "handed_off"
  ) {
    return { color: "gold", filled: true };
  }

  // Rule 4: work in progress.
  const buildStatus = todo.build_status ?? null;
  if (buildStatus && buildStatus !== "pending") {
    return { color: "gold", filled: true };
  }

  // Rule 5: status-derived active/ready (no lifecycle/integration/build signal).
  if (todo.status === "active" || todo.status === "ready") {
    return { color: "gold", filled: true };
  }

  // Rule 6: default.
  return { color: "gray", filled: false };
}

export function deriveTodoPhaseTags(todo: TodoInfo): string[] {
  // Priority 1: prepare-lane lifecycle phase active.
  const lifecyclePhase = todo.lifecycle_phase ?? null;
  if (lifecyclePhase && PREPARE_LANE_PHASES.has(lifecyclePhase)) {
    const label = LIFECYCLE_DISPLAY_LABELS[lifecyclePhase];
    if (label) {
      return [`prepare:${label}`];
    }
    // Prepare-lane phase with no display label (e.g., requirements_human_approval):
    // emit no prepare indicator and fall through to the next priority.
  }

  // Priority 2: integration phase active, or finalize-status-derived integration value.
  const integrationPhase = todo.integration_phase ?? null;
  const finalizeStatus = todo.finalize_status ?? null;
  if (integrationPhase === "started") {
    return ["integration:started"];
  }
  if (integrationPhase === "delivered") {
    return ["integration:delivered"];
  }
  if (!integrationPhase) {
    if (finalizeStatus === "ready") {
      return ["integration:ready"];
    }
    if (finalizeStatus === "handed_off") {
      return ["integration:queued"];
    }
  }

  // Priority 3: work phase active (build_status non-pending).
  const buildStatus = todo.build_status ?? null;
  if (buildStatus && buildStatus !== "pending") {
    const tags: string[] = [`build:${buildStatus}`];
    if (todo.review_status) {
      tags.push(`review:${todo.review_status}`);
    }
    // findings:{count} is requested by SC-3 but `findings_count` is not on the
    // current backend contract (TodoDTO has no such field). The narrowing below
    // emits the tag the moment a future backend exposes it on TodoInfo, without
    // requiring further plan changes — same pattern the plan applied to dor_score.
    const findingsCount = readFindingsCount(todo);
    if (findingsCount !== null && findingsCount > 0) {
      tags.push(`findings:${findingsCount}`);
    }
    if (todo.deferrals_status) {
      tags.push(`deferrals:${todo.deferrals_status}`);
    }
    return tags;
  }

  // Priority 4: nothing else active. The current backend contract does not
  // expose `dor_score`, so the cascade emits an empty list. If `dor_score`
  // is later added back to TodoInfo, a defensive narrowing here can surface it.
  return [];
}

function readFindingsCount(todo: TodoInfo): number | null {
  // Defensive narrowing: TodoInfo does not declare findings_count today, but the
  // assembled DTO may carry it once the backend extends TodoDTO. Read it via
  // structural access without weakening the static type.
  const candidate = (todo as unknown as { findings_count?: unknown }).findings_count;
  return typeof candidate === "number" && Number.isFinite(candidate) ? candidate : null;
}

interface TopoSortResult {
  ordered: string[];
  hadCycle: boolean;
}

function topoSortSiblings(
  slugs: readonly string[],
  afterMap: ReadonlyMap<string, readonly string[]>,
): TopoSortResult {
  const siblingSet = new Set(slugs);
  const indexOf = new Map<string, number>(slugs.map((s, i) => [s, i]));
  const inDegree = new Map<string, number>(slugs.map((s) => [s, 0]));
  const dependents = new Map<string, string[]>(slugs.map((s) => [s, []]));

  for (const slug of slugs) {
    for (const dep of afterMap.get(slug) ?? []) {
      if (siblingSet.has(dep)) {
        inDegree.set(slug, (inDegree.get(slug) ?? 0) + 1);
        dependents.get(dep)!.push(slug);
      }
    }
  }

  const remaining = new Set(slugs);
  const result: string[] = [];
  let hadCycle = false;

  while (remaining.size > 0) {
    let next: string | null = null;
    let nextIdx = Number.POSITIVE_INFINITY;
    for (const slug of remaining) {
      if ((inDegree.get(slug) ?? 0) === 0) {
        const idx = indexOf.get(slug) ?? Number.POSITIVE_INFINITY;
        if (idx < nextIdx) {
          nextIdx = idx;
          next = slug;
        }
      }
    }
    if (next === null) {
      // Cycle fallback: keep visible rows and stable order rather than dropping todos
      // when dependency metadata is inconsistent. Append remaining in original input order.
      hadCycle = true;
      for (const slug of slugs) {
        if (remaining.has(slug)) {
          result.push(slug);
        }
      }
      break;
    }
    result.push(next);
    remaining.delete(next);
    for (const dep of dependents.get(next) ?? []) {
      inDegree.set(dep, (inDegree.get(dep) ?? 1) - 1);
    }
  }

  return { ordered: result, hadCycle };
}

interface ProjectTopology {
  rootIds: string[];
  todoChildren: Map<string, string[]>;
  groupChildren: Map<string, string[]>;
  groupLabelByRootId: Map<string, string>;
  todoBySlug: Map<string, TodoInfo>;
  visibleSlugs: Set<string>;
  rootIdOf: Map<string, string>;
  hadCycle: boolean;
}

const GROUP_PREFIX = "group:";

function isGroupRootId(rootId: string): boolean {
  return rootId.startsWith(GROUP_PREFIX);
}

function buildProjectTopology(project: ProjectWithTodosInfo): ProjectTopology {
  const todos = project.todos ?? [];
  const todoBySlug = new Map<string, TodoInfo>(
    todos.map((todo) => [todo.slug, todo]),
  );
  const visibleSlugs = new Set(todoBySlug.keys());

  // Phase 1: hierarchy from `group`.
  // A todo's `group` may name another visible todo (nest under it) or a non-todo
  // container label (becomes a PreparationGroupNode at project level).
  const todoParent = new Map<string, string | null>();
  const groupContainerForTodo = new Map<string, string>();
  const groupChildren = new Map<string, string[]>();
  const todoChildren = new Map<string, string[]>();
  const groupLabelByRootId = new Map<string, string>();
  const rootCandidatesInOrder: string[] = [];
  const seenRootIds = new Set<string>();

  for (const todo of todos) {
    const rawGroup = todo.group;
    if (rawGroup && rawGroup !== todo.slug && visibleSlugs.has(rawGroup)) {
      // Group references another visible todo: nest under it.
      todoParent.set(todo.slug, rawGroup);
      const siblings = todoChildren.get(rawGroup) ?? [];
      siblings.push(todo.slug);
      todoChildren.set(rawGroup, siblings);
      continue;
    }

    if (rawGroup && rawGroup !== todo.slug) {
      // Group references a non-todo container: expose group node at project level.
      const groupRootId = `${GROUP_PREFIX}${rawGroup}`;
      groupContainerForTodo.set(todo.slug, groupRootId);
      todoParent.set(todo.slug, null);
      const siblings = groupChildren.get(groupRootId) ?? [];
      siblings.push(todo.slug);
      groupChildren.set(groupRootId, siblings);
      if (!seenRootIds.has(groupRootId)) {
        rootCandidatesInOrder.push(groupRootId);
        seenRootIds.add(groupRootId);
        groupLabelByRootId.set(groupRootId, rawGroup);
      }
      continue;
    }

    // Ungrouped todo: candidate root.
    todoParent.set(todo.slug, null);
    const todoRootId = todo.slug;
    if (!seenRootIds.has(todoRootId)) {
      rootCandidatesInOrder.push(todoRootId);
      seenRootIds.add(todoRootId);
    }
  }

  // rootIdOf: which root each visible slug belongs to (group rootId for grouped, slug for ungrouped, ancestor root for nested).
  const rootIdOf = new Map<string, string>();
  function resolveRoot(slug: string): string {
    const cached = rootIdOf.get(slug);
    if (cached) return cached;
    const parent = todoParent.get(slug) ?? null;
    if (parent === null) {
      const groupRoot = groupContainerForTodo.get(slug);
      const root = groupRoot ?? slug;
      rootIdOf.set(slug, root);
      return root;
    }
    const root = resolveRoot(parent);
    rootIdOf.set(slug, root);
    return root;
  }
  for (const slug of visibleSlugs) {
    resolveRoot(slug);
  }

  // Phase 2: cross-root after-deps promote one root before another.
  const afterMap = new Map<string, string[]>(
    todos.map((todo) => [todo.slug, [...(todo.after ?? [])]]),
  );

  const rootAfter = new Map<string, string[]>(
    rootCandidatesInOrder.map((id) => [id, []]),
  );
  for (const todo of todos) {
    const itemRoot = rootIdOf.get(todo.slug);
    if (!itemRoot) continue;
    for (const dep of todo.after ?? []) {
      if (!visibleSlugs.has(dep)) continue;
      const depRoot = rootIdOf.get(dep);
      if (!depRoot || depRoot === itemRoot) continue;
      const list = rootAfter.get(itemRoot);
      if (list && !list.includes(depRoot)) {
        list.push(depRoot);
      }
    }
  }

  // Topo sort roots by input order with cross-root deps.
  const rootSort = topoSortSiblings(rootCandidatesInOrder, rootAfter);
  let hadCycle = rootSort.hadCycle;

  // Topo sort todo children inside each parent (todo with nested or group container).
  const sortedTodoChildren = new Map<string, string[]>();
  for (const [parent, children] of todoChildren) {
    const sort = topoSortSiblings(children, afterMap);
    sortedTodoChildren.set(parent, sort.ordered);
    if (sort.hadCycle) hadCycle = true;
  }
  const sortedGroupChildren = new Map<string, string[]>();
  for (const [groupRootId, children] of groupChildren) {
    const sort = topoSortSiblings(children, afterMap);
    sortedGroupChildren.set(groupRootId, sort.ordered);
    if (sort.hadCycle) hadCycle = true;
  }

  return {
    rootIds: rootSort.ordered,
    todoChildren: sortedTodoChildren,
    groupChildren: sortedGroupChildren,
    groupLabelByRootId,
    todoBySlug,
    visibleSlugs,
    rootIdOf,
    hadCycle,
  };
}

function buildTodoNode(
  slug: string,
  topology: ProjectTopology,
): PreparationTodoNode {
  const todo = topology.todoBySlug.get(slug);
  if (!todo) {
    throw new Error(
      `buildTodoNode: slug "${slug}" was scheduled for rendering but is missing from topology.todoBySlug`,
    );
  }
  const childSlugs = topology.todoChildren.get(slug) ?? [];
  return {
    id: `todo:${slug}`,
    label: slug,
    todo,
    phaseTags: deriveTodoPhaseTags(todo),
    files: sortAlphabetically(todo.files).map((filename) => ({
      id: `file:${slug}:${filename}`,
      label: filename,
      name: filename,
    })),
    todos: childSlugs.map((childSlug) => buildTodoNode(childSlug, topology)),
  };
}

function buildProjectNode(
  project: ProjectWithTodosInfo,
): PreparationProjectNode {
  const topology = buildProjectTopology(project);

  const rootChildren: PreparationRootChild[] = [];
  const groups: PreparationGroupNode[] = [];
  const todos: PreparationTodoNode[] = [];

  for (const rootId of topology.rootIds) {
    if (isGroupRootId(rootId)) {
      const label = topology.groupLabelByRootId.get(rootId) ?? rootId;
      const childSlugs = topology.groupChildren.get(rootId) ?? [];
      const groupNode: PreparationGroupNode = {
        id: `group:${project.path}:${label}`,
        label,
        todos: childSlugs.map((childSlug) => buildTodoNode(childSlug, topology)),
      };
      groups.push(groupNode);
      rootChildren.push({ kind: "group", node: groupNode });
    } else {
      const todoNode = buildTodoNode(rootId, topology);
      todos.push(todoNode);
      rootChildren.push({ kind: "todo", node: todoNode });
    }
  }

  let maxSlugLength = 0;
  for (const slug of topology.visibleSlugs) {
    if (slug.length > maxSlugLength) {
      maxSlugLength = slug.length;
    }
  }

  return {
    id: `project:${project.path}`,
    label: project.name,
    project,
    rootChildren,
    groups,
    todos,
    hasCyclicDeps: topology.hadCycle,
    maxSlugLength,
  };
}

export function buildPreparationTree(
  projects: readonly ProjectWithTodosInfo[],
  computers: readonly ComputerInfo[],
): PreparationComputerNode[] {
  const computersByName = new Map<string, ComputerInfo>(
    computers.map((computer) => [computer.name, computer]),
  );
  const treeByComputer = new Map<string, PreparationComputerNode>();

  for (const computer of computers) {
    treeByComputer.set(computer.name, {
      id: `computer:${computer.name}`,
      label: computer.name,
      computer,
      projects: [],
    });
  }

  for (const project of projects) {
    const computer = resolveComputer(computersByName, project);
    const computerNode = treeByComputer.get(computer.name) ?? {
      id: `computer:${computer.name}`,
      label: computer.name,
      computer,
      projects: [],
    };

    computerNode.projects.push(buildProjectNode(project));
    treeByComputer.set(computer.name, computerNode);
  }

  return [...treeByComputer.values()];
}
