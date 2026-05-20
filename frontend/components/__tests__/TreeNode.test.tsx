// @vitest-environment happy-dom

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { TreeNode } from '../preparation/TreeNode';
import type { TodoInfo } from '@/lib/api/types';

afterEach(() => {
  cleanup();
});

function makeTodo(overrides?: Partial<TodoInfo>): TodoInfo {
  return {
    slug: 'todo-default',
    status: 'pending',
    description: null,
    computer: 'local',
    project_path: '/workspace/teleclaude',
    has_requirements: true,
    has_impl_plan: false,
    build_status: null,
    review_status: null,
    deferrals_status: null,
    files: [],
    after: [],
    group: null,
    lifecycle_phase: null,
    integration_phase: null,
    finalize_status: null,
    delivered_at: null,
    ...overrides,
  };
}

function renderTodoRow(todo: TodoInfo): void {
  render(
    <TreeNode
      label={todo.slug}
      type="todo"
      depth={2}
      expanded={false}
      hasChildren={false}
      isCursor={false}
      todo={todo}
      onToggle={() => {}}
    />,
  );
}

describe('TreeNode phase indicator (SC-3)', () => {
  it('renders a visible phase-indicator element with prefix:value text for a todo with active lifecycle_phase', () => {
    renderTodoRow(makeTodo({ lifecycle_phase: 'input_assessment' }));

    const indicator = screen.getByTestId('phase-indicator');
    expect(indicator.textContent).toBe('prepare:discovery');
  });
});

describe('TreeNode slug column alignment (SC-6)', () => {
  it('renders todo rows with a fixed-width slug column derived from project maxSlugLength', () => {
    render(
      <>
        <TreeNode
          label="short"
          type="todo"
          depth={2}
          expanded={false}
          hasChildren={false}
          isCursor={false}
          todo={makeTodo({ slug: 'short' })}
          slugColWidth={19}
          onToggle={() => {}}
        />
        <TreeNode
          label="very-long-slug-name"
          type="todo"
          depth={2}
          expanded={false}
          hasChildren={false}
          isCursor={false}
          todo={makeTodo({ slug: 'very-long-slug-name' })}
          slugColWidth={19}
          onToggle={() => {}}
        />
      </>,
    );

    const rows = screen.getAllByTestId('preparation-todo-node');
    expect(rows).toHaveLength(2);
    expect(rows[0].dataset.slugColWidth).toBe('19');
    expect(rows[1].dataset.slugColWidth).toBe('19');
  });
});

describe('TreeNode status block (SC-5/SC-7)', () => {
  it('renders a status-block element with the success color for a delivered todo', () => {
    renderTodoRow(makeTodo({ status: 'delivered', delivered_at: '2026-04-01T10:00:00Z' }));

    const block = screen.getByTestId('status-block');
    expect(block.dataset.color).toBe('green');
    expect(block.dataset.filled).toBe('true');
  });

  it('renders an empty status-block element with the muted color for a draft todo', () => {
    renderTodoRow(makeTodo({ status: 'pending' }));

    const block = screen.getByTestId('status-block');
    expect(block.dataset.color).toBe('gray');
    expect(block.dataset.filled).toBe('false');
  });
});

describe('TreeNode phase color (SC-4)', () => {
  it('applies success color token to phase indicators with terminal-success values', () => {
    renderTodoRow(makeTodo({ lifecycle_phase: 'prepared' }));

    const indicator = screen.getByTestId('phase-indicator');
    expect(indicator.dataset.color).toBe('green');
  });

  it('applies failure color token to phase indicators with failure/blocked values', () => {
    renderTodoRow(
      makeTodo({
        lifecycle_phase: 'build_complete',
        integration_phase: null,
        build_status: 'complete',
        deferrals_status: 'blocked',
      }),
    );

    const indicators = screen.getAllByTestId('phase-indicator');
    const blocked = indicators.find((el) => el.dataset.tag === 'deferrals:blocked');
    expect(blocked).toBeDefined();
    expect(blocked!.dataset.color).toBe('red');
  });

  it('applies in-progress color token to phase indicators with in-progress values', () => {
    renderTodoRow(makeTodo({ lifecycle_phase: 'input_assessment' }));

    const indicator = screen.getByTestId('phase-indicator');
    expect(indicator.dataset.color).toBe('gold');
  });
});
