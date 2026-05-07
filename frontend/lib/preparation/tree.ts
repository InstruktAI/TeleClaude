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
}

export interface PreparationProjectNode {
  id: string;
  label: string;
  project: ProjectWithTodosInfo;
  todos: PreparationTodoNode[];
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

export function deriveTodoPhaseTags(todo: TodoInfo): string[] {
  const tags: string[] = [];

  if (todo.build_status) {
    tags.push("B");
  }
  if (todo.review_status) {
    tags.push("R");
  }
  if (todo.deferrals_status) {
    tags.push("DEF");
  }

  return tags;
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

    const projectNode: PreparationProjectNode = {
      id: `project:${project.path}`,
      label: project.name,
      project,
      todos: (project.todos ?? []).map((todo) => ({
        id: `todo:${todo.slug}`,
        label: todo.slug,
        todo,
        phaseTags: deriveTodoPhaseTags(todo),
        files: sortAlphabetically(todo.files).map((filename) => ({
          id: `file:${todo.slug}:${filename}`,
          label: filename,
          name: filename,
        })),
      })),
    };

    computerNode.projects.push(projectNode);
    treeByComputer.set(computer.name, computerNode);
  }

  return [...treeByComputer.values()];
}
