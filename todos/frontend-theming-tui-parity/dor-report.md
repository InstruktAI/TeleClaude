# DOR Report: frontend-theming-tui-parity

## Gate Verdict: PASS (score 8/10)

Assessed: 2026-02-23

---

## Gate Assessment

### 1. Intent & Success — PASS

- Problem statement is explicit in `input.md`: port TUI theming to the web frontend.
- `requirements.md` has a clear Goal section and 10 concrete, testable success criteria (SC-1 through SC-10).
- The "what" (replace oklch, add theming toggle, conditional colors) and "why" (TUI parity, white-labeling) are captured.

### 2. Scope & Size — PASS

- 9 phases, but many are small (2-3 line changes). The bulk is Phase 1 (CSS replacement) and Phase 6 (component wiring).
- All changes are within `frontend/` — single domain, tightly scoped.
- No cross-cutting concerns beyond frontend.
- Fits a single builder session.

### 3. Verification — PASS

- `demo.md` has concrete bash validation scripts.
- SC-1 through SC-10 are all verifiable via observation or grep.
- Visual matrix (4 combinations) is specified with exact expected colors.
- Quality checklist covers lint, tests, commits.
- Edge case: unknown agent type → graceful fallback (Task 7.1).

### 4. Approach Known — PASS

- Technical path is clear: replace CSS values, extend existing token system, create React context/providers.
- `css-variables.ts` already generates and injects CSS vars — proven pattern.
- `next-themes` already installed and configured in `layout.tsx`.
- `PaneThemingMode` type and daemon API settings already exist (verified in `frontend/lib/api/types.ts` and `frontend/app/api/settings/route.ts`).
- All referenced files exist and contain expected structures.

### 5. Research Complete — AUTO-SATISFIED

- No new third-party dependencies.
- `next-themes` and shadcn/ui are already in use.
- Risk about oklch→hex in Tailwind v4's `@theme` block is identified with mitigation (test all shadcn components).

### 6. Dependencies & Preconditions — PASS (after tightening)

- No prerequisite todos.
- Daemon API for `pane_theming_mode` exists and is wired.
- All required infrastructure is in place.
- **Action taken:** Added slug to `roadmap.yaml` (was missing — untracked directory without roadmap registration).

### 7. Integration Safety — PASS

- Changes are additive: replacing CSS values, creating new files, adding providers.
- Theming toggle defaults to peaceful (no visible change from current state).
- Rollback: revert globals.css + remove new files — straightforward.
- No destabilization risk to main.

### 8. Tooling Impact — AUTO-SATISFIED

- No tooling or scaffolding changes.

---

## Plan-to-Requirement Fidelity

All 10 success criteria trace to implementation plan tasks:

| Requirement                           | Plan Task(s)            | Contradiction |
| ------------------------------------- | ----------------------- | ------------- |
| SC-1 (globals.css hex tokens)         | Task 1.1                | None          |
| SC-2 (CSS custom properties)          | Task 2.1, 2.2           | None          |
| SC-3 (theme.local.css)                | Task 3.2, 3.3           | None          |
| SC-4 (theming toggle persists)        | Task 4.1, 5.1           | None          |
| SC-5 (peaceful mode)                  | Task 6.1, 6.2, 6.3      | None          |
| SC-6 (themed mode)                    | Task 6.1, 6.2, 6.3, 7.1 | None          |
| SC-7 (chat bg never agent-tinted)     | Task 6.2                | None          |
| SC-8 (dark/light toggle works)        | Task 3.1, 3.4           | None          |
| SC-9 (no hardcoded hex in components) | Task 8.3                | None          |
| SC-10 (4-combo matrix)                | Task 8.1                | None          |

No contradictions found. All plan tasks trace to requirements.

---

## Advisory Notes for Builder

### Token value discrepancy between `tokens.ts` and TUI

Several `globals.css` values in the plan come from `THEMING-PLAN.md` / `theme.py` (TUI source of truth), not from `tokens.ts`:

| Property       | `tokens.ts` (dark) | Plan / `theme.py` | Reason                                                        |
| -------------- | ------------------ | ----------------- | ------------------------------------------------------------- |
| `bg.surface`   | `#000000`          | `#262626`         | tokens.ts uses terminal default; web needs distinct elevation |
| `text.primary` | `#e4e4e4`          | `#d0d0d0`         | tokens.ts has xterm 254; TUI uses softer gray                 |

The plan is correct — it follows the TUI's actual values. The `globals.css` is the right place for these web-specific values. The builder does NOT need to update `tokens.ts` to implement this plan, because globals.css defines the shadcn semantic variables directly and the JS injection layer (`css-variables.ts`) uses a separate namespace (`--agent-*`, `--bg-*`, etc.).

### Sidebar component targeting

The plan references `SessionItem.tsx` which doesn't exist. The actual component is `SessionList.tsx` with inline session item rendering (lines 89-119). The builder should apply sidebar coloring within `SessionList.tsx`'s map callback.

### Hardcoded agent icon colors in `SessionList.tsx`

`SessionList.tsx` currently has hardcoded Tailwind color classes for agent icons (`text-blue-500`, `text-green-500`, `text-purple-500`). These should be migrated to CSS variable references as part of Task 6.3.

---

## Actions Taken

1. Added `frontend-theming-tui-parity` to `roadmap.yaml`.
2. Verified all referenced source files exist.
3. Confirmed `PaneThemingMode` API is wired end-to-end.
4. Cross-referenced plan values against TUI theme.py source of truth.
