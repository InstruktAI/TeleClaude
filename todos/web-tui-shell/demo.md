# web-tui-shell — Demo Plan

## Medium

Web browser (localhost dev server). All scenarios use the running Next.js app
with at least 2-3 active sessions across different computers/projects.

---

## Scenario 1: Layout and Tab System

**Setup:** Open the web app.

**Observe:**

1. Two-panel layout — left panel occupies ~40% width, right panel ~60%.
2. Left panel has a tab bar at the top with four tabs.
3. Sessions tab is active by default, showing the session tree.
4. Click tabs 2-4 — each shows placeholder "Not yet implemented" content.
5. Click Sessions tab — tree reappears.

**Keyboard validation:** 6. Press `2`, `3`, `4` — tabs switch via keyboard. 7. Press `1` — back to Sessions. 8. Click into the chat input, press `2` — character types normally, tab does
not switch.

**Validates:** R1, R2, R7, R6 (partial)

---

## Scenario 2: Session Tree Hierarchy

**Setup:** Have sessions across at least 2 computers, with multiple projects
per computer and at least one session with no project.

**Observe:**

1. Tree shows Computer → Project → Session hierarchy.
2. Computer headers: name, online/offline badge, total session count.
3. Project headers: name, truncated path, session count.
4. Session rows: index badge, colored agent icon, thinking mode, title, subdir.
5. Click a computer header — collapses, hiding its children. Click again —
   expands.
6. Click a project header — same collapse/expand.
7. Click a session row to expand — detail lines show session ID, status,
   last activity.
8. Session(s) without a project appear under a synthetic project node.
9. AI-to-AI spawned sessions nest as children under their parent session.

**Validates:** R3, R14

---

## Scenario 3: Activity Highlighting

**Setup:** At least one session actively running (tools or thinking).

**Observe:**

1. Active session's row shows full-row highlight (not just a dot).
2. Highlight style reflects activity type.
3. Stop agent activity. Within ~5 seconds, highlight fades/clears.
4. Resume activity — highlight reappears.

**Validates:** R4

---

## Scenario 4: Keyboard Navigation

**Setup:** Sessions tab active, left panel focused.

**Observe:**

1. Down arrow — cursor moves to next visible tree node.
2. Up arrow — cursor moves up. Cursor visually distinct from activity
   highlighting.
3. Navigate to collapsed computer/project. Right arrow — expands. Left
   arrow — collapses.
4. Press `+` — all nodes expand. Press `-` — all collapse.
5. Navigate to a session. Enter — right panel shows that session's chat.
6. Navigate to a project header. Enter — New Session modal opens with
   computer and project pre-filled.
7. Close modal. Press `n` — New Session modal opens (no pre-fill).
8. Close modal. Navigate to a session. Press `k` — Confirm modal asks to
   end session.
9. Press Esc — Confirm modal closes without ending.
10. Press Shift+`R` on a session — session restarts.

**Validates:** R5, R6

---

## Scenario 5: Footer Context Sensitivity

**Setup:** Sessions tab active.

**Observe:**

1. Footer visible at bottom of left panel.
2. No selection: footer shows general shortcuts (arrows, +/-, n).
3. Move cursor to session: footer updates with session shortcuts (Enter, R, k).
4. Move cursor to project header: footer shows project shortcuts (Enter to
   create session).
5. Switch to tab 2: footer updates to that tab's context.

**Validates:** R8

---

## Scenario 6: Modals

**Setup:** Sessions tab, left panel focused.

**Observe:**

1. Press `n` — New Session modal opens as shadcn Dialog (overlay, centered,
   focus-trapped).
2. Fields visible: computer, project, agent (with availability), thinking
   mode, title, message.
3. `native_session_id` and `subdir` fields present.
4. Fill in fields, submit — session creates.
5. Navigate to a session, press `k` — Confirm modal: "End session?", Yes/No.
6. Press No (or Esc) — modal closes, session continues.
7. Press `k` again, press Yes — session ends.

**Validates:** R9, R10

---

## Scenario 7: Toast Notifications

**During scenarios 6 actions:**

1. After creating a session — success toast appears.
2. After ending a session — info toast appears.
3. After restarting (Shift+R) — success toast appears.
4. Toasts auto-expire. Can be dismissed manually.

**Validates:** R11

---

## Scenario 8: Dark/Light Mode

**Setup:** Toggle the theme switcher.

**Observe:**

1. All new components (tree, tabs, footer, modals, toasts) render correctly
   in both dark and light mode.
2. Agent icon colors update through CSS variables — no flash, no hardcoded
   colors.
3. Borders, backgrounds, and text use design token variables throughout.

**Validates:** R14

---

## Validation Commands

```bash
# Dev server
pnpm dev

# Run tests
npx vitest run --config vitest.cli.config.ts

# Type check
npx tsc --noEmit

# Verify no hardcoded colors in new or modified shell components
grep -rn '#[0-9a-fA-F]\{3,8\}' frontend/components/tui/ frontend/components/sidebar/NewSessionDialog.tsx

# Verify API route forwards new fields
grep -q 'native_session_id' frontend/app/api/sessions/route.ts && echo "OK" || echo "MISSING"
grep -q 'subdir' frontend/app/api/sessions/route.ts && echo "OK" || echo "MISSING"

# Verify Toaster in layout
grep -q 'Toaster' frontend/app/\(chat\)/layout.tsx && echo "OK" || echo "MISSING"

# Validate demo artifact wiring
telec todo demo validate web-tui-shell
```
