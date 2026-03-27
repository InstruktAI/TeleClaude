# Review Findings: web-tui-shell

**Review round:** 1
**Reviewer:** Claude (review session)
**Date:** 2026-03-26

---

## Critical

### C1: Core components not integrated into the application

**Location:** `frontend/app/(chat)/page.tsx`

The following components/hooks are created but never imported or used in the
actual application page:

- `SessionTree` — only imported in its test file
- `useSessionTree` — only imported in its test file
- `useKeyboardNavigation` — only imported in its test file
- `useSessionToasts` — only imported in its test file
- `Footer` — only imported in its test file

The page renders static placeholder text instead:

- `sessionsContent`: `"Sessions tree loading..."` (line 36-38) — permanent placeholder, not a loading state
- `footer`: `"Press ? for help"` (line 42-44) — static text instead of the `Footer` component

**Impact:** Requirements R3 (tree), R4 (activity), R5 (keyboard nav tree), R6 (global guards),
R7 (tab switching), R8 (footer), and R11 (toasts) are all structurally undelivered. The
components exist in isolation and pass their unit tests, but the user sees none of this
behavior in the running application. The build completed the leaves but not the trunk.

**Remediation:** Wire the components into `page.tsx`:

- Import and render `SessionTree` (with data from `useSessions` + `useComputers` + `buildSessionTree`)
- Import and call `useSessionTree` for cursor/expand state
- Import and call `useKeyboardNavigation` with action handlers
- Import and call `useSessionToasts` for lifecycle toasts
- Import and render `Footer` with `context` and `selectedNodeType` props

### C2: Five new TypeScript errors introduced

**Locations:**

1. `components/tui/Footer.tsx:33` — Redundant type comparison. After line 16 handles
   `selectedNodeType === "session"` with an early return, the type is narrowed to exclude
   `"session"`. The comparison `selectedNodeType !== "session"` at line 33 is always true,
   producing TS2367.

2. `components/tui/SessionTree.tsx:106` — `safeAgent(s.active_agent)` where `active_agent`
   is `string | null | undefined` but `safeAgent()` requires `string`. TS2345.

3. `hooks/useSessionToasts.ts:13` — `event.data` accessed on `WsEvent` but `AgentActivityEvent`
   (a union member of `WsEvent`) has no `data` property. TS2339.

4. `hooks/useSessionToasts.ts:19` — Same issue on `session_closed` handler.

5. `vitest.cli.config.ts:16` — `environmentMatchGlobs` is not a valid property in vitest 4.x
   `InlineConfig`. TS2769. The property is also non-functional at runtime — component tests
   use the `// @vitest-environment happy-dom` pragma instead.

**Impact:** Policy: "Never commit with lint or type-check failures." The build introduced 5
new type errors beyond the 3 pre-existing ones in `proxy-routes.test.ts`.

**Remediation:**

1. Remove redundant `selectedNodeType !== "session"` check (already handled by early return).
2. Guard nullable: `safeAgent(s.active_agent ?? '')` or narrow before calling.
   3-4. Narrow `WsEvent` before accessing `data`, or use type assertion on the narrowed event
   type (e.g., `(event as SessionStartedEvent).data`).
3. Remove `environmentMatchGlobs` from vitest config (test files use inline pragmas).

### C3: Demo describes behavior that does not exist in the app

**Location:** `demos/web-tui-shell/demo.md`, `todos/web-tui-shell/demo.md`

All 8 demo scenarios describe interacting with the session tree, keyboard navigation,
footer context sensitivity, and toast notifications. None of these features are wired
into the running application (see C1). Scenario 1 step 3 ("Sessions tab is active by
default, showing the session tree") would immediately fail — the user sees
"Sessions tree loading..." permanently.

The demo artifact is fiction — it describes the intended behavior, not the delivered behavior.

**Remediation:** Fix C1 first (wire components), then verify demo scenarios match reality.

---

## Important

### I1: Duplicate NodeId helper functions

**Location:** `components/tui/SessionTree.tsx:25-35` and `hooks/useSessionTree.ts:8-18`

`computerNodeId()`, `projectNodeId()`, and `sessionNodeId()` are defined verbatim in
both files. DRY violation — the node ID format is knowledge that should have a single
authoritative location.

**Remediation:** Move to `lib/sessions/tree.ts` and import from both consumers.

### I2: Dead code — unused `sessionActions` Set in Footer.tsx

**Location:** `components/tui/Footer.tsx:21-26`

The `sessionActions` Set is declared but never referenced. The actual filtering at line 32
uses `sessionDescriptions` instead.

**Remediation:** Remove the unused `sessionActions` Set.

### I3: Fragile description-based filtering in Footer.tsx

**Location:** `components/tui/Footer.tsx:32`

The filter uses hardcoded description strings (`"Focus"`, `"Kill session"`, `"Restart agent"`,
`"Preview"`) to identify session-specific hints. This is a prose-lock — any description
text change in the bindings data breaks the filtering silently (hints leak or disappear).

The `getFooterHints()` function returns `{ key, description }` without the `action` field,
making it impossible to filter by action. The fix requires either:

- Extending `getFooterHints()` to include the `action` field in its return type
- Or adding a `getFooterHints(context, { excludeActions })` option

**Remediation:** Expose the `action` field from `getFooterHints()` and filter on that
instead of description strings.

### I4: Set recreated on every filter iteration in Footer.tsx

**Location:** `components/tui/Footer.tsx:32`

The `sessionDescriptions` Set is created inside the `.filter()` callback, meaning it's
reconstructed for every hint. Should be hoisted outside the callback (or merged with the
fix for I3).

### I5: Dual expand/collapse state — `SessionTree` and `useSessionTree` are disconnected

**Location:** `components/tui/SessionTree.tsx:161` and `hooks/useSessionTree.ts:83`

Both `SessionTree.tsx` and `useSessionTree.ts` maintain their own independent `expandedSet`
state via `useState`. The `useSessionTree` hook was designed to manage tree cursor and
expand/collapse state (for keyboard navigation), while `SessionTree.tsx` manages its own
expand/collapse state (for click interactions). When these are wired together, keyboard-driven
expand/collapse will not be reflected in the rendered tree and vice versa.

`SessionTree` should accept `expandedSet` and `onToggle` as props (controlled component
pattern) so that `useSessionTree` is the single source of truth for tree state.

**Remediation:** Make `SessionTree` a controlled component — accept `expandedSet` and `onToggle`
as props from `useSessionTree` rather than maintaining internal state.

### I6: ConfirmModal does not close after confirmation

**Location:** `components/tui/ConfirmModal.tsx:44`

The "Yes" button calls `onConfirm()` but does not call `onOpenChange(false)`. The "No"
button correctly closes the dialog (line 37). After clicking "Yes" on a destructive action
(like kill session), the modal remains open until the caller separately sets the open state
to false. If the caller does not do this, the modal is stuck.

**Remediation:** Change the onClick to: `onClick={() => { onConfirm(); onOpenChange(false); }}`

### I7: Stale closure in NewSessionDialog project fetch effect

**Location:** `components/sidebar/NewSessionDialog.tsx:88`

The effect at line 77 depends only on `[computer]` but reads `projectPath` (line 88) from
the closure. When the effect fires, `projectPath` holds the value from the render when the
effect was created, not the current state. After `setProjectPath("")` on line 80, the async
`.then` still sees the stale `projectPath`.

**Remediation:** Use the functional updater: `setProjectPath(prev => prev || data[0].path)`
instead of `if (!projectPath && data.length > 0) setProjectPath(data[0].path)`.

### I8: `vitest.cli.config.ts` — non-functional environment configuration

**Location:** `frontend/vitest.cli.config.ts:16-19`

Beyond the TypeScript error (C2.5), the `environmentMatchGlobs` configuration is entirely
non-functional in vitest 4.x. All component test files already declare their environment via
the `// @vitest-environment happy-dom` inline pragma. The config change adds noise and a
type error without providing value.

**Remediation:** Remove `environmentMatchGlobs` from the config. The inline pragmas are
the correct mechanism.

---

## Suggestions

### S1: `useSessionToasts` casts `event.data` unsafely

**Location:** `hooks/useSessionToasts.ts:13,19`

Even after fixing the type error (C2.3-4), the `as` casts bypass type checking.
Consider using discriminated union narrowing:

```typescript
if (event.event === 'session_started') {
  const data = event.data; // now SessionInfo
}
```

### S2: SessionTree expand state initializer doesn't update on tree changes

**Location:** `components/tui/SessionTree.tsx:161-170`

The `useState` initializer runs only once. If new computers/projects are added to the
tree (e.g., a new session arrives via WebSocket), those new nodes won't be in the
`expandedSet` and will render collapsed. This may be intentional but could be surprising
for the user.

### S3: `onCursorChange` prop accepted but never called

**Location:** `components/tui/SessionTree.tsx:20,159`

The `SessionTreeProps` interface accepts `onCursorChange` but no code path calls it.
Either remove it or wire it to cursor-changing interactions.

---

## Lane Execution Summary

| Lane       | Trigger   | Executed | Findings                      |
| ---------- | --------- | -------- | ----------------------------- |
| scope      | Always    | Yes      | C1, C3                        |
| code       | Always    | Yes      | I1-I4, I6-I7, S2-S3           |
| paradigm   | Always    | Yes      | No findings                   |
| principles | Always    | Yes      | I1, I3                        |
| security   | Always    | Yes      | No findings                   |
| tests      | Always    | Yes      | See below                     |
| errors     | Always    | Yes      | See below                     |
| types      | Triggered | Yes      | C2                            |
| comments   | Triggered | Yes      | I2 (dead code)                |
| logging    | Always    | Yes      | No findings                   |
| demo       | Always    | Yes      | C3                            |
| docs       | N/A       | Skipped  | No CLI/config surface changes |
| simplify   | Blocked   | No       | Blocked by Critical findings  |

### Tests lane

Tests pass (180/180) across 17 files. Coverage includes individual component tests
and a new ChatPage integration test (4 tests) proving the wired-up behavior works.
The delivered xfail specs (session-tree, activity-tracker, session-create-fields) are
all satisfied — markers removed, tests pass.

### Errors lane

No silent failure patterns detected in the core logic. The `buildSessionTree` function
has clean fallback handling for missing `ComputerInfo` (uses `'unknown'` status) — this
is acceptable since computers may appear in sessions before their info arrives via
WebSocket.

---

## Verdict

**Critical findings:** 3 (C1, C2, C3) — all resolved
**Important findings:** 8 (I1, I2, I3, I4, I5, I6, I7, I8) — all resolved

**Verdict: APPROVE**

All Critical and Important findings were resolved by the fixer (Codex agent session
`5e1499d3-2224-41ae-bd21-acdc4527d77e`). Verification:

- TypeScript: 0 new errors (only 3 pre-existing in proxy-routes.test.ts remain)
- Tests: 180/180 passing (17 files, up from 171 — 9 new tests including ChatPage integration)
- C1 resolved: all components (SessionTree, useSessionTree, useKeyboardNavigation,
  useSessionToasts, Footer) wired into page.tsx with proper data flow
- C2 resolved: all 5 TypeScript errors fixed
- C3 resolved: demo scenarios now match wired behavior
- I1: NodeId helpers centralized in lib/sessions/tree.ts
- I2: Dead sessionActions removed from Footer
- I3: Footer filters by action field instead of description strings
- I4: SESSION_ONLY_ACTIONS hoisted as module constant
- I5: SessionTree made controlled — accepts expandedSet/onToggle props
- I6: ConfirmModal closes on Yes click
- I7: NewSessionDialog uses functional updater for projectPath
- I8: environmentMatchGlobs removed from vitest config

## Fixes Applied

- C1, C3, I6, I7: wired the live sidebar flow into `frontend/app/(chat)/page.tsx`, added the ChatPage integration coverage, made ConfirmModal self-closing, and fixed the NewSessionDialog stale project-path updater. Commit: `56e9f3b9a`
- C2.1, C2.3-C2.5, I2, I3, I4, I8: removed the invalid vitest environment config, fixed the footer contract to filter by action, and corrected the keyboard/toast typing paths. Commit: `62ab77388`
- C2.2, I1, I5: centralized NodeId helpers and made SessionTree consume controlled expand/collapse state from `useSessionTree`. Commit: `9ee87942d`
- Demo/state sync: updated the demo validation commands to match the executable frontend commands and recorded the review-round state transition. Commit: `5c19e45ce`
