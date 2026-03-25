# Implementation Plan: web-tui-panels

## Overview

Add three admin views (Preparation, Config, Jobs) to the web TUI with tab
navigation, modals, toasts, and new API proxy routes. All new code follows
established patterns: React Query hooks, daemon proxy routes, context-based
keyboard bindings, and Tailwind-styled components.

The work is atomic. The tab system, views, and shared infrastructure (toasts,
modals, API routes) form one coherent behavior — independently shipping tabs
without views or views without tabs has no value. All patterns are
well-established, requirements are detailed, and estimated new code (~1200
lines) fits one builder session with clear guidance.

## Task order

Tasks are sequenced so each builds on the previous. The builder should work
top-to-bottom.

---

### Task 1: Types and key bindings foundation

**What:** Extend the type system and keyboard bindings to support the new views.

**Files modified:**
- `frontend/lib/api/types.ts` — add `JobInfo` interface
- `frontend/lib/keys/types.ts` — add `'jobs'` to `ViewContext` union
- `frontend/lib/keys/bindings.ts` — add global `4` binding, add missing
  preparation bindings (`n`, `b`, `r`, `R`, `f`, Shift+arrows), add jobs
  view bindings (`↑`/`↓`/`k`/`j`, `return`)

**Why:** All downstream tasks depend on these types and bindings. Adding them
first ensures type-safety throughout the rest of the build and prevents
retroactive binding changes that could break existing keyboard handling.

**Details:**

`JobInfo` type (derived from daemon `JobDTO` shape):
```typescript
export interface JobInfo {
  name: string;
  type: "agent" | "script";
  schedule: string | null;
  last_run: string | null;
  status: string | null;
}
```

`ViewContext` update:
```typescript
export type ViewContext = 'global' | 'sessions' | 'preparation' | 'configuration' | 'jobs'
```

New global binding:
```typescript
{ key: '4', description: 'Jobs tab', action: 'switch_to_jobs', context: 'global' }
```

Missing preparation bindings (per R2.4):
```typescript
{ key: 'n', description: 'New todo', action: 'new_todo', context: 'preparation' }
{ key: 'b', description: 'New bug', action: 'new_bug', context: 'preparation' }
{ key: 'r', description: 'Refine', action: 'refine_todo', context: 'preparation' }
{ key: 'R', shift: true, description: 'Remove', action: 'remove_todo', context: 'preparation' }
{ key: 'f', description: 'Freeze', action: 'freeze_todo', context: 'preparation' }
{ key: 'upArrow', shift: true, description: 'Move up', action: 'move_up', context: 'preparation' }
{ key: 'downArrow', shift: true, description: 'Move down', action: 'move_down', context: 'preparation' }
```

Jobs view bindings (per R4.3):
```typescript
{ key: 'upArrow', description: 'Navigate up', action: 'navigate_up', context: 'jobs' }
{ key: 'k', description: 'Navigate up', action: 'navigate_up', context: 'jobs', hidden: true }
{ key: 'downArrow', description: 'Navigate down', action: 'navigate_down', context: 'jobs' }
{ key: 'j', description: 'Navigate down', action: 'navigate_down', context: 'jobs', hidden: true }
{ key: 'return', description: 'Run job', action: 'run_job', context: 'jobs' }
```

**Verification:**
- TypeScript compiles with no errors.
- `getBindingsForContext('jobs')` returns the expected bindings.
- `findBinding('4', {}, 'global')` returns `switch_to_jobs`.
- Satisfies: R1.1 (shortcut 4), R2.4 (preparation action shortcuts), R4.3 (jobs nav).

---

### Task 2: API proxy routes

**What:** Create three new Next.js API routes proxying to daemon endpoints.

**Files created:**
- `frontend/app/api/todos/create/route.ts` — `POST` handler for todo creation
- `frontend/app/api/jobs/route.ts` — `GET` handler for job listing
- `frontend/app/api/jobs/[name]/run/route.ts` — `POST` handler for job trigger

**Why:** The views need backend data and action dispatch. Creating routes first
allows hooks and components to reference real endpoints. The proxy pattern
(auth check → daemon request → error normalization) is identical to existing
routes like `app/api/todos/route.ts` and `app/api/settings/route.ts`.

**Details:**

`POST /api/todos/create` (R7.1):
- Requires auth session (401 if missing).
- Reads `{ slug: string }` from request body.
- Validates slug matches `/^[a-z0-9]+(-[a-z0-9]+)*$/`.
- Proxies to daemon `POST /todos/create` with identity headers and slug in body.
- Returns daemon response or normalized error.

`GET /api/jobs` (R7.2):
- Requires auth session.
- Proxies to daemon `GET /jobs`.
- Returns JSON array of `JobInfo` items or error.

`POST /api/jobs/[name]/run` (R7.3):
- Requires auth session + admin role (via `requireAdmin`).
- Reads `name` from route params.
- Proxies to daemon `POST /jobs/{name}/run`.
- Returns 202 on success or error.

**Verification:**
- Test specs in `frontend/lib/__tests__/proxy-routes.test.ts` verify: auth
  gates, admin gates, daemon proxying, error passthrough, input validation.
- Satisfies: R7.1, R7.2, R7.3.

---

### Task 3: Data hooks

**What:** Create React Query hooks for new data sources.

**Files created:**
- `frontend/lib/hooks/useJobs.ts`
- `frontend/lib/hooks/usePeople.ts`

**Why:** Views consume data via hooks, matching the existing pattern
(`useTodos`, `useProjects`, `useComputers`, `useSettings`). Creating hooks
before components keeps the component layer thin.

**Details:**

Both follow the exact pattern of `useTodos` (~17 lines): a single `useQuery`
call with a cache key and fetch function.

`useJobs()` returns `UseQueryResult<JobInfo[], Error>`, cache key `["jobs"]`,
fetches from `/api/jobs`.

`usePeople()` returns `UseQueryResult<PersonInfo[], Error>`, cache key
`["people"]`, fetches from `/api/people`.

**Verification:**
- TypeScript compiles. Hooks return the correct generic type.
- Satisfies: R4.1 (jobs data source), R3.4 (people data).

---

### Task 4: Toast notification system

**What:** Add a toast notification provider and hook.

**Files created:**
- `frontend/components/ui/toaster.tsx` — toast viewport renderer
- `frontend/lib/hooks/useToast.ts` — `toast()` function provider

**Files modified:**
- `frontend/app/(chat)/layout.tsx` — mount `<Toaster />` inside provider stack

**Why:** Multiple views need transient feedback for operations (R6). The
`@radix-ui/react-toast` package is already in the lockfile. Building the toast
system before the views means every component can import and use it immediately.

**Details:**

Use the shadcn/ui toast pattern built on `@radix-ui/react-toast`:
- `Toaster` renders `ToastProvider` + `ToastViewport`.
- `useToast` hook exposes `toast({ title, description, variant })` where
  variant is `"default" | "success" | "destructive"`.
- Toasts auto-dismiss after 4 seconds, stack vertically, are non-blocking.
- Mount `<Toaster />` as the last child inside `layout.tsx`, after
  `<CacheInvalidation />`.

**Verification:**
- Calling `toast({ title: "Test" })` renders a visible notification.
- Success and destructive variants render with distinct styling.
- Satisfies: R6.1, R6.2, R6.3.

---

### Task 5: Tab navigation system

**What:** Add a tab bar and view-switching state to the main page.

**Files created:**
- `frontend/components/tabs/TabBar.tsx` — visual tab indicator
- `frontend/components/tabs/useActiveView.ts` — view state hook

**Files modified:**
- `frontend/app/(chat)/page.tsx` — integrate tab bar and conditional view rendering

**Why:** The tab system is the routing backbone for all new views (R1). The
existing page renders only the Sessions/Chat view. This task adds view state,
the visual tab indicator, and conditionally renders the active view.

**Details:**

`useActiveView` hook:
- State: `activeView` (default: `'sessions'` per R1.3).
- Exposes `setActiveView(view)` for programmatic switching.

`TabBar` component:
- Renders 4 tab buttons: Sessions (1), Preparation (2), Configuration (3),
  Jobs (4).
- Highlights active tab with a visual indicator (theme-aware bottom border
  or background).
- Tab numbers shown as small indicators for keyboard shortcut discovery.

Page integration in `ChatPageInner`:
- Add `useActiveView` state.
- Wire global keyboard shortcuts `1`–`4` to `setActiveView` using the
  binding system (listen for `switch_to_sessions`, `switch_to_preparation`,
  `switch_to_configuration`, `switch_to_jobs` actions).
- Render `<TabBar>` below the header.
- Render all four views simultaneously but show only the active one using
  `display: none` on inactive views. This preserves React state (scroll
  position, cursor, expanded nodes) without complex state-lifting (R1.2).
  - `'sessions'`: existing Chat/session content (unchanged behavior).
  - `'preparation'`: `<PreparationView />` (placeholder div until Task 6).
  - `'configuration'`: `<ConfigView />` (placeholder div until Task 8).
  - `'jobs'`: `<JobsView />` (placeholder div until Task 9).

**Verification:**
- Tab bar renders 4 tabs with correct labels.
- Clicking a tab switches the visible view.
- Pressing `1`–`4` switches tabs via keyboard.
- Switching away and back preserves view state (R1.2).
- Sessions is the default active tab (R1.3).
- Satisfies: R1.1, R1.2, R1.3.

---

### Task 6: Preparation view — tree and navigation

**What:** Build the hierarchical tree component for the Preparation view.

**Files created:**
- `frontend/components/preparation/PreparationView.tsx` — main view component
- `frontend/components/preparation/TreeNode.tsx` — recursive tree node renderer
- `frontend/components/preparation/useTreeState.ts` — tree expand/collapse and
  cursor state management

**Why:** The Preparation view is the most complex new view. The tree structure
(Computer → Project → Todo → File) requires recursive rendering, cursor
tracking across heterogeneous node types, and expand/collapse state. Isolating
tree state into a custom hook keeps the component layer focused on rendering.

**Details:**

Tree node model (internal to the preparation module):
```typescript
type TreeNodeType = 'computer' | 'project' | 'todo' | 'file';
interface TreeNode {
  id: string;
  type: TreeNodeType;
  label: string;
  depth: number;
  children?: TreeNode[];
  data: ComputerInfo | ProjectInfo | TodoInfo | string;
}
```

`useTreeState` hook:
- Builds tree from `useComputers()`, `useProjects()`, and `useTodos()` data.
  Groups todos under their project (matching `todo.project_path` to
  `project.path` and `todo.computer` to `project.computer`), projects under
  their computer.
- Tracks `expandedNodes: Set<string>` and `cursorIndex: number` into the
  flattened visible-node list.
- Provides: `toggle(id)`, `expandAll()`, `collapseAll()`, `moveCursor(delta)`,
  `getCursorNode()`.

`TreeNode` component renders per node type (R2.2):
- Computer: name + status indicator.
- Project: name.
- Todo: slug, status badge (pending/icebox/delivered), compact phase tags
  (B/R/DOR/DEF/F derived from `build_status`, `review_status`, `dor_score`,
  `deferrals_status`, `findings_count`), DOR score, deferrals count.
- File: filename, displayed alphabetically under parent todo.
- Indentation by depth. Expand/collapse chevron for container nodes.

`PreparationView` wires keyboard bindings from `preparation` context (R2.3):
- `navigate_up`/`navigate_down`: move cursor.
- `collapse_or_back` (←): collapse or move to parent.
- `drill_down` (→): expand.
- `open_editor` (Enter): toggle on containers, open file on leaves.
- `preview_file` (Space): show file content in inline preview area.
- `expand_all`/`collapse_all` (+/-): global expand/collapse.

Cursor row has distinct background. Auto-scrolls to keep cursor visible.

Real-time updates (R2.5): tree re-derives from hook data. WebSocket events
invalidate `["todos"]` cache via existing `useCacheInvalidation`. Cursor
position preserved by node ID, not index.

**Verification:**
- Tree renders hierarchy: computers → projects → todos → files.
- Keyboard navigation moves cursor, expand/collapse works.
- Todo nodes display status badge, phase tags, DOR score, deferrals count.
- Data changes via WebSocket reflect without manual refresh.
- Satisfies: R2.1, R2.2, R2.3, R2.5.

---

### Task 7: Preparation view — actions and modals

**What:** Wire action shortcuts and create modals for the Preparation view.

**Files created:**
- `frontend/components/preparation/NewTodoModal.tsx`
- `frontend/components/preparation/NewBugModal.tsx`

**Files modified:**
- `frontend/components/preparation/PreparationView.tsx` — add action handlers

**Why:** Separating actions from tree navigation keeps Task 6 focused on
rendering and Task 7 focused on side-effects and modal forms.

**Details:**

Action handlers in `PreparationView` (R2.4):
- `new_todo` (n): opens `NewTodoModal`.
- `new_bug` (b): opens `NewBugModal`.
- `prepare_todo` (p): POST to daemon's `POST /todos/{slug}/prepare` via a new
  proxy route `app/api/todos/[slug]/prepare/route.ts` (auth + daemon proxy
  pattern). Toast on success/error.
- `start_work` (s): POST to daemon's `/todos/{slug}/work` via similar route.
  Toast feedback.
- `refine_todo` (r): POST to daemon's `/todos/{slug}/refine`. Toast feedback.
- `remove_todo` (R): disabled — toast "Operation unavailable (no daemon endpoint)".
- `freeze_todo` (f): disabled — same.
- `move_up`/`move_down` (Shift+↑/↓): disabled — same.

Additional proxy routes needed (builder creates alongside actions):
- `frontend/app/api/todos/[slug]/prepare/route.ts`
- `frontend/app/api/todos/[slug]/work/route.ts`
- `frontend/app/api/todos/[slug]/refine/route.ts`

All follow the same pattern: auth check, proxy POST to daemon, return response.

`NewTodoModal` (R5.1):
- Slug input validated against `/^[a-z0-9]+(-[a-z0-9]+)*$/`.
- Inline validation feedback below input.
- Submit POSTs to `/api/todos/create` (Task 2 route).
- On success: close modal, toast "Todo created", invalidate `["todos"]` query.
- `Esc` closes, `Enter` submits (R5.3).
- Follows `NewSessionDialog` modal pattern: fixed overlay, centered card, form.

`NewBugModal` (R5.2):
- Same structure as NewTodoModal.
- Same slug validation.
- The daemon has no dedicated bug-report REST endpoint. If `POST /todos/create`
  supports a type parameter, use it. Otherwise the modal creates a todo with
  `bug-` slug prefix convention and toasts accordingly. If no viable mechanism
  exists, show "Bug reporting available via CLI (`telec bugs report`)" message.

**Verification:**
- `n` opens New Todo modal, validates slug, submit creates via API.
- `p`/`s`/`r` dispatch to daemon with toast feedback.
- `R`/`f`/Shift+arrows show "unavailable" toast.
- `Esc` closes modals, `Enter` submits.
- Satisfies: R2.4, R5.1, R5.2, R5.3, R6.1.

---

### Task 8: Configuration view

**What:** Build the Configuration view with 5 subtabs and admin gating.

**Files created:**
- `frontend/components/configuration/ConfigView.tsx` — main view with subtab nav
- `frontend/components/configuration/AdaptersTab.tsx`
- `frontend/components/configuration/PeopleTab.tsx`
- `frontend/components/configuration/NotificationsTab.tsx`
- `frontend/components/configuration/EnvironmentTab.tsx`
- `frontend/components/configuration/ValidateTab.tsx`

**Why:** The Configuration view is admin-restricted with its own subtab
navigation. Each subtab displays data from a different source. Self-contained
component tree with clear subtab boundaries makes each independently testable.

**Details:**

`ConfigView` (R3.1, R3.2):
- Admin gate: use client-side session to check role. Non-admin users see
  "Admin access required" message (not a redirect — the tab remains navigable
  but gated).
- Subtab state: `activeSubtab` (0-4), default 0 (Adapters).
- Subtab bar: 5 buttons. Active subtab highlighted.
- Keyboard bindings from `configuration` context:
  - `prev_subtab` (←/h), `next_subtab` (→/l): cycle subtabs.
  - `next_tab` (Tab), `prev_tab` (Shift+Tab): cycle subtabs.
  - `navigate_up`/`navigate_down` (↑↓/kj): items within subtab.
  - `select_item` (Enter): toggle focused item.

`AdaptersTab` (R3.3):
- Read-only. Fetches via `useSettings()`. Renders adapter config as key-value
  list. Shows "Read-only — edit via CLI" indicator.

`PeopleTab` (R3.4):
- Fetches via `usePeople()` hook. Renders list: name, email, role per
  `PersonInfo`. Read-only.

`NotificationsTab` (R3.5):
- Read-only. Shows notification preferences from settings if available,
  otherwise "Notification config — edit via CLI" placeholder.

`EnvironmentTab` (R3.6):
- Displays env vars as rows. Values masked by default (`••••••`). Click/Enter
  reveals value. Read-only. If daemon provides no env-var data, shows placeholder.

`ValidateTab` (R3.7):
- Placeholder: "Config validation available via CLI (`telec config validate`)".
  If builder discovers a daemon validation endpoint, wire it.

**Verification:**
- Non-admin users see access-denied in Config tab.
- Admin sees 5 subtabs with data.
- Tab/Shift+Tab and ←/→ cycle subtabs.
- ↑/↓ navigates items within subtabs.
- People tab lists people. Environment masks values.
- Satisfies: R3.1–R3.8.

---

### Task 9: Jobs view

**What:** Build the Jobs view with list rendering and trigger capability.

**Files created:**
- `frontend/components/jobs/JobsView.tsx`

**Why:** Simplest new view — a flat list with two sections. Depends on
`useJobs` (Task 3) and toast system (Task 4).

**Details:**

`JobsView` component:
- Fetches via `useJobs()`.
- Splits into "Scheduled Jobs" (`schedule !== null`) and "One-shot Jobs"
  (`schedule === null`) sections (R4.2).
- Row: name, schedule expression or "one-shot", type badge (agent/script),
  last run timestamp (relative), status.
- Cursor navigation: `cursorIndex` state, `navigate_up`/`navigate_down` from
  jobs context bindings.
- Enter (`run_job`): POST to `/api/jobs/{name}/run`, toast success/error (R4.4).
- Loading/error/empty states.

**Verification:**
- Jobs list renders with scheduled/one-shot grouping.
- Cursor moves between rows. Enter triggers and toasts.
- Satisfies: R4.1, R4.2, R4.3, R4.4.

---

### Task 10: Theme compatibility pass

**What:** Verify all new components render correctly in dark and light modes.

**Files modified:**
- All new component files as needed.

**Why:** R8.1 requires both themes. The existing codebase uses theme-aware
Tailwind classes (`bg-card`, `text-muted-foreground`, `border`, etc.). This
task is a verification pass to catch any hardcoded colors.

**Details:**
- Audit new components for hardcoded `text-gray-*`, `bg-gray-*`, etc.
- Replace with theme-aware equivalents.
- Status badges use semantic colors that work in both themes.

**Verification:**
- Toggle dark/light mode. All views render with correct contrast.
- Satisfies: R8.1.

---

### Task 11: Proxy route tests

**What:** Extend `frontend/lib/__tests__/proxy-routes.test.ts` with tests for
the new API routes.

**Files modified:**
- `frontend/lib/__tests__/proxy-routes.test.ts`

**Why:** Existing test file covers GET /api/computers, settings, sessions.
New routes follow identical patterns and need the same coverage.

**Details:**

New describe blocks following existing mock pattern (`vi.mock("@/auth")`,
`vi.mock("@/lib/proxy/daemon-client")`, `makeSession()`, `makeRequest()`):

`POST /api/todos/create`:
- 401 if unauthenticated.
- 400 if slug missing or invalid.
- Proxies valid request to daemon.
- Passes through daemon errors.
- 503 when daemon unreachable.

`GET /api/jobs`:
- 401 if unauthenticated.
- Proxies to daemon when authenticated.
- Passes through daemon errors.

`POST /api/jobs/[name]/run`:
- 401 if unauthenticated.
- 403 for non-admin.
- Admin triggers job (202 response).

**Verification:**
- `pnpm test:cli` passes with all new cases.
- Satisfies: DoD testing gates.

---

## Requirement-to-task traceability

| Requirement | Task(s)        |
|-------------|----------------|
| R1.1        | T1, T5         |
| R1.2        | T5             |
| R1.3        | T5             |
| R2.1        | T6             |
| R2.2        | T6             |
| R2.3        | T6             |
| R2.4        | T1, T7         |
| R2.5        | T6             |
| R3.1–R3.8   | T3, T8         |
| R4.1        | T2, T3         |
| R4.2        | T9             |
| R4.3        | T1, T9         |
| R4.4        | T4, T9         |
| R5.1        | T2, T7         |
| R5.2        | T7             |
| R5.3        | T7             |
| R6.1–R6.3   | T4, T7, T9     |
| R7.1        | T2             |
| R7.2        | T2             |
| R7.3        | T2             |
| R7.4        | — (documented)  |
| R8.1        | T10            |

## Notes for the builder

1. **Todo action proxy routes.** R2.4 actions (prepare, work, refine) need
   routes at `app/api/todos/[slug]/prepare/route.ts` (and work, refine).
   These are auth + daemon proxy, same pattern as existing routes.

2. **Bug modal.** If daemon `POST /todos/create` has no type parameter for
   bugs, use slug prefix convention or show CLI-only message.

3. **Environment subtab.** Daemon settings API returns `{ tts: {...} }` only.
   If env vars unavailable, show placeholder.

4. **View preservation.** Use `display: none` on inactive views to preserve
   React state (R1.2), not conditional unmounting.

5. **Modal pattern.** Follow `NewSessionDialog` (hand-rolled overlay + card),
   not a new shadcn dialog component, for consistency.

6. **Toast package.** `@radix-ui/react-toast` is in the lockfile. Build the
   toast system on it.
