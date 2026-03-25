# Requirements: web-tui-panels

## Goal

Add three admin views (Preparation, Config, Jobs) to the web TUI, building on the
existing sidebar+main layout. Each view is accessible via tab navigation and
keyboard shortcuts. Accompanying modals and toast notifications provide CRUD
operations and user feedback.

## Scope

### In scope

- Tab navigation system: switching between Sessions (existing), Preparation, Config,
  and Jobs views via global keyboard shortcuts and a visible tab indicator.
- Preparation view: hierarchical tree (Computer → Project → Todo → Files) with
  keyboard navigation and action dispatching.
- Config view: admin-gated configuration display with 5 subtabs (Adapters, People,
  Notifications, Environment, Validate). Read-only display for all subtabs; editing
  limited to operations that have daemon API support.
- Jobs view: list of scheduled and one-shot jobs with trigger capability.
- Modals for creating todos and reporting bugs.
- Toast notification system for operation feedback.
- Frontend API routes proxying to existing daemon endpoints.

### Out of scope

- New daemon API endpoints. The frontend proxies to daemon endpoints; operations
  requiring daemon endpoints that do not exist are displayed read-only or stubbed.
- New project creation (no daemon endpoint for project scaffolding).
- People CRUD (daemon has read-only people listing; no write endpoint).
- Full config editing for adapters, notifications, and environment (daemon settings
  endpoint handles runtime settings only; YAML config mutation endpoints do not exist).
- Todo removal (daemon has no delete endpoint for todos).
- Roadmap reordering (daemon has no move/freeze/unfreeze endpoints exposed as REST).
- Changes to the chat/sessions view beyond integrating it into the tab system.

## Requirements

### R1: Tab navigation

The main content area must support four views: Sessions, Preparation, Configuration,
Jobs. [inferred] A visual tab bar indicating the active view must be visible in the
main content area.

- **R1.1**: Global keyboard shortcuts `1`, `2`, `3`, `4` switch between the four
  views. Shortcuts `1`–`3` use the bindings already defined in
  `frontend/lib/keys/bindings.ts`. [inferred] Shortcut `4` for Jobs needs to be
  added to the global context.
- **R1.2**: Tab switching preserves each view's internal state (scroll position,
  selected item, expanded nodes). Switching away and back must not reset the view.
- **R1.3**: The Sessions view remains the default active tab on initial load.

### R2: Preparation view

A hierarchical tree displaying Computer → Project → Todo → File nodes with keyboard
navigation and action dispatching.

- **R2.1**: **Data shape.** The tree groups `TodoInfo` items under their
  `ProjectInfo` parents, which are grouped under `ComputerInfo` headers. Data comes
  from the existing `useTodos`, `useProjects`, and `useComputers` hooks.
  `ProjectWithTodosInfo` from the daemon WebSocket `preparation_initial` event
  provides the pre-grouped shape.
- **R2.2**: **Tree rendering.** Each level is expandable/collapsible:
  - Computer nodes: computer name and status.
  - Project nodes: project name.
  - Todo nodes: slug, status badge (pending/icebox/delivered), compact phase tags
    (B/R/DOR/DEF/F derived from `build_status`, `review_status`, `dor_score`,
    `deferrals_status`, `findings_count`), DOR score, deferrals count.
  - File nodes: filenames from `TodoInfo.files`, displayed alphabetically under
    their parent todo when expanded.
- **R2.3**: **Keyboard navigation.** Bindings from the `preparation` context in
  `frontend/lib/keys/bindings.ts` must be wired:
  - `↑`/`↓` (or `k`/`j`): move cursor between visible nodes.
  - `←`/`→`: collapse/expand current node.
  - `Enter`: toggle expand/collapse on container nodes; open file on file nodes.
  - `Space`: preview file content. [inferred] Preview displays file content inline
    or in a side panel — exact presentation is a builder decision.
  - `+`/`-`: expand/collapse all nodes globally.
- **R2.4**: **Action shortcuts.** The following key actions dispatch operations
  through the daemon API via frontend proxy routes:
  - `n`: open New Todo modal (see R5.1).
  - `b`: open New Bug modal (see R5.2).
  - `p`: dispatch prepare for the focused todo (POST to daemon's `/todos/prepare`).
  - `s`: dispatch work/start for the focused todo (POST to daemon's `/todos/work`).
  - `r`: dispatch refine/input-refinement for the focused todo.
  - `R` (shift): remove the focused todo. [inferred] Since the daemon lacks a
    delete endpoint, this action should be visually present but disabled with an
    indication that the operation is unavailable.
  - `f`: freeze the focused todo. [inferred] Same constraint as R above — daemon
    lacks a freeze REST endpoint; action is disabled.
  - `Shift+↑`/`Shift+↓`: move the focused todo in the roadmap. [inferred] Same
    constraint — daemon lacks a move endpoint; action is disabled.
- **R2.5**: **Real-time updates.** The WebSocket cache invalidation system already
  handles `todos_updated`, `todo_created`, and `todo_removed` events. The tree must
  reflect these updates without manual refresh.

### R3: Configuration view

An admin-restricted view with 5 subtabs for configuration display and limited editing.

- **R3.1**: **Auth gating.** The Configuration view is accessible only to users with
  the `admin` role. Non-admin users see a clear access-denied state or the tab is
  hidden/disabled. The existing `requireAdmin` guard pattern applies to all write
  operations.
- **R3.2**: **Subtab navigation.** 5 subtabs: Adapters, People, Notifications,
  Environment, Validate. Keyboard shortcuts `Tab`/`Shift+Tab` cycle between subtabs.
  `←`/`→` (or `h`/`l`) also navigate between subtabs (matching the `configuration`
  key context bindings).
- **R3.3**: **Adapters subtab.** Displays adapter configuration. [inferred] Read-only
  display of adapter settings since the daemon settings endpoint only covers runtime
  settings (tts), not adapter configuration.
- **R3.4**: **People subtab.** Lists people from the daemon's `GET /api/people`
  endpoint (name, email, role). [inferred] Read-only display since the daemon has no
  write endpoint for people.
- **R3.5**: **Notifications subtab.** Displays notification preferences. [inferred]
  Read-only since no daemon write endpoint exists for notification config.
- **R3.6**: **Environment subtab.** Displays environment variables. Values are masked
  by default; clicking/selecting reveals the value. [inferred] Read-only display; the
  daemon has no endpoint for setting environment variables.
- **R3.7**: **Validate subtab.** Triggers config validation and displays results.
  The existing `telec config validate` function provides validation; [inferred] the
  validation may need a daemon endpoint to be useful from the web, or it displays
  a placeholder indicating CLI-only availability.
- **R3.8**: **Keyboard navigation within subtabs.** `↑`/`↓` (or `k`/`j`) navigates
  items within the active subtab. `Enter` selects or toggles the focused item.
  `Esc` cancels editing.

### R4: Jobs view

A list of scheduled and one-shot jobs with status display and trigger capability.

- **R4.1**: **Data source.** Jobs are fetched from the daemon's `GET /jobs` endpoint
  via a new frontend proxy route. The daemon returns `JobDTO` items with name, type
  (agent/script), schedule, last_run, and status.
- **R4.2**: **List rendering.** Two sections: "Scheduled Jobs" (jobs with a schedule
  expression) and "One-shot Jobs" (jobs without a schedule). Each row shows: name,
  schedule expression or "one-shot", type (agent/script), last run timestamp, status.
- **R4.3**: **Keyboard navigation.** `↑`/`↓` moves the cursor. `Enter` triggers the
  selected job by POSTing to the daemon's `POST /jobs/{name}/run` endpoint.
- **R4.4**: **Trigger feedback.** After triggering a job, a toast notification
  confirms the dispatch (see R6). The daemon returns 202 Accepted with the job name.

### R5: Modals

Modal dialogs for creating work items.

- **R5.1**: **New Todo modal.** Triggered by `n` in the Preparation view. Contains a
  slug input validated to allow only lowercase letters, numbers, and hyphens.
  Submitting POSTs to the daemon's `POST /todos/create` endpoint via a new frontend
  proxy route.
- **R5.2**: **New Bug modal.** Triggered by `b` in the Preparation view. Contains a
  slug input with the same validation as R5.1. [inferred] Submits via the same or a
  similar creation flow — the daemon has no separate bug-report REST endpoint, so the
  exact mechanism depends on daemon capabilities.
- **R5.3**: **Modal interaction.** `Esc` closes any open modal. `Enter` submits the
  form. Input validation feedback is displayed inline.

### R6: Toast notifications

Transient user feedback for operations.

- **R6.1**: Toast messages appear for: todo created, bug created, prepare dispatched,
  work dispatched, refine dispatched, job triggered, and any operation errors.
- **R6.2**: Toasts are non-blocking, auto-dismiss after a reasonable duration, and
  stack if multiple appear in quick succession.
- **R6.3**: [inferred] The toast system must support both success and error variants
  to distinguish successful dispatches from failures.

### R7: Frontend API proxy routes

New Next.js API routes that proxy to existing daemon endpoints.

- **R7.1**: `POST /api/todos` — proxies to daemon's `POST /todos/create`. Requires
  authentication. Accepts `slug` in the request body.
- **R7.2**: `GET /api/jobs` — proxies to daemon's `GET /jobs`. Requires authentication.
- **R7.3**: `POST /api/jobs/[name]/run` — proxies to daemon's `POST /jobs/{name}/run`.
  Requires authentication and admin authorization.
- **R7.4**: The existing `PATCH /api/settings` route's allowlist (currently `tts` only)
  should be documented as a known limitation. [inferred] Expanding it requires
  understanding what the daemon's `RuntimeSettings.parse_patch` accepts beyond `tts`.

### R8: Theme compatibility

- **R8.1**: All new views and components must support both dark and light mode using
  the existing theme infrastructure (ThemeProvider, CSS variables, Tailwind classes).

## Constraints

- Stack: Next.js 15, React 19, TypeScript, Tailwind 4.
- Component library: shadcn/ui exclusively for UI primitives.
- All data fetching goes through the daemon proxy pattern (frontend API route →
  daemon Unix socket).
- Real-time updates via the existing WebSocket + React Query cache invalidation.
- Keyboard bindings use the context-based system in `frontend/lib/keys/`.

## Risks

- **Scope size.** Three distinct views, each with its own component tree, keyboard
  wiring, and interactions. The draft phase should evaluate whether splitting into
  separate todos (e.g., per-tab) is warranted based on estimated lines of change
  and session context limits.
- **Daemon API gaps.** Several operations mentioned in the input (todo remove, project
  create, people CRUD, full config editing, roadmap reorder, freeze) lack daemon REST
  endpoints. These are scoped as read-only or disabled in this todo. Future daemon
  endpoint work would unlock write capability.
- **Bug report modal.** The daemon has no dedicated bug-report REST endpoint. The CLI
  `telec bugs report` scaffolds files and dispatches via the daemon's session
  infrastructure. The exact frontend mechanism for bug creation needs builder
  investigation during implementation.

## Success criteria

- [ ] Tab navigation switches between four views via keyboard and visual indicator.
- [ ] Preparation view renders a hierarchical tree with correct data grouping.
- [ ] Preparation keyboard navigation (cursor, expand/collapse, preview) works.
- [ ] Preparation action shortcuts dispatch to daemon for supported operations.
- [ ] Unsupported preparation actions (remove, freeze, move) are visibly disabled.
- [ ] Config view is admin-gated and renders 5 subtabs with read-only data.
- [ ] Config subtab navigation works via keyboard.
- [ ] Jobs view lists jobs from daemon and allows triggering via Enter.
- [ ] New Todo modal validates slug input and creates via daemon API.
- [ ] Toast notifications appear for key operations.
- [ ] All new API proxy routes work with authentication.
- [ ] Dark and light mode render correctly across all new views.
- [ ] WebSocket-driven data updates reflect in all views without manual refresh.
