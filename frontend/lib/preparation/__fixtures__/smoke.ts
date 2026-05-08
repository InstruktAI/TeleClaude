import type {
  ComputerInfo,
  ProjectWithTodosInfo,
  TodoInfo,
} from "@/lib/api/types";

function todo(overrides: Partial<TodoInfo> & Pick<TodoInfo, "slug">): TodoInfo {
  return {
    status: "pending",
    description: null,
    computer: "local",
    project_path: "/workspace/teleclaude",
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

export const SMOKE_COMPUTERS: readonly ComputerInfo[] = [
  { name: "local", status: "online", is_local: true },
];

export const SMOKE_PROJECTS: readonly ProjectWithTodosInfo[] = [
  {
    computer: "local",
    name: "teleclaude",
    path: "/workspace/teleclaude",
    todos: [
      todo({
        slug: "smoke-delivered-row",
        status: "delivered",
        delivered_at: "2026-04-01T10:00:00Z",
      }),
      todo({
        slug: "smoke-active-row",
        status: "active",
        lifecycle_phase: "input_assessment",
      }),
      // SC-6 alignment pin: this row carries the same phase indicator as
      // smoke-active-row but has a markedly shorter slug (8 vs 16 characters).
      // The Playwright smoke compares phase-indicator x coordinates between
      // these two rows; with the shared slug-column width the indicators must
      // start at the same horizontal offset regardless of slug length.
      todo({
        slug: "smoke-x",
        status: "active",
        lifecycle_phase: "input_assessment",
      }),
      todo({
        slug: "smoke-draft-row",
        status: "draft",
      }),
    ],
  },
];
