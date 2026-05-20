/**
 * Tests for the preparation panel tree and actions.
 *
 * Behavioral contract: buildPreparationTree groups daemon todo data into a
 * computer → project → (group →)? todo → file hierarchy, derives phase
 * display tags via a priority cascade, applies color semantics to phase
 * values, renders status-block indicators, and supports column alignment.
 *
 * All SC-1 through SC-8 cases are active (no expected-failure markers): the
 * cascade, color helper, status-block helper, and project-level alignment
 * metadata are implemented in lib/preparation/tree.ts and exercised here.
 * Browser smoke for SC-8 lives in frontend/e2e/preparation.spec.ts.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import { findBinding } from '@/lib/keys/bindings';
import type { ComputerInfo, ProjectWithTodosInfo, TodoInfo } from '@/lib/api/types';

// ---------------------------------------------------------------------------
// Factories
// ---------------------------------------------------------------------------

let todoCounter = 0;

beforeEach(() => {
  todoCounter = 0;
});

function expectPreparationBinding(key: string, modifiers: { shift?: boolean }, action: string): void {
  const binding = findBinding(key, modifiers, 'preparation');

  expect(binding).toMatchObject({
    key,
    context: 'preparation',
    action,
  });
}

function makeComputer(overrides?: Partial<ComputerInfo>): ComputerInfo {
  return {
    name: 'local',
    status: 'online',
    is_local: true,
    ...overrides,
  };
}

/**
 * Factory for TodoInfo including all lifecycle fields introduced by SC-1.
 * New fields: after, group, lifecycle_phase, integration_phase, finalize_status,
 * delivered_at.
 */
function makeTodo(overrides?: Partial<TodoInfo>): TodoInfo {
  todoCounter += 1;
  return {
    slug: `todo-${todoCounter}`,
    status: 'pending',
    has_requirements: true,
    has_impl_plan: false,
    build_status: null,
    review_status: null,
    deferrals_status: null,
    files: [],
    // SC-1 lifecycle fields
    after: [],
    group: null,
    lifecycle_phase: null,
    integration_phase: null,
    finalize_status: null,
    delivered_at: null,
    ...overrides,
  };
}

function makeProject(overrides?: Partial<ProjectWithTodosInfo>): ProjectWithTodosInfo {
  return {
    computer: 'local',
    name: 'teleclaude',
    path: '/workspace/teleclaude',
    todos: [],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Existing behavior — it() (already implemented, suite stays green)
// ---------------------------------------------------------------------------

describe('preparation panel bindings', () => {
  it('registers new_todo in the preparation context', () => {
    expectPreparationBinding('n', {}, 'new_todo');
  });

  it('registers new_bug in the preparation context', () => {
    expectPreparationBinding('b', {}, 'new_bug');
  });

  it('registers refine_input in the preparation context', () => {
    expectPreparationBinding('r', {}, 'refine_input');
  });

  it('registers remove_todo in the preparation context', () => {
    expectPreparationBinding('R', { shift: true }, 'remove_todo');
  });

  it('registers freeze_todo in the preparation context', () => {
    expectPreparationBinding('f', {}, 'freeze_todo');
  });

  it('registers move_todo_up in the preparation context', () => {
    expectPreparationBinding('upArrow', { shift: true }, 'move_todo_up');
  });

  it('registers move_todo_down in the preparation context', () => {
    expectPreparationBinding('downArrow', { shift: true }, 'move_todo_down');
  });
});

describe('buildPreparationTree (basic)', () => {
  it('groups computers, projects, todos, and alphabetized file children', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { buildPreparationTree } = await import(modulePath);

    const tree = buildPreparationTree(
      [
        makeProject({
          name: 'teleclaude',
          path: '/workspace/teleclaude',
          todos: [
            makeTodo({
              slug: 'web-tui-panels',
              files: ['z-last.md', 'a-first.md', 'm-middle.md'],
            }),
          ],
        }),
      ],
      [makeComputer()],
    );

    expect(tree).toHaveLength(1);
    expect(tree[0].computer.name).toBe('local');
    expect(tree[0].computer.status).toBe('online');
    expect(tree[0].projects).toHaveLength(1);
    expect(tree[0].projects[0].project.path).toBe('/workspace/teleclaude');
    expect(tree[0].projects[0].todos).toHaveLength(1);
    expect(tree[0].projects[0].todos[0].todo.slug).toBe('web-tui-panels');
    expect(tree[0].projects[0].todos[0].files.map((file: { name: string }) => file.name)).toEqual([
      'a-first.md',
      'm-middle.md',
      'z-last.md',
    ]);
  });
});

describe('getPreparationActionAvailability', () => {
  it('marks unsupported roadmap actions as disabled with daemon-gap reasons', async () => {
    const modulePath = '@/lib/preparation/actions' as string;
    const { getPreparationActionAvailability } = await import(modulePath);

    const availability = getPreparationActionAvailability({
      kind: 'todo',
      todo: makeTodo({ slug: 'web-tui-panels' }),
    });

    expect(availability.prepare.enabled).toBe(true);
    expect(availability.startWork.enabled).toBe(true);
    expect(availability.refine.enabled).toBe(true);
    expect(availability.remove).toEqual({
      enabled: false,
      reason: 'daemon_endpoint_unavailable',
    });
    expect(availability.freeze).toEqual({
      enabled: false,
      reason: 'daemon_endpoint_unavailable',
    });
    expect(availability.moveUp).toEqual({
      enabled: false,
      reason: 'daemon_endpoint_unavailable',
    });
    expect(availability.moveDown).toEqual({
      enabled: false,
      reason: 'daemon_endpoint_unavailable',
    });
  });
});

// ---------------------------------------------------------------------------
// SC-1: TodoInfo type completeness — behavioral consequence tests
//
// TypeScript struct checks (tsc --noEmit) are the enforcement for the type
// definition. The tests here verify behavioral consequences of the new fields.
// SC-3/SC-4/SC-5 all depend on lifecycle_phase, integration_phase, delivered_at,
// etc. being accessible — those are the runtime contracts.
//
// NOTE: The current backend contract exposes lifecycle_phase and finalize_status,
// not the stale prepare_phase, todo_dir, dor_score, or findings_count fields.
// The tests below pin behavior against that generated contract.
// ---------------------------------------------------------------------------

describe('SC-1: TodoInfo lifecycle fields', () => {
  it('deriveTodoPhaseTags reads lifecycle_phase from TodoInfo (current implementation ignores it)', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { deriveTodoPhaseTags } = await import(modulePath);

    // A todo with ONLY lifecycle_phase set and no legacy signals (build_status etc.)
    // Current deriveTodoPhaseTags does not read lifecycle_phase — returns [].
    // New implementation must return a prepare: tag.
    const todo = makeTodo({
      lifecycle_phase: 'requirements_review',
      build_status: null,
      review_status: null,
      deferrals_status: null,
    });
    const tags: string[] = deriveTodoPhaseTags(todo);

    expect(tags).toContain('prepare:requirements');
  });

  it('buildPreparationTree exposes finalize_status on the tree node (already implemented — type-completeness behavioral guard)', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { buildPreparationTree } = await import(modulePath);

    // finalize_status is not yet consumed by phase cascade logic, but it must
    // be accessible on the tree node so the UI can read it.
    const todo = makeTodo({
      slug: 'finalize-test',
      finalize_status: 'finalized',
    });
    const tree = buildPreparationTree([makeProject({ todos: [todo] })], [makeComputer()]);

    const node = tree[0].projects[0].todos[0];
    expect(node.todo.finalize_status).toBe('finalized');
  });
});

// ---------------------------------------------------------------------------
// SC-2: Dependency-ordered tree — it.fails
// ---------------------------------------------------------------------------

describe('SC-2: dependency-ordered tree', () => {
  it('todo with after:[B] renders after B within the same project', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { buildPreparationTree } = await import(modulePath);

    const todoB = makeTodo({ slug: 'B' });
    const todoA = makeTodo({ slug: 'A', after: ['B'] });
    // Intentionally provide A before B in input to verify reordering
    const tree = buildPreparationTree([makeProject({ todos: [todoA, todoB] })], [makeComputer()]);

    const slugs = tree[0].projects[0].todos.map((node: { todo: { slug: string } }) => node.todo.slug);
    // B must appear before A because A depends on B
    expect(slugs.indexOf('B')).toBeLessThan(slugs.indexOf('A'));
  });

  it('todo with group:X renders nested under a group node X', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { buildPreparationTree } = await import(modulePath);

    const grouped = makeTodo({ slug: 'grouped-todo', group: 'release' });
    const ungrouped = makeTodo({ slug: 'ungrouped-todo', group: null });
    const tree = buildPreparationTree([makeProject({ todos: [grouped, ungrouped] })], [makeComputer()]);

    const projectNode = tree[0].projects[0];
    // The project must expose a group node for "release"
    const groupNode = projectNode.groups?.find((g: { label: string }) => g.label === 'release');
    expect(groupNode).toBeDefined();
    expect(groupNode.todos.map((n: { todo: { slug: string } }) => n.todo.slug)).toContain('grouped-todo');
    // Ungrouped todo must not appear under a group node
    expect(projectNode.todos.map((n: { todo: { slug: string } }) => n.todo.slug)).toContain('ungrouped-todo');
  });

  it('cyclic after references do not infinite-loop: tree reports cycle metadata', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { buildPreparationTree } = await import(modulePath);

    const todoX = makeTodo({ slug: 'X', after: ['Y'] });
    const todoY = makeTodo({ slug: 'Y', after: ['X'] });

    // Must not throw AND must expose cycle metadata on the project node so
    // the UI can surface a warning. hasCyclicDeps is new — current code
    // doesn't emit it, so this test fails until implemented.
    const tree = buildPreparationTree([makeProject({ todos: [todoX, todoY] })], [makeComputer()]);

    const projectNode = tree[0].projects[0];
    expect(projectNode).toHaveProperty('hasCyclicDeps', true);
    // Cyclic deps must fall back to input order (X then Y), not an arbitrary order
    const slugs = projectNode.todos.map((n: { todo: { slug: string } }) => n.todo.slug);
    expect(slugs).toEqual(['X', 'Y']);
  });

  it('todo with after referencing a non-existent slug renders at input position without throwing (already implemented — external dep fallback)', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { buildPreparationTree } = await import(modulePath);

    // Requirements: "external dependencies fall back to input order without errors [inferred]"
    // A builder who throws on unresolved deps would fail this test.
    const todoA = makeTodo({ slug: 'A', after: ['does-not-exist'] });
    const todoB = makeTodo({ slug: 'B' });

    let tree: unknown;
    expect(() => {
      tree = buildPreparationTree([makeProject({ todos: [todoA, todoB] })], [makeComputer()]);
    }).not.toThrow();

    // A should remain at its input position (index 0) since the dependency is unresolvable
    const slugs = (tree as { projects: { todos: { todo: { slug: string } }[] }[] }[])[0].projects[0].todos.map(
      (n: { todo: { slug: string } }) => n.todo.slug,
    );
    expect(slugs[0]).toBe('A');
  });
});

// ---------------------------------------------------------------------------
// SC-3: Structured phase display with priority cascade — it.fails
//
// Replaces old deriveTodoPhaseTags compact-letter tests. The function now
// returns prefix:value pairs (e.g., "prepare:requirements") and follows a
// strict priority cascade: prepare > integration > work > empty fallback.
// ---------------------------------------------------------------------------

describe('SC-3: phase priority cascade (deriveTodoPhaseTags)', () => {
  it('prepare-lane lifecycle phase active → returns prepare:{display_label} tag, integration:value not present', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { deriveTodoPhaseTags } = await import(modulePath);

    const todo = makeTodo({ lifecycle_phase: 'input_assessment' });
    const tags: string[] = deriveTodoPhaseTags(todo);

    expect(tags.some((t: string) => t.startsWith('prepare:'))).toBe(true);
    expect(tags.find((t: string) => t.startsWith('prepare:'))).toBe('prepare:discovery');
    expect(tags.every((t: string) => !t.startsWith('integration:'))).toBe(true);
  });

  it('integration phase active, no prepare phase → returns integration:value pair (cascade priority 2)', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { deriveTodoPhaseTags } = await import(modulePath);

    const todo = makeTodo({
      lifecycle_phase: null,
      integration_phase: 'delivered',
    });
    const tags: string[] = deriveTodoPhaseTags(todo);

    expect(tags.some((t: string) => t.startsWith('integration:'))).toBe(true);
    expect(tags.every((t: string) => !t.startsWith('prepare:'))).toBe(true);
  });

  it('prepare phase takes priority over integration phase', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { deriveTodoPhaseTags } = await import(modulePath);

    const todo = makeTodo({
      lifecycle_phase: 'input_assessment',
      integration_phase: 'started',
    });
    const tags: string[] = deriveTodoPhaseTags(todo);

    // Prepare beats integration in the cascade
    expect(tags.some((t: string) => t.startsWith('prepare:'))).toBe(true);
    expect(tags.every((t: string) => !t.startsWith('integration:'))).toBe(true);
  });

  it('work phase active (non-pending build_status), no prepare/integration → returns work phase columns (cascade priority 3)', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { deriveTodoPhaseTags } = await import(modulePath);

    const todo = makeTodo({
      lifecycle_phase: null,
      integration_phase: null,
      build_status: 'complete',
      review_status: 'approved',
      deferrals_status: null,
    });
    const tags: string[] = deriveTodoPhaseTags(todo);

    expect(tags.some((t: string) => t.startsWith('build:'))).toBe(true);
    expect(tags.some((t: string) => t.startsWith('review:'))).toBe(true);
    expect(tags.every((t: string) => !t.startsWith('prepare:'))).toBe(true);
    expect(tags.every((t: string) => !t.startsWith('integration:'))).toBe(true);
  });

  it('work phase with deferrals → returns deferrals: tag', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { deriveTodoPhaseTags } = await import(modulePath);

    const todo = makeTodo({
      lifecycle_phase: null,
      integration_phase: null,
      build_status: 'complete',
      review_status: 'approved',
      deferrals_status: 'open',
    });
    const tags: string[] = deriveTodoPhaseTags(todo);

    expect(tags.some((t: string) => t.startsWith('deferrals:'))).toBe(true);
  });

  it('work phase active → returns build/review/deferrals tags', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { deriveTodoPhaseTags } = await import(modulePath);

    const todo = makeTodo({
      lifecycle_phase: null,
      integration_phase: null,
      build_status: 'complete',
      review_status: 'approved',
      deferrals_status: 'open',
    });
    const tags: string[] = deriveTodoPhaseTags(todo);

    expect(tags.some((t: string) => t.startsWith('build:'))).toBe(true);
    expect(tags.some((t: string) => t.startsWith('review:'))).toBe(true);
    expect(tags.some((t: string) => t.startsWith('deferrals:'))).toBe(true);
  });

  // findings:{count} is requested by SC-3 but the current backend contract
  // (TodoDTO) does not declare findings_count. The cascade defensively reads
  // the field if present — same pattern the plan-drafter used for dor_score.
  // Today: no findings tag emitted (field absent). Future: tag emitted once
  // the backend surfaces findings_count on TodoInfo.
  it('work phase active without findings_count → no findings: tag emitted (current contract)', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { deriveTodoPhaseTags } = await import(modulePath);

    const todo = makeTodo({
      lifecycle_phase: null,
      integration_phase: null,
      build_status: 'complete',
      review_status: 'approved',
    });
    const tags: string[] = deriveTodoPhaseTags(todo);

    expect(tags.every((t: string) => !t.startsWith('findings:'))).toBe(true);
  });

  it('work phase active with findings_count present → emits findings:{count} (future contract narrowing)', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { deriveTodoPhaseTags } = await import(modulePath);

    // Construct a TodoInfo + the future findings_count field via structural
    // extension. TypeScript does not declare findings_count on TodoInfo today.
    const baseTodo = makeTodo({
      lifecycle_phase: null,
      integration_phase: null,
      build_status: 'complete',
      review_status: 'approved',
    });
    const todo = { ...baseTodo, findings_count: 3 } as unknown as TodoInfo;
    const tags: string[] = deriveTodoPhaseTags(todo);

    expect(tags).toContain('findings:3');
  });

  it('work phase active with findings_count = 0 → no findings: tag (count must be > 0)', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { deriveTodoPhaseTags } = await import(modulePath);

    const baseTodo = makeTodo({
      lifecycle_phase: null,
      integration_phase: null,
      build_status: 'complete',
    });
    const todo = { ...baseTodo, findings_count: 0 } as unknown as TodoInfo;
    const tags: string[] = deriveTodoPhaseTags(todo);

    expect(tags.every((t: string) => !t.startsWith('findings:'))).toBe(true);
  });

  it('no active prepare/integration/work phase → returns empty tag list (cascade priority 4 returns empty when no other phase signal is present)', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { deriveTodoPhaseTags } = await import(modulePath);

    const todo = makeTodo({
      lifecycle_phase: null,
      integration_phase: null,
      build_status: null,
    });
    const tags: string[] = deriveTodoPhaseTags(todo);

    expect(tags).toEqual([]);
  });

  it('todo with no phase signals → returns empty tag list (preserved behavior)', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { deriveTodoPhaseTags } = await import(modulePath);

    const todo = makeTodo({
      lifecycle_phase: null,
      integration_phase: null,
      build_status: null,
      review_status: null,
      deferrals_status: null,
    });
    const tags: string[] = deriveTodoPhaseTags(todo);

    expect(tags).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// SC-4: Color semantics — it.fails
// ---------------------------------------------------------------------------

describe('SC-4: phase value color semantics (getPhaseTagColor)', () => {
  it("returns 'green' for terminal-success values like 'prepared'", async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { getPhaseTagColor } = await import(modulePath);

    expect(getPhaseTagColor('prepared')).toBe('green');
  });

  it("returns 'gold' for in-progress values like 'discovery'", async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { getPhaseTagColor } = await import(modulePath);

    expect(getPhaseTagColor('discovery')).toBe('gold');
  });

  it("returns 'red' for failure/blocked values like 'blocked'", async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { getPhaseTagColor } = await import(modulePath);

    expect(getPhaseTagColor('blocked')).toBe('red');
  });

  it('returns the default muted color for unrecognized values', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { getPhaseTagColor } = await import(modulePath);

    expect(getPhaseTagColor('__unrecognized__')).toBe('gray');
  });
});

// ---------------------------------------------------------------------------
// SC-5 / SC-7: Status block indicator — it.fails
// ---------------------------------------------------------------------------

describe('SC-5/SC-7: status block indicator (getTodoStatusBlock)', () => {
  it('delivered todo → filled-green block', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { getTodoStatusBlock } = await import(modulePath);

    const todo = makeTodo({
      status: 'delivered',
      delivered_at: '2026-04-01T10:00:00Z',
    });
    const block = getTodoStatusBlock(todo);

    expect(block.color).toBe('green');
    // Filled block character (█ U+2588 or equivalent)
    expect(block.filled).toBe(true);
  });

  it('pending/draft todo with no active work → empty-gray block', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { getTodoStatusBlock } = await import(modulePath);

    const todo = makeTodo({
      status: 'pending',
      build_status: null,
      lifecycle_phase: null,
      integration_phase: null,
    });
    const block = getTodoStatusBlock(todo);

    expect(block.color).toBe('gray');
    expect(block.filled).toBe(false);
  });

  it('todo with active work in progress → filled-gold block', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { getTodoStatusBlock } = await import(modulePath);

    const todo = makeTodo({
      status: 'active',
      lifecycle_phase: null,
      integration_phase: null,
      build_status: 'building',
    });
    const block = getTodoStatusBlock(todo);

    expect(block.color).toBe('gold');
    expect(block.filled).toBe(true);
  });

  it('todo with active prepare phase → filled-gold block', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { getTodoStatusBlock } = await import(modulePath);

    const todo = makeTodo({
      status: 'active',
      lifecycle_phase: 'discovery',
    });
    const block = getTodoStatusBlock(todo);

    expect(block.color).toBe('gold');
    expect(block.filled).toBe(true);
  });

  it('todo with lifecycle_phase:prepared → filled-green block (green comes from lifecycle_phase, not status)', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { getTodoStatusBlock } = await import(modulePath);

    // Green comes from lifecycle_phase: "prepared" (a terminal success value per SC-4),
    // not from status: "ready". See the next test for status:ready without lifecycle_phase.
    const todo = makeTodo({
      status: 'ready',
      lifecycle_phase: 'prepared',
    });
    const block = getTodoStatusBlock(todo);

    expect(block.color).toBe('green');
    expect(block.filled).toBe(true);
  });

  it('todo with status:ready and no lifecycle_phase → filled-gold block (I-4: status:ready alone maps to gold, not green)', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { getTodoStatusBlock } = await import(modulePath);

    // Requirements SC-5: "ready" is listed under gold (active/in-progress/ready status).
    // When there is no lifecycle_phase driving a green color, status:ready → gold block.
    const todo = makeTodo({
      status: 'ready',
      lifecycle_phase: null,
    });
    const block = getTodoStatusBlock(todo);

    expect(block.color).toBe('gold');
    expect(block.filled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// SC-6: Column alignment metadata — it.fails
// ---------------------------------------------------------------------------

describe('SC-6: column alignment metadata', () => {
  it('project node exposes maxSlugLength so consumers can align phase columns', async () => {
    const modulePath = '@/lib/preparation/tree' as string;
    const { buildPreparationTree } = await import(modulePath);

    const tree = buildPreparationTree(
      [
        makeProject({
          todos: [makeTodo({ slug: 'short' }), makeTodo({ slug: 'very-long-slug-name' })],
        }),
      ],
      [makeComputer()],
    );

    const projectNode = tree[0].projects[0];
    // The project node must expose the longest slug length so the UI can
    // compute a fixed column offset for phase indicators
    expect(typeof projectNode.maxSlugLength).toBe('number');
    expect(projectNode.maxSlugLength).toBe('very-long-slug-name'.length);
  });
});

// ---------------------------------------------------------------------------
// SC-8: Browser smoke verification — it.fails
//
// Two-part DoD requirement:
//
// Part A (Vitest): PreparationView component module exports a renderable
//   component. Builder removes it.fails marker when the component is created.
//
// Part B (Playwright): A real browser smoke test in frontend/e2e/preparation.spec.ts
//   verifies tree render, phase indicators, and status blocks. That file uses
//   test.skip until a running server is available for e2e. It is a separate
//   artifact from this Vitest spec — see frontend/e2e/preparation.spec.ts.
// ---------------------------------------------------------------------------

describe('SC-8: preparation pane smoke', () => {
  it('PreparationView module exports a renderable component (already implemented — smoke check)', async () => {
    // Part A: The component module exports a default or named PreparationView.
    // This test is green because the component already exists.
    //
    // Part B is in frontend/e2e/preparation.spec.ts (Playwright, test.skip scaffold).
    const modulePath = '@/components/preparation/PreparationView' as string;
    const mod = await import(modulePath);

    expect(mod.default ?? (mod as Record<string, unknown>).PreparationView).toBeDefined();
  });
});
