# web-tui-shell — Requirements

## Problem Statement

The current web frontend uses a flat sidebar listing sessions without hierarchy,
grouping, or keyboard navigation. There is no tab system, no context-sensitive
footer, and no activity highlighting. The layout is a fixed-width sidebar rather
than a proportional panel split. Users familiar with the terminal TUI expect
equivalent navigation, grouping, and keyboard-driven interaction in the web
interface.

## Intended Outcome

A two-panel web TUI shell with a tab bar, hierarchical Sessions tab, keyboard
navigation infrastructure, context-sensitive footer, toast notifications, and
migrated modals — serving as the foundation layout that subsequent tabs build on.

---

## R1: Two-Panel Layout

The page layout shall present two panels side by side:

- **Left panel**: occupies 40% of viewport width. Contains a top tab bar, view
  content area, and a fixed bottom footer — in that vertical order.
- **Right panel**: occupies 60% of viewport width. Displays a home/welcome view
  when no session is selected and the active session's chat view when a session
  is selected.

The existing chat and message rendering must continue to function unchanged in
the right panel.

**Success criteria:**

- Left panel renders at 40% width, right panel at 60%.
- Right panel shows home view when no session is active.
- Right panel shows the existing chat component when a session is selected.
- Existing message rendering, scrolling, and real-time updates are unaffected.

## R2: Tab Bar

The left panel shall display a tab bar at the top with four tabs. Only the
Sessions tab (tab 1) is functional in this scope — the remaining three tabs
shall render placeholder content indicating they are not yet implemented.

Tab switching shall be possible via clicking tabs and via keyboard shortcuts
(see R7).

The tab bar shall use accessible tab semantics (correct ARIA roles for
`tablist`, `tab`, and `tabpanel`).

**Success criteria:**

- Four tabs are visible in the tab bar.
- Clicking a tab switches the view content below it.
- The active tab is visually distinguished.
- Tabs 2-4 render placeholder content.
- ARIA roles are correct: `tablist` on the container, `tab` on each tab,
  `tabpanel` on the content area.

## R3: Sessions Tab — Hierarchical Tree

The Sessions tab shall display sessions in a hierarchical tree structure:

- **Level 1 — Computer**: header showing computer name, online/offline status,
  and total session count for that computer.
- **Level 2 — Project**: header showing project name, truncated path, and
  session count for that project.
- **Level 3 — Session**: row showing an index badge, agent icon colored per
  agent design tokens, thinking mode, title, and subdir slug.

Sessions without a project shall be grouped under a synthetic project node.

Sessions spawned by another session (identified by `initiator_session_id`)
shall nest as children of the initiating session. [inferred]

Tree nodes at computer and project levels shall be expand/collapse toggleable.
Session rows shall be expand/collapse toggleable to reveal detail lines
(session ID, status, last activity, etc.). [inferred: detail line content]

**Success criteria:**

- Sessions are grouped by computer, then by project within each computer.
- Computer headers show name, status badge, and session count.
- Project headers show name, truncated path, and session count.
- Session rows show index badge, agent icon (colored per design tokens),
  thinking mode, title, and subdir.
- Orphaned sessions appear under a synthetic project node.
- AI-to-AI child sessions nest under their parent session.
- All tree levels expand and collapse.
- Expanding a session row reveals detail information.

## R4: Activity Highlighting

Active sessions shall receive full-row visual highlighting (not just a status
dot). The highlighting shall be driven by `agent_activity` WebSocket events,
discriminating by the event's `type` field.

**Success criteria:**

- When an `agent_activity` event arrives for a session, that session's row
  receives a visible full-row highlight.
- The highlight reflects the activity type from the event's `type` field.
- Highlighting is transient — it decays or clears after activity stops.
  [inferred: decay behavior needed to avoid permanent highlights]

## R5: Keyboard Navigation — Tree

Tree navigation shortcuts shall fire only when the left panel has focus:

- **Up/Down arrows**: move the cursor through the tree.
- **Enter**: select the cursored item and focus the right panel (opens session
  in chat view). On a project header, open the new-session modal pre-filled
  for that project.
- **Left/Right arrows**: collapse/expand the current node.
- **+/-**: expand/collapse all tree nodes.
- **n**: open the new-session modal.
- **R** (shift): restart the selected session.
- **k**: kill (end) the selected session (triggers confirm modal).

The existing keyboard binding definitions in `frontend/lib/keys/` shall be
used as the data source for shortcut mappings.

**Success criteria:**

- Arrow keys move the cursor through tree nodes.
- Enter selects a session and opens it in the right panel.
- Enter on a project header opens the new-session modal pre-filled.
- Left/Right expand and collapse nodes.
- +/- expand and collapse all nodes.
- n opens new-session modal.
- Shift+R restarts the selected session.
- k on a session triggers the confirm modal for ending it.
- None of these shortcuts fire when a text input or textarea has focus.

## R6: Keyboard Navigation — Global Guards

All keyboard shortcuts shall be guarded against text input/textarea focus:
when a text input or textarea is focused, key presses pass through to the
input and do not trigger shortcut actions.

**Esc** shall close the active modal if one is open, or clear the current
selection if no modal is open.

**Success criteria:**

- Typing in an input or textarea does not trigger any shortcut.
- Esc closes an open modal.
- Esc clears selection when no modal is open.

## R7: Keyboard Navigation — Tab Switching

Number keys 1-4 shall switch between tabs, subject to the same focus guard
as other shortcuts (R6).

**Success criteria:**

- Pressing 1-4 switches to the corresponding tab when no input is focused.
- Pressing 1-4 while an input is focused types the character normally.

## R8: Context-Sensitive Footer

A footer shall be fixed at the bottom of the left panel, always visible. It
shall display keyboard shortcut hints relevant to the current tab and the
type of item currently selected (computer, project, session, or nothing).

Each hint shall show a styled key indicator and a description label.

The footer shall update dynamically as the cursor moves through the tree or
the active tab changes.

**Success criteria:**

- Footer is visible at the bottom of the left panel at all times.
- Footer content changes when the active tab changes.
- Footer content changes when the selected item type changes.
- Each shortcut hint shows a styled key element and description.

## R9: New Session Modal — shadcn Dialog Migration

The existing `NewSessionDialog` shall be migrated from its custom overlay
implementation to use the shadcn Dialog primitive.

The modal shall retain all existing fields: computer, project, agent (with
availability indication), thinking mode, title, and message.

When opened from a project header (via Enter key, R5), the computer and
project fields shall be pre-filled.

The modal shall also accept `native_session_id` and `subdir` fields for
resume-oriented sessions. [inferred: these fields support the API change in R13]

**Success criteria:**

- New Session modal uses shadcn Dialog component.
- All existing form fields are present and functional.
- Pre-filling works when opened from a project header.
- native_session_id and subdir fields are available in the form.
- Modal opens and closes cleanly with proper focus management.

## R10: Confirm Modal

A reusable confirmation modal shall exist, displaying a title, message, and
Yes/No actions. Esc dismisses it (equivalent to No).

This modal shall be used when the user triggers a kill/end action on a session
(R5, k key).

**Success criteria:**

- Confirm modal displays title, message, Yes button, and No button.
- Esc dismisses the modal without performing the action.
- Yes triggers the confirmed action (session end).
- No dismisses the modal.

## R11: Toast Notifications

Toast notifications shall be delivered via sonner (shadcn/ui-adopted).

Toasts shall fire for session lifecycle events:

- Session created
- Session restarted
- Session ended

**Success criteria:**

- Toast appears when a session is created.
- Toast appears when a session is restarted.
- Toast appears when a session is ended.
- Toasts are dismissable and auto-expire.

## R12: shadcn/ui Primitives

The following additional shadcn/ui primitives shall be installed and available
for use: tabs, dialog, scroll-area, badge, tooltip, sonner.

**Success criteria:**

- Each listed primitive is installed and importable.
- Primitives are used in the relevant components (tabs in R2, dialog in R9,
  badge in R3, sonner in R11).

## R13: API — Session Creation Fields

The POST /api/sessions route shall forward `native_session_id` and `subdir`
fields from the request body to the upstream daemon, enabling resume-oriented
session creation.

**Success criteria:**

- POST /api/sessions accepts `native_session_id` and `subdir` in the request body.
- These fields are forwarded to the daemon in the upstream request.
- Existing session creation behavior is unaffected when these fields are absent.

## R14: Design Token Compliance

All agent-related coloring shall use the existing design token system
(CSS custom properties and the TS token maps). Agent icons, highlights,
and selection states shall derive colors from `--tc-agent-{name}-*` variables.

Both dark and light mode shall be supported throughout all new components.

**Success criteria:**

- Agent colors in the tree use design token CSS variables, not hardcoded values.
- All new components render correctly in both dark and light mode.
- No new color values are introduced outside the token system.

---

## Scope Notes

This work is substantial — it restructures the page layout, introduces a tab
system, builds a full hierarchical tree with keyboard navigation, and migrates
modals. The draft phase should assess whether splitting is warranted based on
estimated lines of change and session-size fit. The input is highly detailed,
which reduces discovery overhead for the builder, but the total surface area
is large.

Only the Sessions tab is implemented; tabs 2-4 are placeholders. The right
panel's existing chat functionality is preserved, not modified.

## Deferred

- Tabs 2-4 content (Preparation, Configuration, etc.) — separate todos.
- Session restart API integration (R5 mentions restart; the API route for
  restart is out of scope if it doesn't exist yet). [inferred]
- Mobile/responsive layout — the input specifies no mobile behavior changes
  beyond what the existing sidebar already handles. [inferred]
