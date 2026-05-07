/**
 * Test specifications for the preparation panel tree and actions.
 *
 * Behavioral contract: buildPreparationTree groups daemon todo data into a
 * computer → project → todo → file hierarchy, derives compact phase badges,
 * exposes keyboard/action contracts for supported operations, and tracks the
 * visible tree state for navigation.
 *
 * All tests are marked as expected failures (it.fails) until implementation exists.
 */

import { beforeEach, describe, expect, it } from "vitest";
import { findBinding } from "@/lib/keys/bindings";
import type {
  ComputerInfo,
  ProjectWithTodosInfo,
  TodoInfo,
} from "@/lib/api/types";

let todoCounter = 0;

beforeEach(() => {
  todoCounter = 0;
});

function expectPreparationBinding(
  key: string,
  modifiers: { shift?: boolean },
  action: string,
): void {
  const binding = findBinding(key, modifiers, "preparation");

  expect(binding).toMatchObject({
    key,
    context: "preparation",
    action,
  });
}

function makeComputer(overrides?: Partial<ComputerInfo>): ComputerInfo {
  return {
    name: "local",
    status: "online",
    is_local: true,
    ...overrides,
  };
}

function makeTodo(overrides?: Partial<TodoInfo>): TodoInfo {
  todoCounter += 1;
  return {
    slug: `todo-${todoCounter}`,
    status: "pending",
    has_requirements: true,
    has_impl_plan: false,
    build_status: null,
    review_status: null,
    deferrals_status: null,
    files: [],
    ...overrides,
  };
}

function makeProject(overrides?: Partial<ProjectWithTodosInfo>): ProjectWithTodosInfo {
  return {
    computer: "local",
    name: "teleclaude",
    path: "/workspace/teleclaude",
    todos: [],
    ...overrides,
  };
}

describe("preparation panel bindings", () => {
  it("registers new_todo in the preparation context", () => {
    expectPreparationBinding("n", {}, "new_todo");
  });

  it("registers new_bug in the preparation context", () => {
    expectPreparationBinding("b", {}, "new_bug");
  });

  it("registers refine_input in the preparation context", () => {
    expectPreparationBinding("r", {}, "refine_input");
  });

  it("registers remove_todo in the preparation context", () => {
    expectPreparationBinding("R", { shift: true }, "remove_todo");
  });

  it("registers freeze_todo in the preparation context", () => {
    expectPreparationBinding("f", {}, "freeze_todo");
  });

  it("registers move_todo_up in the preparation context", () => {
    expectPreparationBinding("upArrow", { shift: true }, "move_todo_up");
  });

  it("registers move_todo_down in the preparation context", () => {
    expectPreparationBinding("downArrow", { shift: true }, "move_todo_down");
  });
});

describe("buildPreparationTree", () => {
  it("groups computers, projects, todos, and alphabetized file children", async () => {
    const modulePath = "@/lib/preparation/tree" as string;
    const { buildPreparationTree } = await import(modulePath);

    const tree = buildPreparationTree(
      [
        makeProject({
          name: "teleclaude",
          path: "/workspace/teleclaude",
          todos: [
            makeTodo({
              slug: "web-tui-panels",
              files: ["z-last.md", "a-first.md", "m-middle.md"],
            }),
          ],
        }),
      ],
      [makeComputer()],
    );

    expect(tree).toHaveLength(1);
    expect(tree[0].computer.name).toBe("local");
    expect(tree[0].computer.status).toBe("online");
    expect(tree[0].projects).toHaveLength(1);
    expect(tree[0].projects[0].project.path).toBe("/workspace/teleclaude");
    expect(tree[0].projects[0].todos).toHaveLength(1);
    expect(tree[0].projects[0].todos[0].todo.slug).toBe("web-tui-panels");
    expect(tree[0].projects[0].todos[0].files.map((file: { name: string }) => file.name)).toEqual([
      "a-first.md",
      "m-middle.md",
      "z-last.md",
    ]);
  });
});
describe("deriveTodoPhaseTags", () => {
  it("includes B when build status exists", async () => {
    const modulePath = "@/lib/preparation/tree" as string;
    const { deriveTodoPhaseTags } = await import(modulePath);

    expect(deriveTodoPhaseTags(makeTodo({ build_status: "built" }))).toEqual(["B"]);
  });

  it("includes R when review status exists", async () => {
    const modulePath = "@/lib/preparation/tree" as string;
    const { deriveTodoPhaseTags } = await import(modulePath);

    expect(deriveTodoPhaseTags(makeTodo({ review_status: "approved" }))).toEqual(["R"]);
  });

  it("includes DEF when deferrals status exists", async () => {
    const modulePath = "@/lib/preparation/tree" as string;
    const { deriveTodoPhaseTags } = await import(modulePath);

    expect(deriveTodoPhaseTags(makeTodo({ deferrals_status: "deferred" }))).toEqual(["DEF"]);
  });
});

describe("getPreparationActionAvailability", () => {
  it("marks unsupported roadmap actions as disabled with daemon-gap reasons", async () => {
    const modulePath = "@/lib/preparation/actions" as string;
    const { getPreparationActionAvailability } = await import(modulePath);

    const availability = getPreparationActionAvailability({
      kind: "todo",
      todo: makeTodo({ slug: "web-tui-panels" }),
    });

    expect(availability.prepare.enabled).toBe(true);
    expect(availability.startWork.enabled).toBe(true);
    expect(availability.refine.enabled).toBe(true);
    expect(availability.remove).toEqual({
      enabled: false,
      reason: "daemon_endpoint_unavailable",
    });
    expect(availability.freeze).toEqual({
      enabled: false,
      reason: "daemon_endpoint_unavailable",
    });
    expect(availability.moveUp).toEqual({
      enabled: false,
      reason: "daemon_endpoint_unavailable",
    });
    expect(availability.moveDown).toEqual({
      enabled: false,
      reason: "daemon_endpoint_unavailable",
    });
  });
});
