# Review Findings: web-tui-panels (Round 2)

## Review metadata

- Branch: `web-tui-panels`
- Diff: 50 files changed, ~3633 insertions, ~182 deletions
- TypeScript: clean (`npx tsc --noEmit`)
- Tests: 98/98 passing (`npx vitest run --config vitest.cli.config.ts`)
- Implementation plan tasks: all checked

## Round 1 findings — all resolved

| Finding                             | Status   | Verification                                                                                                                                           |
| ----------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| C-1 (browser key normalization)     | Resolved | `BROWSER_KEY_MAP` in `findBinding()` translates `ArrowUp`→`upArrow`, `Enter`→`return`, etc. Test in `panel-navigation.test.ts` verifies normalization. |
| I-1 (R3.8 config subtab navigation) | Resolved | `navigate_up`, `navigate_down`, `select_item` cases added to ConfigView's `handleKeyDown`. No-ops since all subtabs are read-only.                     |
| I-2 (preview_file/view_file)        | Resolved | Both actions handled in PreparationView with toast feedback indicating daemon endpoint needed.                                                         |
| I-3 (dead navigator/queue code)     | Resolved | All listed exports removed. `lib/panels/theme.ts` and `lib/toasts/queue.ts` deleted.                                                                   |
| I-4 (missing proxy route tests)     | Resolved | `panel-proxy-routes.test.ts` now covers auth gating and daemon proxying for prepare, work, and refine routes.                                          |
| I-5 (out-of-scope Python tests)     | Resolved | Changes required to pass pre-commit hooks (backend behavior had changed on main; stale characterization tests failed the hook gate).                   |
| I-6 (duplicate k binding)           | Resolved | Hidden `k`→`navigate_up` removed from sessions context. `k`→`kill_session` is now the sole match, matching the Python TUI.                             |

## Critical

(none)

## Important

(none)

## Suggestions

### S-1: `lib/preparation/actions.ts` tested but unused in production

**Location:** `lib/preparation/actions.ts`

`getPreparationActionAvailability` and all its associated types are tested in
`preparation-panel.test.ts` but never imported by any React component.
`PreparationView` uses its own inline `UNAVAILABLE_ACTIONS` set for the same
purpose. Same YAGNI pattern as the resolved I-3 finding. The module is small
(57 lines) and well-typed — not harmful, just unnecessary.

### S-2: `PanelTab` interface unused

**Location:** `lib/panels/navigation.ts:3-8`

`PanelTab` is exported but never imported. Only `PanelId` is consumed by
`TabBar`, `useActiveView`, and `page.tsx`.

### S-3: Demo validation blocks assume `cd frontend`

**Location:** `demos/web-tui-panels/demo.md:66-78`

The executable bash blocks start with `cd frontend && ...`. In the worktree
context (`trees/web-tui-panels`) the working directory IS the frontend — these
commands would fail. Execution-context dependent; not blocking.

---

## Why No Issues

### Paradigm-fit verification

- All 6 new API routes (`todos/route.ts`, `todos/[slug]/prepare|work|refine`,
  `jobs/route.ts`, `jobs/[name]/run/route.ts`) follow the established daemon
  proxy pattern: auth check → daemon request → normalize upstream error → return.
  Compared against `api/computers/route.ts`, `api/settings/route.ts`,
  `api/sessions/[id]/route.ts` as references.
- Data hooks (`useJobs`, `usePeople`) follow the exact `useQuery` pattern of
  `useTodos`, `useComputers`, `useSettings` — single `useQuery` call with
  cache key and fetch function.
- Components use dynamic imports, Tailwind theme-aware classes, and the
  established `findBinding`-based keyboard handling pattern.

### Requirements validation

Every requirement (R1.1 through R8.1) traced to implementation:

- **R1**: Tab bar renders 4 tabs, `1`-`4` shortcuts wired, `display:none`
  preserves state, sessions default on load.
- **R2**: Tree renders hierarchy, keyboard navigation wired (including
  preview_file/view_file with toast), actions dispatch via proxy routes,
  unavailable actions show toast.
- **R3**: Admin gate via `resolveConfigurationAccess`, 5 subtabs, subtab
  keyboard navigation, read-only displays with CLI pointers.
- **R4**: Jobs fetched via hook, split into scheduled/one-shot sections,
  cursor navigation, Enter triggers job with toast.
- **R5**: Modals validate slugs, submit via API, Esc/Enter work.
- **R6**: Toast system with success/destructive variants, 4s auto-dismiss.
- **R7**: All proxy routes with auth, admin gates, input validation.
- **R8**: All components use theme-aware Tailwind classes.

No unrequested features or gold-plating detected.

### Copy-paste duplication check

- The three `todos/[slug]/{prepare,work,refine}/route.ts` files are structurally
  identical (auth → proxy → error). Each is 42 lines. Extracting a shared
  factory would save ~60 lines but add indirection for a pattern that occurs
  exactly 3 times. Current approach is acceptable per DRY nuance ("duplication
  is cheaper than the wrong abstraction").
- `NewTodoModal` and `NewBugModal` share similar structure but differ in slug
  prefix handling and user messaging. Reasonable duplication for distinct
  behaviors.

### Security review

- No hardcoded secrets in diff.
- Slug validation via regex at API boundary prevents injection.
- `encodeURIComponent` on all path parameters.
- Auth session checked on every route. Admin gate on `POST /api/jobs/[name]/run`.
- Error responses return generic messages, no stack traces or internal paths.

---

## Verdict

| Severity               | Count |
| ---------------------- | ----- |
| Critical (unresolved)  | 0     |
| Important (unresolved) | 0     |
| Suggestion             | 3     |

**Verdict: APPROVE**
