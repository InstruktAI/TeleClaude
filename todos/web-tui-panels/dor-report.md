# DOR Gate Report: web-tui-panels

**Assessed at:** 2026-03-25T09:00:00Z
**Score:** 7/10
**Verdict:** needs_work

---

## Gate Summary

The artifact set is well-grounded and detailed. Requirements are clear, the plan has
comprehensive task sequencing, rationale per task, and a full traceability table.
Grounding was verified against the actual codebase (`bindings.ts`, `proxy-routes.test.ts`,
hook files). The single blocking issue is that test specifications were not pre-delivered
as expected-failure stubs — DOR Gate 3 partial fail.

---

## Cross-artifact Validation

### Plan-to-requirement fidelity

All plan tasks trace to requirements. The traceability table covers every requirement ID
(R1.1–R8.1). No task contradicts a requirement. The plan's handling of R7.4 (PATCH
settings allowlist) as "documented limitation" without a task is correct — the requirement
explicitly scopes it as a known boundary, not work.

Minor observation: R2.4 in requirements refers to dispatching `POST /todos/prepare`; the
plan (Task 7) correctly routes this through slug-parameterized proxy routes
(`/todos/{slug}/prepare`). Consistent.

### Coverage completeness

Every requirement maps to at least one task. No orphan requirements. No orphan tasks
(gold-plating). The R3.1–R3.8 → T3, T8 grouping is appropriate — people data hook (T3)
feeds the config view (T8).

### Verification chain

The plan's combined verification steps would satisfy DoD gates IF the test specs are
delivered. Currently the proxy route test scenarios are described in Task 11 but not
present as expected-failure stubs in `frontend/lib/__tests__/proxy-routes.test.ts`.
This is the primary gap.

---

## DOR Gate Results

### Gate 1: Intent & success — PASS

- Problem statement explicit: add three admin views (Preparation, Config, Jobs) to the
  web TUI on top of the `web-tui-shell` infrastructure.
- "What" and "why" captured in `input.md` and `requirements.md`.
- Success criteria are concrete and checkable (tab switching, tree rendering, keyboard
  navigation, modal creation, toast feedback, API proxy routes).
- Success criteria include both functional and non-functional requirements (dark/light
  mode, WebSocket real-time updates).

### Gate 2: Scope & size — PASS (marginal)

- Plan estimates ~1200 new lines across ~35 files in 11 tasks.
- The coherence argument is solid: tabs without views have no value; views without the
  toast/modal infrastructure are incomplete. The work is atomic.
- All 11 tasks have clear dependencies and sequencing (T1 → T2 → T3 → ... → T11 is
  top-to-bottom, each builds on the previous).
- Risk: at the upper boundary for one session. Plan explicitly evaluated this and
  justified atomicity. The detail in the plan (exact file paths, TypeScript interfaces,
  behavioral notes) reduces session startup cost significantly.
- Cross-cutting changes are explicit and justified (keyboard bindings system, layout.tsx,
  page.tsx).

### Gate 3: Verification — PARTIAL FAIL

- **Gap:** DOR requires "executable test specifications (expected-failure-marked) exist."
  `test_spec_review.verdict` in `state.yaml` is empty — no test specs were produced
  in the prepare phase.
- The plan (Task 11) describes proxy route test scenarios in detail (auth gates, admin
  gates, slug validation, daemon proxying, error passthrough). These are clear enough
  to pre-deliver as `it.todo()` stubs in `proxy-routes.test.ts`. They have not been.
- React component behavioral tests are not planned at all. For the tree, tab switching,
  and modal components, verification relies on visual/manual checks in each task's
  verification section. This is acceptable for UI in this stack but leaves behavioral
  regression risk.
- The demo artifact exists (`demo.md`) and is domain-specific with executable validation
  blocks (`pnpm build`, `pnpm test:cli`, `pnpm tsc --noEmit`). This partially compensates.
- **Required action:** Deliver `it.todo()` stubs for all proxy route test cases
  described in Task 11 into `frontend/lib/__tests__/proxy-routes.test.ts` before
  implementing those routes. The builder should treat this as Task 0.

### Gate 4: Approach known — PASS

- Grounding verified against actual codebase:
  - `bindings.ts` confirmed: `preparation` and `configuration` contexts exist. Global
    `1`/`2`/`3` bindings exist. `4` (Jobs) is absent — plan correctly identifies this.
  - Missing preparation bindings confirmed absent: `n`, `b`, `r`, `R`, `f`,
    `leftArrow`, `rightArrow`, `upArrow+shift`, `downArrow+shift`.
  - `proxy-routes.test.ts` exists with vitest infrastructure (describe, it, vi.mock,
    makeSession helper). Plan's Task 11 can directly extend it.
- All patterns reference existing codebase files:
  - Proxy pattern: `app/api/todos/route.ts`, `app/api/settings/route.ts`
  - Auth guards: `auth-guards.ts` (`requireAdmin`)
  - React Query hooks: `useTodos.ts` (17-line pattern)
  - Modal pattern: `NewSessionDialog.tsx`
- Toast: `@radix-ui/react-toast` referenced as "already in the lockfile." This is a
  strong grounding signal that the shadcn toast pattern can be applied directly.
- No architectural decisions remain unresolved. The plan explicitly addresses
  unknowns (bug modal fallback, env var data availability, validate subtab CLI-only).

### Gate 5: Research complete — PASS

- No new third-party libraries introduced. `@radix-ui/react-toast` is an existing
  dependency.
- shadcn/ui patterns are established in the codebase. No new frameworks to research.
- Gate automatically satisfied for third-party dependencies.

### Gate 6: Dependencies & preconditions — PASS

- Daemon API gaps explicitly listed in requirements scope section and handled:
  - Remove, freeze, move → disabled with explanatory toast.
  - Bug modal → fallback to CLI message if no daemon mechanism.
  - Environment vars → placeholder if daemon returns nothing.
  - Config editing → read-only with CLI indicator.
- No new config keys, env vars, or YAML sections introduced by this work.
- The `web-tui-shell` prerequisite (established tab shell) is assumed complete — this
  todo is in the same worktree, building on that foundation.

### Gate 7: Integration safety — PASS

- All changes are additive: new files created, existing files minimally modified
  (layout.tsx, page.tsx, bindings.ts).
- The `display: none` approach for inactive views is explicitly chosen over conditional
  unmounting to preserve React state (R1.2). This is a safe, reversible implementation
  decision.
- No schema or data shape migrations.
- Entry/exit: tab bar wraps the existing sessions view without touching its internals.

### Gate 8: Tooling impact — PASS

- No tooling or scaffolding changes. Gate automatically satisfied.

---

## Review-readiness Assessment

Walking DoD gates against the plan:

| DoD Gate       | Status | Notes                                                                                             |
| -------------- | ------ | ------------------------------------------------------------------------------------------------- |
| Functionality  | READY  | All requirements have task coverage, verification steps defined.                                  |
| Code quality   | READY  | TypeScript compilation check in each task. Existing patterns used.                                |
| Testing        | GAP    | Proxy route specs described but not pre-delivered. See Gate 3.                                    |
| Linting        | READY  | TypeScript compilation checks per task.                                                           |
| Security       | READY  | Auth gates explicit on all write routes (requireAdmin). Read routes require auth session.         |
| Documentation  | READY  | No new CLI commands, no config surface changes.                                                   |
| Commit hygiene | READY  | Standard commitizen format assumed.                                                               |
| Observability  | MINOR  | No specific logging requirements for new API routes, but proxy pattern inherits existing logging. |

Security assessment is strong: all write proxy routes require authentication; admin-only
routes explicitly use `requireAdmin`; the slug validation regex is specified
(`/^[a-z0-9]+(-[a-z0-9]+)*$/`) and applied at both frontend and proxy route level.

---

## Blockers

1. **Test specs not pre-delivered (Gate 3 partial fail).**
   - Action: add `it.todo()` stubs for all proxy route scenarios listed in Task 11
     to `frontend/lib/__tests__/proxy-routes.test.ts` before implementing the routes.
   - This is a small, mechanical action (~30 lines). Once done, the gate passes.
   - The builder can treat this as Task 0 before Task 1.

---

## Findings (non-blocking)

- **Component behavioral tests absent.** The plan covers proxy routes (Task 11) but has
  no component test plan for tree navigation, tab switching, or modal interactions.
  For this UI stack, this is acceptable but noted as a coverage gap.
- **Scope size at upper boundary.** ~1200 lines / 35 files / 11 tasks is large for one
  session. The plan's detail compensates but the builder should checkpoint after Task 6
  (the most complex task) and assess remaining context headroom.
- **R7.4 PATCH settings allowlist** is documented as a known limitation with no task.
  This is correct scoping but the documentation note ("builder creates alongside actions"
  in Task 7 for prepare/work/refine routes) slightly underspecifies those routes. The
  builder should apply the same auth + daemon proxy pattern as Task 2 routes.

---

## Path to pass

1. Builder delivers proxy route test stubs as `it.todo()` before Task 2 implementation.
2. Gate re-assessment would score 8/10 → **pass**.
