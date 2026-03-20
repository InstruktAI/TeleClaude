# Requirements: web-tui-parity

## Goal

Port the full TUI admin experience to the web frontend. The web interface must be a complete administrative environment — not a consumer chat app. Admins working remotely need the same hierarchical views, real-time activity, keyboard navigation, context-sensitive footer, todo lifecycle management, bug reporting, job execution, and config editing that TUI users have locally. The target is full functional parity across all four TUI tabs.

## Background

**Current web state:** Flat `w-64` session list, single chat view, no tabs, no keyboard shortcuts, no toasts, no todos view, no jobs view, no config editing, only 3 shadcn/ui components installed.

**TUI has:** 4 tabs (Sessions, Preparation, Jobs, Config), hierarchical trees, rich keyboard navigation across all views, context-sensitive footer, activity highlighting, full todo lifecycle (new/prepare/work/refine/freeze/remove), bug reporting, job execution, config editing with 5 subtabs.

---

## Scope

### In scope

#### 1. Layout — shell and panel structure

- Two-panel layout: **left panel = 40% width**, right panel = 60%.
- Left panel contains: top tab bar (4 tabs) + view content + bottom footer.
- Right panel: fixed, shows home page when no session selected; chat view when a session is active.
- No preview pane, no sticky pane, no dynamic layout splitting.

#### 2. Component library — shadcn/ui expansion

**Tab bar:** shadcn `Tabs` (Radix UI Tabs, correct ARIA roles). Top of left panel; switching tabs replaces tree content. Four tabs: Sessions, Preparation, Jobs, Config.

**Tree panels:** Custom `TreeNode` system built on shadcn `Collapsible` (Radix UI Collapsible) for expand/collapse with animation. `TreePanel` renders a recursive node hierarchy. A `useTreeNavigation` hook owns `↑↓/Enter/←→` keyboard logic via a flat ref array across all visible nodes. All tree visual specialization (agent colors, phase badges, depth indentation, highlight states) lives in purpose-built node components (`ComputerNode`, `ProjectNode`, `SessionNode`, `TodoNode`, `FileNode`).

**Global keyboard shortcuts:** Single `useAdminKeyboard` hook, mounted at the left panel root, guards against `input`/`textarea` focus before firing. No external hotkey library.

**shadcn components to install** (`npx shadcn add <name>`):

- `dialog` — replace manual overlay in `NewSessionDialog` and all future modals
- `tabs` — tab bar for the 4 main views
- `collapsible` — base primitive for `TreeNode` expand/collapse
- `tooltip` — keyboard shortcut hints on hover over footer keys
- `badge` — status badges, session index display, phase tags
- `select` — dropdowns in modals and config
- `input` — text inputs in modals and config
- `label` — form labels
- `radio-group` — agent and mode selectors in modals
- `separator` — visual dividers in tree headers
- `scroll-area` — scrollable tree panels
- `sonner` — toast notifications (shadcn-adopted; `npx shadcn add sonner`)
- `keyboard` (custom, not from registry) — `<kbd>` styled component for footer key display

#### 3. Sessions tab — full parity

**Layout:**

- Left panel shows hierarchical tree: Computer → Project → Session, AI-to-AI child sessions nest one level deeper.
- Computer header: icon, name, online/offline status badge, total session count. Thick separator below.
- Project header: icon, project name, truncated path, session count. Thin separator.
- Session rows: `[N]` index badge (e.g., `[1]`, `[3.2]`), agent icon with agent color (claude=cyan, gemini=magenta, codex=yellow, shell=neutral), thinking mode, title (truncated), subdir slug.
- Expand/collapse session row with `←→` to show detail lines: session_id, native_id (if present), `last_input_at` + truncated last input, `last_output_summary_at` + truncated summary.
- Orphaned sessions (no project path) grouped under synthetic "—" project per computer.

**Activity highlighting — full row, not just dot:**

- User sends message → entire session row highlights yellow/orange. Persists until agent responds.
- Agent turn complete (`agent_output_stop`) → row highlights green/blue. Persists until user selects the session.
- Tool executing (`agent_output_update`) → row highlights blue for duration of tool.
- Selecting a session clears its output highlight.
- Event source: `agent_activity` WebSocket event; discriminate by `event.type` field (`user_prompt_submit`, `agent_output_update`, `agent_output_stop`).

**Keyboard navigation (active when tree panel has focus):**

- `↑/↓` — move cursor, auto-scroll to keep cursor visible
- `Enter` — on session: open in right panel + focus chat input; on project header: open new session modal pre-filled with that project
- `←/→` — collapse/expand session row detail lines
- `+/-` — expand all / collapse all
- `n` — open new session modal
- `R` — restart selected session (toast: "Session restart dispatched")
- `k` — kill selected session (confirm modal → toast: "Session ended")

**Session actions — right panel header:**

- Existing "End" button remains.
- Add "Restart" button (calls `/api/sessions/:id/agent-restart`).

#### 4. Preparation tab — full parity

**Layout:**

- Hierarchical tree: Computer → Project → Todo → Files (nested, expandable).
- Computer headers (from configured trusted dirs / computers).
- Project headers per computer.
- Todo rows showing:
  - Slug
  - Status badge: `pending`, `icebox`, `delivered`
  - Compact phase tags: `B` (build), `R` (review), `DOR`, `DEF`, `F` (finalize)
  - DOR score if available
  - Deferrals count if >0
- File rows nested under expanded todos (all non-hidden files under `todos/{slug}/`, alphabetically).

**Keyboard navigation:**

- `↑/↓` — cursor
- `←/→` — collapse/expand todo (shows/hides file list)
- `Enter` — toggle expand/collapse on todo; open file viewer on file row
- `Space` — preview file (view-only pane or modal)
- `+/-` — expand/collapse all todos
- `n` — new todo modal (slug input, validates format)
- `b` — new bug modal (slug input)
- `p` — prepare (dispatches `/next-prepare {slug}` session, toast: "Prepare session started")
- `s` — start work (dispatches `/next-work {slug}` session, gated on DOR readiness, toast: "Work session started")
- `r` — refine (dispatches `/next-refine-input {slug}` session)
- `R` — remove todo (confirm modal → toast: "Todo removed")
- `f` — freeze to icebox (confirm modal → toast: "Todo frozen")
- `Shift+↑/↓` — move todo up/down in roadmap order

**API:** `/api/todos` already exists. Wiring to existing endpoint.

#### 5. Jobs tab — full parity

**Layout:**

- Two sections: "Scheduled Jobs" and "One-shot Jobs".
- Each job row: name, schedule expression or "one-shot", script/command.
- Cursor-navigable list.

**Keyboard navigation:**

- `↑/↓` — cursor
- `Enter` — run selected job (POST to `/api/jobs/:name/run`, toast: "Job dispatched")

**API:** `/api/jobs` does not exist yet — needs daemon endpoint or stub with mock data. Wire when available; stub in UI until then.

#### 6. Config tab — full parity

**Subtabs (horizontal tab bar within left panel):**

1. **Adapters** — enable/disable and edit per-adapter fields (Telegram, Discord, WhatsApp, etc.)
2. **People** — list people, add/edit (name, email, role)
3. **Notifications** — notification preferences
4. **Environment** — list and edit environment variables (masked by default, reveal on click)
5. **Validate** — run config validation, show status per env var

**Keyboard navigation:**

- `↑/↓` — navigate within subtab
- `Tab/Shift+Tab` — cycle through subtabs
- `←/→` — cycle enum values on enum fields
- `Enter` — select/edit field
- `Esc` — cancel edit
- `g` — toggle guided mode
- `v` — run validation (toast result)
- `r` — refresh config from disk

**API:** `/api/settings` GET/PATCH exists.

#### 7. Modals — all using shadcn Dialog primitive

Migrate `NewSessionDialog` from custom overlay to shadcn `Dialog`. All new modals also use `Dialog`.

**New Session Modal** (trigger: `n` in Sessions tab, Enter on project header):

- Computer (select, pre-filled when triggered from project context)
- Project (select, pre-filled when triggered from project context)
- Agent (radio: claude / gemini / codex, with availability indicator ✔ / ✘ / ~)
- Thinking mode (radio: fast / med / slow)
- Title (text input, optional)
- Initial message (textarea, optional)
- Session ID (text input, optional, for revive/resume)

**New Todo Modal** (trigger: `n` in Preparation tab):

- Slug (text input, validated: lowercase, numbers, hyphens only)

**New Bug Modal** (trigger: `b` in Preparation tab):

- Slug (text input, same validation)

**Confirm Modal** (trigger: `k`, `R`, `f` destructive actions):

- Title + message
- Yes / No / Esc

**New Project Modal** (trigger: `n` on computer header in Sessions/Preparation):

- Name (text input)
- Description (text input, optional)
- Path (text input, validated: must be an existing directory)

#### 8. Footer — context-sensitive keybinding display

- Fixed at bottom of left panel, always visible.
- Shows available keyboard shortcuts for the current context (active tab + selected item type).
- Each key: `<kbd>` styled element + description label.
- Active/primary action highlighted (e.g., bold or accent color).
- Updates dynamically as cursor moves between computer/project/session/todo/file nodes.

**Sessions tab footer (on session):** `↑↓` Nav · `←→` Fold · `+−` All · `Enter` Focus · `n` New · `R` Restart · `k` Kill
**Sessions tab footer (on project header):** `↑↓` Nav · `Enter` New Session · `n` New Session
**Preparation tab footer (on todo):** `↑↓` Nav · `←→` Fold · `n` Todo · `b` Bug · `p` Prep · `s` Start · `r` Refine · `R` Remove · `f` Freeze · `Shift+↑↓` Move
**Preparation tab footer (on file):** `↑↓` Nav · `Enter` View · `Space` Preview
**Jobs tab footer:** `↑↓` Nav · `Enter` Run
**Config tab footer:** `↑↓` Nav · `Tab` Subtabs · `Enter` Edit · `Esc` Cancel · `g` Guided · `v` Validate · `r` Refresh

#### 9. Keyboard infrastructure

- All tree navigation shortcuts fire only when the left panel has focus (`tabIndex` on panel root, `onKeyDown` handler).
- Global shortcuts (`n`, `R`, `k`, `b`, `p`, `s`, `r`, `f`) guarded: skip when `event.target` is `HTMLInputElement` or `HTMLTextAreaElement`.
- Tab switching: `1`–`4` number keys switch tabs (guarded same as above).
- `Esc` closes active modal or clears selection.
- All shortcuts should have tooltip hints (via shadcn `Tooltip`) on hover over footer keys.

#### 10. Toast notifications

- Add `sonner` package. Add `<Toaster />` to root layout.
- Fire toasts for: session created, session restarted, session ended, todo created, bug created, prepare dispatched, work dispatched, refine dispatched, todo removed, todo frozen, todo moved, job dispatched, config saved, config validated.
- Long-running dispatches (prepare, work, refine, jobs): "dispatched" toast only — no spinner, no polling.
- Destructive actions: "ended" / "removed" / "frozen" toast on confirm.

### Out of scope

- TTS voice toggle and chiptunes music (TUI-only hardware features)
- UFO/car animations
- Sticky sessions / tmux pane pinning
- Mobile / responsive below 1280px viewport
- Full file editor within the web UI (file preview is read-only modal/pane)
- Jobs API daemon endpoint (stub UI until endpoint exists)
- TypeScript daemon migration (parallel track)

---

## Success Criteria

- [ ] Left panel is 40% viewport width with tab bar, scrollable tree content, and fixed footer
- [ ] Right panel shows home page or chat view (unchanged behavior)
- [ ] Sessions tab: hierarchical tree renders Computer → Project → Session with correct headers and depth-indexed rows
- [ ] Sessions tab: full-row activity highlight (yellow input, green output, blue tool) fires from `agent_activity` WebSocket events
- [ ] Sessions tab: `↑↓` cursor, `Enter` selects into right panel, `←→` expand/collapse rows, `n` opens modal, `R` restarts, `k` kills with confirm
- [ ] Sessions tab: Enter on project header opens new session modal pre-filled with that project
- [ ] Preparation tab: Computer → Project → Todo → Files tree renders with slug, status badge, phase tags
- [ ] Preparation tab: `n`/`b` open respective create modals; `p`/`s`/`r` dispatch sessions; `R`/`f` confirm then act; `Shift+↑↓` reorders
- [ ] Jobs tab: scheduled and one-shot sections; Enter runs job
- [ ] Config tab: 5 subtabs; fields editable; validation runs; guided mode toggles
- [ ] All modals use shadcn Dialog primitive with proper focus management and Esc handling
- [ ] New Session modal has: computer, project, agent (with availability), mode, title, message, session ID fields
- [ ] Footer renders context-sensitive keyboard shortcuts that update as cursor moves
- [ ] Toasts fire for all dispatched and completed actions via Sonner
- [ ] Number keys `1`–`4` switch tabs when tree panel has focus
- [ ] Keyboard shortcuts do not fire when chat input is focused

---

## Constraints

- Stack: Next.js 15, React 19, TypeScript, Tailwind 4 — no new frameworks
- Component library: shadcn/ui exclusively — install additional components from the existing registry
- Toast: `sonner` (shadcn/ui adopted; `npx shadcn add sonner`)
- Must use existing daemon API routes; Jobs tab stubs until `/api/jobs` exists
- Agent colors must match existing design tokens (`/lib/theme/tokens.css`)
- Dark and light mode throughout
- Must not break existing chat/message view

## Risks

- Keyboard focus management in browser requires careful `tabIndex` and `focus()` discipline to avoid clashing with browser shortcuts (`n`, `b`, `f`, `r` are common)
- Jobs API endpoint does not exist — stub required in the UI layer
- Config editing over the web needs careful auth gating (admin-only)
- Large session/todo trees may need virtualization (`@tanstack/virtual` or similar) if counts exceed ~200 nodes
