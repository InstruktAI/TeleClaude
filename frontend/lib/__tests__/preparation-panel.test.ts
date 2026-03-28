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
    dor_score: null,
    deferrals_status: null,
    findings_count: 0,
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
  const bindingCases = [
    { key: "n", modifiers: {}, action: "new_todo" },
    { key: "b", modifiers: {}, action: "new_bug" },
    { key: "r", modifiers: {}, action: "refine_input" },
    { key: "R", modifiers: { shift: true }, action: "remove_todo" },
    { key: "f", modifiers: {}, action: "freeze_todo" },
    { key: "upArrow", modifiers: { shift: true }, action: "move_todo_up" },
    { key: "downArrow", modifiers: { shift: true }, action: "move_todo_down" },
  ] as const;

  for (const { key, modifiers, action } of bindingCases) {
    it(`registers ${action} in the preparation context`, () => {
      const binding = findBinding(key, modifiers, "preparation");

      expect(binding).toMatchObject({
        key,
        context: "preparation",
        action,
      });
    });
  }
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
  const phaseCases = [
    {
      name: "includes B when build status exists",
      todo: makeTodo({ build_status: "built" }),
      expected: ["B"],
    },
    {
      name: "includes R when review status exists",
      todo: makeTodo({ review_status: "approved" }),
      expected: ["R"],
    },
    {
      name: "includes DOR when a DOR score exists",
      todo: makeTodo({ dor_score: 7 }),
      expected: ["DOR"],
    },
    {
      name: "includes DEF when deferrals status exists",
      todo: makeTodo({ deferrals_status: "deferred" }),
      expected: ["DEF"],
    },
    {
      name: "includes F when findings count is non-zero",
      todo: makeTodo({ findings_count: 2 }),
      expected: ["F"],
    },
    {
      name: "returns the full compact set when every phase signal exists",
      todo: makeTodo({
        build_status: "built",
        review_status: "approved",
        dor_score: 9,
        deferrals_status: "deferred",
        findings_count: 1,
      }),
      expected: ["B", "R", "DOR", "DEF", "F"],
    },
  ] as const;

  for (const phaseCase of phaseCases) {
    it(phaseCase.name, async () => {
      const modulePath = "@/lib/preparation/tree" as string;
      const { deriveTodoPhaseTags } = await import(modulePath);

      expect(deriveTodoPhaseTags(phaseCase.todo)).toEqual(phaseCase.expected);
    });
  }
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
