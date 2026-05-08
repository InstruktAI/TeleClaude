# frontend-preparation-pane — Implementation Plan

## Overview

Enrich the web frontend preparation pane to match the TUI's information density: dependency-ordered
tree, structured phase display with priority cascade, colored status block indicators, and column
alignment. All changes are in the frontend; no backend modifications are required.

## Atomicity verdict

This todo remains atomic after regrounding. The changed files still describe one coherent user-facing
behavior: richer preparation-pane rendering from existing daemon todo data. Type alignment, tree
construction, renderer updates, and verification are not independently shippable in smaller slices
without leaving the pane half-working.

## Current codebase state (verified during fix-mode regrounding, round 2)

- `teleclaude/api_models.py:204-226` defines the canonical `TodoDTO`. It has
  `lifecycle_phase` (line 224), `integration_phase` (line 225), `finalize_status` (line 226),
  `delivered_at` (line 223), `after` (line 221), `group` (line 222). It does **not** have
  `todo_path`, `todo_dir`, **or `dor_score`** — none of those are on the contract today.
- `frontend/lib/api/types.ts` re-exports everything from `./generated-types` via
  `export * from "./generated-types"`. `TodoInfo` is generated, not hand-edited.
- `frontend/lib/api/generated-types.ts:393-413` currently exposes the stale `TodoInfo` shape
  with `prepare_phase?: string | null` (line 410) **and a stale `dor_score?: number | null`
  (line 403)**. This file is auto-generated from `teleclaude/api_models.py` by
  `teleclaude/codegen/pydantic_to_typescript.py`, invoked via `make generate-types`
  (Makefile:177-178: `uv run -m teleclaude.codegen.pydantic_to_typescript`). Regenerating
  renames `prepare_phase` to `lifecycle_phase` **and removes `dor_score`** because neither the
  current `TodoDTO` nor any other DTO in `api_models.py` declares `dor_score`. Codegen is the
  only sanctioned way to align `TodoInfo` with `TodoDTO`.
- `frontend/lib/__tests__/preparation-panel.test.ts` is the approved data-layer spec surface.
  Its `makeTodo` factory still produces `prepare_phase` (line 64), `todo_dir` (line 68), and
  `dor_score` defaults; several tests pass `dor_score: N` and assert on `dor:N` tags
  (lines 382, 481, 491–504). Per `software-development/policy/testing` — Test Spec Immutability
  — the builder may not delete or weaken behavioral assertions. Spec revisions driven by the
  approved backend contract (this fix mode, plan-drafter authority) are sanctioned: where a
  spec asserts behavior on a field the contract does not provide, the spec is defective and
  must be revised in the same task that aligns the contract (Task 1).
- `frontend/components/__tests__/PreparationView.test.tsx` is the approved render-level spec
  surface. It references `prepare_phase` (lines 24, 136) and `dor_score` (line 130). It
  currently covers SC-2 hierarchy only (four `it.fails` cases at lines 230, 271, 320, 342).
- `frontend/e2e/preparation.spec.ts` exists with three `test.skip` Playwright scaffolds. The
  frontend has no `@playwright/test` dependency installed, no `playwright.config.ts`, and no
  fixture data path. SC-8 requires the smoke to **pass**, so the missing setup must be delivered
  in this work item.
- `teleclaude/cli/tui/widgets/todo_row.py:47-96` is the grounded reference for both cascade
  behavior **and lifecycle display labels**:
  - `_LIFECYCLE_PHASE_LABELS` (lines 47–60) maps canonical `LifecyclePhase` enum values to
    TUI display labels — the labels users actually read. Two lifecycle phases collapse onto
    one display label by design:
      | Lifecycle phase enum value (`lifecycle_phase` string) | TUI display label |
      | --- | --- |
      | `draft` | `draft` |
      | `input_assessment` | `discovery` |
      | `triangulation` | `discovery` |
      | `requirements_review` | `requirements` |
      | `test_spec_build` | `requirements` |
      | `test_spec_review` | `requirements` |
      | `plan_drafting` | `planning` |
      | `plan_review` | `planning` |
      | `gate` | `planning` |
      | `grounding_check` | `planning` |
      | `re_grounding` | `planning` |
      | `prepared` | `ready` |
      | `requirements_human_approval` | _no label — phase emits no prepare-lane indicator_ |
  - `lifecycle_phase_label()` (line 66) returns `(prefix, value, color)` — the value is the
    display label, never the raw lifecycle ID. Color is green when
    `is_settled_ok_phase(phase)` (`PREPARED` or `REVIEW_APPROVED`), gold otherwise.
  - `integration_phase_label(phase, finalize_status)` returns labels for `started`,
    `delivered`, and — when `phase` is null — derives `ready` from `finalize_status="ready"`
    and `queued` from `finalize_status="handed_off"`.
- `teleclaude/core/next_machine/lifecycle.py:128-135` `is_settled_ok_phase` returns True only
  for `LifecyclePhase.PREPARED` and `LifecyclePhase.REVIEW_APPROVED`.
- `teleclaude/types/lifecycle.py:51-69` defines `PREPARE_LIFECYCLE_PHASES` and
  `WORK_LIFECYCLE_PHASES` frozensets. These are the canonical prepare-lane vs work-lane sets the
  TUI uses to disambiguate `lifecycle_phase` values.
- `docs/third-party/playwright/` (added in this fix round) holds indexed third-party research
  for `@playwright/test` install, `playwright.config.ts` shape, and selector/assertion patterns.
  Snippet IDs: `third-party/playwright/install`, `third-party/playwright/config`,
  `third-party/playwright/selectors-and-assertions`. The plan grounds Task 7 commands and config
  shapes against these snippets, satisfying DOR Gate 5 for the introduced Playwright tooling.
  These snippet IDs are now retrievable via `telec docs index --third-party` and
  `telec docs get third-party/playwright/<slug>`. The third-party `index.yaml` is regenerated by
  `telec sync` (or `telec sync --warn-only` when unrelated validation findings would otherwise
  block the build), and the regenerated `docs/third-party/index.yaml` is the file that backs the
  index/get queries. Builders and reviewers should run one of those sync forms after pulling this
  branch to pick up the Playwright entries on a clean machine.

## Field rename and contract-shrink impact (cross-task invariant)

The codegen regeneration in Task 1 renames `TodoInfo.prepare_phase` → `lifecycle_phase` and
**removes `dor_score`** because the current `TodoDTO` does not declare it. Every test fixture,
factory, comment, and assertion that references `prepare_phase`, `todo_dir`, or `dor_score`
must be updated to the regenerated contract during Task 1 — the same commit that regenerates
the type — so subsequent tasks consume a stable shape. Two distinct categories of update:

1. **Rename** (`prepare_phase` → `lifecycle_phase`): structural refactor preserving behavioral
   assertions. Per testing policy this is allowed without weakening the spec.
2. **Spec revision driven by backend contract** (`dor_score` removal, `todo_dir` removal):
   `dor_score` is not on the backend contract today and is not rendered by the TUI either
   (`grep -n dor_score teleclaude/cli/tui/widgets/todo_row.py` returns nothing). The plan
   reviewer's findings explicitly authorize revising SC-3/test expectations so the frontend
   does not plan to render or typecheck a field the backend does not provide. Task 1 therefore
   removes `dor_score` from the spec fixtures and removes the spec assertions that depend on
   `dor:N` output. The "DOR score if available" requirement remains satisfied in spirit:
   when the backend later exposes `dor_score`, regenerating the type and the cascade's already
   defensive narrowing produce the indicator without further plan changes (see Task 3).

Subsequent tasks (Tasks 3, 4, 5, 6) consume the regenerated type. Tests that were testing a
phantom feature do not measure delivery; tests that test the contract field set do.

**Test Spec Immutability reconciliation:** The testing policy states builders may not delete
or weaken spec tests. This plan does not violate that policy — it applies it correctly.
Test Spec Immutability protects behavioral intent from builder drift. When the backend
contract removes a field (`dor_score`), assertions on that field are not behavioral guards —
they are type errors that prevent compilation. The builder cannot satisfy them because the
field does not exist. Removing a compile-blocking assertion on a phantom field preserves the
spec's behavioral intent (test the actual contract) while respecting the constraint (do not
weaken coverage of real behavior). The rename (`prepare_phase` → `lifecycle_phase`) preserves
every behavioral assertion — only the field name changes, not the tested behavior.

## SC-4 verification reconciliation: `lifecycle_phase=blocked` (cross-task invariant)

The approved SC-4 verification text reads, in part: *"A todo with `lifecycle_phase=blocked`
renders in red."* That example does not correspond to a constructible state on the backend
contract:

- `teleclaude/types/lifecycle.py:18-43` defines the canonical `LifecyclePhase` enum. Its members
  are `draft`, `input_assessment`, `triangulation`, `requirements_review`,
  `requirements_human_approval`, `test_spec_build`, `test_spec_review`, `plan_drafting`,
  `plan_review`, `gate`, `grounding_check`, `re_grounding`, `prepared`, `build_started`,
  `build_complete`, `review_changes_requested`, `review_approved`, `finalize_ready`,
  `handed_off`. **There is no `blocked` lifecycle phase.**
- `lifecycle_phase_label()` (`teleclaude/cli/tui/widgets/todo_row.py:66-77`) only produces two
  colors for the prepare-lane lifecycle indicator: green for the settled-ok terminals
  (`PREPARED`, `REVIEW_APPROVED`) and gold for everything else. It never emits red. Red is only
  reachable in the TUI for non-lifecycle signals (e.g., a deferrals/work-lane status whose
  value is the literal string `"blocked"`).

Plan-drafter authority resolves this contradiction without weakening the SC-4 color policy:

1. **The color policy stands as written.** Success → green, in-progress → gold, failure/blocked
   → red. The `getPhaseTagColor("blocked")` and `getPhaseTagColor("failed")` helper paths
   continue to return red so the renderer is correct the moment the backend ever surfaces a red
   value through any cascade branch.
2. **The SC-4 verification path for the red rendering is sourced from a contract value that is
   actually constructible: the work-lane `deferrals_status` field.** When `deferrals_status` is
   the literal string `"blocked"`, the work-phase branch of the cascade emits a
   `deferrals:blocked` tag, and the renderer applies the red color token. This is the only
   contract-grounded way to drive the red rendering today, and it is the path the plan and
   specs deliver.
3. **The verification quote stays verbatim in the SC-4 task block per preparation-artifact
   quality policy** (artifacts must carry the upstream requirement text verbatim — the source
   text is the contract). The reconciliation note above is the plan-drafter's recorded mismatch
   between the verbatim quote and the actual contract; the task body is traceable to the
   reconciled red path.

If the backend later adds a `blocked` member to `LifecyclePhase` (or otherwise causes the
prepare-lane cascade to emit `prepare:blocked`), `getPhaseTagColor("blocked")` already maps to
red — no further plan changes are required to satisfy the literal SC-4 example.

---

## Task 1: Regenerate `TodoInfo` from backend `TodoDTO` and align test fixtures (SC-1)

**Requirement criterion (verbatim from `requirements.md` SC-1):**

> The TypeScript `TodoInfo` interface consumed by the preparation view must match the backend `TodoDTO` contract. [inferred] The generated frontend API type output is stale: it exposes `prepare_phase` while the backend sends `lifecycle_phase`, and it must include every backend-provided field consumed by the preparation view. Regenerating the codegen output brings the frontend type into alignment.
>
> [inferred] Required fields from `TodoDTO` that must be present and correctly named on `TodoInfo`: `after` (dependency list), `group` (group membership), `lifecycle_phase` (canonical lifecycle state — replaces stale `prepare_phase`), `integration_phase`, `finalize_status`, `delivered_at`.
>
> [inferred] The `pydantic-to-typescript-codegen` todo is listed as a dependency in the input but marked non-blocking. Regenerating the codegen output is a mechanical step within scope of this work.
>
> **Verification**: The regenerated `TodoInfo` type includes `lifecycle_phase` (not `prepare_phase`) and all other `TodoDTO` fields. Existing consumers continue to compile after the rename.

**What**:

1. Run the project codegen tool to regenerate `frontend/lib/api/generated-types.ts` from
   `teleclaude/api_models.py`:
   ```sh
   make generate-types
   ```
   This invokes `uv run -m teleclaude.codegen.pydantic_to_typescript` and overwrites the generated
   file. After regeneration, `TodoInfo` must expose `lifecycle_phase` (replacing `prepare_phase`)
   and include `after`, `group`, `integration_phase`, `finalize_status`, `delivered_at`. It must
   **not** include `todo_path` or `todo_dir` because `TodoDTO` does not declare those fields.
2. Do not hand-edit `frontend/lib/api/types.ts`. The hand-written file already re-exports
   `./generated-types`; no new manual fields are added there.
3. Update the test factory in `frontend/lib/__tests__/preparation-panel.test.ts`:
   - In `makeTodo`, rename the default `prepare_phase: null` (line 64) to `lifecycle_phase: null`
     and **remove** the `todo_dir: null` default (line 68) **and the `dor_score: null` default
     at line 57**. Drop the `todo_dir` and `dor_score` mentions from the factory comment.
   - Update the SC-1 type-completeness behavioral guard test currently named
     `"buildPreparationTree exposes finalize_status and todo_dir on the tree node ..."` to
     `"buildPreparationTree exposes finalize_status on the tree node ..."` and remove the
     `todo_dir` portion of the fixture and assertion. The `finalize_status` portion of the
     assertion stays. This is a structural alignment with the approved `TodoDTO` field set —
     `todo_dir` was never on the contract, so the assertion's intent (passthrough of contract
     fields) is preserved on the actual contract field.
   - Update the SC-1 cascade test name and body from `prepare_phase` to `lifecycle_phase`. The
     test currently named `"deriveTodoPhaseTags reads prepare_phase from TodoInfo (current
     implementation ignores it)"` becomes `"deriveTodoPhaseTags reads lifecycle_phase from
     TodoInfo (current implementation ignores it)"`. The fixture's `prepare_phase: "requirements"`
     becomes `lifecycle_phase: "requirements_review"` (matching the canonical lifecycle phase ID
     that maps to the TUI display label `requirements`). The fixture **must drop**
     `dor_score: 6` because `dor_score` is no longer on `TodoInfo`. The renamed test's behavioral
     assertion changes from "the cascade returns at least one tag including a `dor:` tag" to
     "the cascade returns at least one tag — the `prepare:requirements` indicator." This is a
     spec revision driven by the backend contract (see "Field rename and contract-shrink impact"
     above), not a weakening of the original behavioral intent (the cascade reads the lifecycle
     field). **Keep the `it.fails` marker** — the test still fails until Task 3 implements the
     cascade.
   - Update the comment block at lines 182-196 to refer to `lifecycle_phase` and drop the
     `todo_dir` and `dor_score` mentions.
   - **Revise SC-3 DOR-related expected-failure tests** in the
     `SC-3: phase priority cascade (deriveTodoPhaseTags)` describe block, in this same task,
     because the regenerated `TodoInfo` cannot accept `dor_score`:
     - The test at lines 376–388 (`prepare-lane lifecycle phase active → returns prepare:value
       tag, integration:value not present, plus dor:N when dor_score set`): drop the
       `dor_score: 6` fixture field and revise the test name and assertions to remove the
       `dor:` portion. Renamed test name: `prepare-lane lifecycle phase active → returns
       prepare:{display_label} tag, integration:value not present`. The remaining assertion
       continues to pin: at least one `prepare:` tag, no `integration:` tag.
     - The test at lines 471–488 (`work phase active → returns build/review/findings/deferrals
       tags, plus dor:N when dor_score set`): drop the `dor_score: 8` fixture field and revise
       the test name and assertions to remove the `dor:` portion. Renamed test name:
       `work phase active → returns build/review/findings/deferrals tags`. The remaining
       assertions continue to pin the work-phase tag set.
     - The test at lines 490–506 (`DOR score only, no active prepare/integration/work phase →
       returns dor:N tag (cascade priority 4)`): replace this expected-failure test with a new
       expected-failure test named `no active prepare/integration/work phase → returns empty
       tag list (cascade priority 4 returns empty when no other phase signal is present)`.
       Fixture is a todo with `lifecycle_phase: null`, `integration_phase: null`,
       `build_status: null` (or `"pending"`). Assertion: `expect(tags).toEqual([])`. This is
       the contract-aligned shape of priority 4: when no other phase signal is present and the
       backend has no `dor_score` to surface, the cascade emits nothing. The behavioral intent
       of the original test (priority-4 fallthrough behavior) is preserved on the contract that
       actually exists. **Keep the `it.fails` marker.**
   - **Restructure SC-4 helper-test block to remove the forbidden table-driven pattern.** The
     existing `SC-4: phase value color semantics (getPhaseTagColor)` describe block at
     `frontend/lib/__tests__/preparation-panel.test.ts:531-559` packages thirteen
     `getPhaseTagColor(value)` cases inside a `for (const { value, expected } of colorCases)`
     iterator. `software-development/policy/testing` §"Parametrized / table-driven tests"
     forbids this pattern unconditionally: "There is no legitimate use of parametrize — by
     construction it either packages redundant runs (delete the duplicates) or smuggles
     distinct paths under one body (split into named tests)." The thirteen cases collapse to
     **four distinct color-mapping paths**, one per branch of `getPhaseTagColor`. Replace the
     `colorCases`/`for` loop with the following four named expected-failure specs (one
     representative input per path; the rest are redundant runs through the same path and are
     deleted, not preserved). Keep them inside the same `describe("SC-4: phase value color
     semantics (getPhaseTagColor)", …)` block so the SC-4 test home stays single:

     1. `it.fails("returns 'green' for terminal-success values like 'prepared'")` — calls
        `getPhaseTagColor("prepared")` and asserts it equals `"green"`. This pins the
        success-value branch.
     2. `it.fails("returns 'gold' for in-progress values like 'discovery'")` — calls
        `getPhaseTagColor("discovery")` and asserts it equals `"gold"`. This pins the
        in-progress-value branch.
     3. `it.fails("returns 'red' for failure/blocked values like 'blocked'")` — calls
        `getPhaseTagColor("blocked")` and asserts it equals `"red"`. This pins the
        failure/blocked-value branch.
     4. `it.fails("returns the default muted color for unrecognized values")` — calls
        `getPhaseTagColor("__unrecognized__")` and asserts the result equals the same
        default token the helper returns for any value not covered above. This pins the
        default branch — without it, a helper that hardcodes `"green"` for everything would
        slip past the other three tests for representative-recognized inputs.

     The chosen representative inputs are deliberate: `"prepared"` is the prepare-lane
     terminal that SC-4 explicitly names in green; `"discovery"` is the prepare-lane
     in-progress display label that SC-4 explicitly names in gold; `"blocked"` is the
     deferrals-status value that the work-lane cascade actually emits and that SC-4 names in
     red; the unrecognized value pins the default branch without binding it to a moving
     vocabulary. **Keep all four `it.fails` markers** — Task 3 (which adds
     `getPhaseTagColor`) is what removes them as it implements the helper.

     **Verify** during this restructuring that no SC-4 case constructs a `TodoInfo` with
     `dor_score`. The four named tests above operate on plain string inputs and never build
     a `TodoInfo`, so this confirmation is automatic for the helper-test block.
4. Update `frontend/components/__tests__/PreparationView.test.tsx`:
   - Rename the `prepare_phase` references at lines 24 and 136 to `lifecycle_phase` so the
     fixtures match the regenerated contract.
   - Drop the `dor_score: null` default at line 130 — the regenerated `TodoInfo` does not
     declare `dor_score`. No behavioral assertions in the existing render-level specs depend
     on `dor_score`, so this is a fixture-shape alignment only.
5. Update every other in-tree consumer that still references the renamed/removed fields. Search
   the frontend tree for `prepare_phase`, `todo_dir`, and `dor_score` after regeneration and
   update all hits to `lifecycle_phase` / drop, as applicable. Confirmed pre-edit hit list:
   `frontend/components/preparation/TreeNode.tsx:114-116` (existing `todo.dor_score` rendering
   block must be removed — the field is no longer typed) and `frontend/lib/preparation/tree.ts:66`
   (the existing `if (todo.dor_score !== null && todo.dor_score !== undefined)` branch must be
   removed because the field is no longer typed). Tasks 3 and 6 will cover the cascade and
   renderer rebuild — Task 1 only needs to delete the stale references so `tsc --noEmit` passes
   between tasks.

**Why**: SC-1 explicitly requires regenerated output, not a manual interface patch. The hand-edited
path the previous plan described would diverge the file from `TodoDTO` and cannot satisfy the
criterion. The codegen is the source of truth; aligning fixtures in the same task keeps the
contract change atomic and prevents downstream tasks from being blocked by `tsc` excess-property
errors.

**Verification**:

- `cd frontend && npx tsc --noEmit` succeeds. Excess-property errors that previously fired on
  `prepare_phase`/`todo_dir` no longer fire.
- The renamed SC-1 cascade test in `preparation-panel.test.ts`
  (`deriveTodoPhaseTags reads lifecycle_phase from TodoInfo ...`) **stays** marked `it.fails`
  pending Task 3. The renamed type-completeness guard test
  (`buildPreparationTree exposes finalize_status on the tree node ...`) **must pass** after
  the field/factory updates land.
- Inspect `frontend/lib/api/generated-types.ts` and confirm `TodoInfo` declares
  `lifecycle_phase?: string | null` and includes `after`, `group`, `integration_phase`,
  `finalize_status`, `delivered_at`.

**Referenced files**:
- `teleclaude/api_models.py` (read-only contract reference)
- `teleclaude/codegen/pydantic_to_typescript.py` (read-only codegen tool)
- `Makefile` (read-only — `generate-types` target)
- `frontend/lib/api/generated-types.ts` (regenerate)
- `frontend/lib/api/types.ts` (read-only — re-exports the generated type)
- `frontend/lib/__tests__/preparation-panel.test.ts` (rename field references in factory, comments,
  and SC-1 tests; drop `todo_dir` content)
- `frontend/components/__tests__/PreparationView.test.tsx` (rename field references in fixtures)

---

## Task 2: Dependency-ordered tree with group hierarchy (SC-2)

**Requirement criterion (verbatim from `requirements.md` SC-2):**

> Todos within a project are organized as a dependency graph, not a flat list. [inferred] Group membership establishes parent-child hierarchy. The `after` field establishes ordering via topological sort within sibling sets. Cross-group dependencies influence root ordering [inferred from TUI reference implementation]. Cyclic or external dependencies fall back to input order without errors [inferred].
>
> **Verification**: A project with todos A→B (A after B) renders B before A. A todo with `group=X` renders nested under X. Cyclic or external dependencies fall back to input order without errors.

**What**: Rewrite `buildPreparationTree` in `frontend/lib/preparation/tree.ts` to build a
dependency graph instead of a flat list. Port the ordering/hierarchy behavior from
`teleclaude/cli/tui/prep_tree.py` and shape the output for direct renderer consumption.

Implementation shape:
1. Build hierarchy from `group`: when `group` points to another todo slug in the project, nest the
   child under that todo; when `group` names a container slug that is not itself a todo, expose a
   `PreparationGroupNode` under the project.
2. Topologically sort sibling sets using `after`, ignoring external dependencies (deps to slugs not
   in the project's todo set).
3. On cycles, fall back to **input order** for the unresolved set and expose `hasCyclicDeps: true`
   on the project node so the renderer can surface a cycle indicator.
4. At the unresolved-dependency and cycle fallback branches, add a code comment explaining that
   the pane must preserve visible rows and stable order instead of erroring or dropping todos when
   dependency metadata is inconsistent (this satisfies the "no unjustified fallback paths" code
   quality DoD gate).

Interface updates on `frontend/lib/preparation/tree.ts`:
- Add nested child support to `PreparationTodoNode` (`todos` for child todos).
- Add `PreparationGroupNode` exposed via `PreparationProjectNode.groups`.
- Add `hasCyclicDeps: boolean` on `PreparationProjectNode`.
- Preserve DFS-friendly traversal order so the renderer does not re-sort.

**Why**: SC-2 is not a flat-list enhancement. The pane needs hierarchy and dependency order that
match the TUI's workflow cues. Making the node shape explicit avoids renderer-side heuristics and
keeps cycle/external fallback observable to consumers and tests.

**Verification**: Remove the `it.fails` markers from the SC-2 data-layer tests in
`frontend/lib/__tests__/preparation-panel.test.ts` so they become regular `it()` and pass:
- `todo with after:[B] renders after B within the same project` (line 254)
- `todo with group:X renders nested under a group node X` (line 273)
- `cyclic after references do not infinite-loop: tree reports cycle metadata` (line 299)

The existing regular test for unresolved external deps (line 324) must stay green.

**Referenced files**:
- `frontend/lib/preparation/tree.ts` (rewrite `buildPreparationTree`, add hierarchy types)
- `teleclaude/cli/tui/prep_tree.py` (read-only algorithm reference)
- `frontend/lib/__tests__/preparation-panel.test.ts` (existing SC-2 specs; remove `it.fails`)

---

## Task 3: Phase priority cascade with `lifecycle_phase` and finalize-status integration derivation (SC-3, SC-4)

**Requirement criterion (verbatim from `requirements.md` SC-3):**

> Phase indicators show `prefix:value` pairs with the current workflow state, not just letter abbreviations. The display follows a priority cascade (first match wins):
>
> 1. **Prepare-lane lifecycle phase active** (`lifecycle_phase` is a prepare-lane value): Show the lifecycle display stage aligned with the TUI lifecycle labeling (e.g., draft, discovery, requirements, planning, ready, blocked, prepared — not exhaustive). This covers the prepare lane [inferred from TUI reference implementation].
> 2. **Integration phase active** (`integration_phase` is non-null, or integration readiness/queue state is available through finalize status): Show the integration lifecycle stage as reported by the backend or derived by the TUI reference (e.g., started, delivered, failed, ready, queued — not exhaustive) [inferred from TUI reference implementation].
> 3. **Work phase active** (build status is non-pending): Show build, review, findings, and deferrals values.
> 4. **None of the above**: Show DOR score if available.
>
> DOR score also accompanies prepare-lane lifecycle phase and work phase displays [inferred from TUI reference].
>
> **Verification**: A todo with `lifecycle_phase=input_assessment` shows the lifecycle indicator. A todo with `lifecycle_phase=build_complete`, `build_status=complete`, and no active integration phase shows the work phase columns. The phase cascade produces at most one category of display per todo.

**Requirement criterion (verbatim from `requirements.md` SC-4):**

> Phase values use consistent color coding aligned with the TUI:
>
> - **Success states** (e.g., complete, approved, delivered, ready, prepared — any terminal success value): green
> - **In-progress states** (e.g., active work, discovery, requirements, planning, queued — any in-progress value): gold/amber
> - **Failure/blocked states** (e.g., blocked, failed): red
>
> **Verification**: A todo with `lifecycle_phase=prepared` renders its indicator in green. A todo with `lifecycle_phase=blocked` renders in red. A todo with `lifecycle_phase=input_assessment` renders in gold.

**What**: Rewrite `deriveTodoPhaseTags` in `frontend/lib/preparation/tree.ts` to consume
`lifecycle_phase` (not the removed `prepare_phase`) and follow the priority cascade from SC-3,
emitting **TUI display labels** for the prepare lane (not raw lifecycle IDs) and using
finalize-status-derived integration display. Add a `getPhaseTagColor` helper covering the SC-4
mapping.

Two new constants in `frontend/lib/preparation/tree.ts`:

1. `PREPARE_LANE_PHASES: ReadonlySet<string>` — mirrors
   `teleclaude/types/lifecycle.py` `PREPARE_LIFECYCLE_PHASES`. Contents:
   `["draft", "input_assessment", "triangulation", "requirements_review",
   "requirements_human_approval", "test_spec_build", "test_spec_review", "plan_drafting",
   "plan_review", "gate", "grounding_check", "re_grounding", "prepared"]`. Add a code comment
   pointing to the source file and the line range so future contract changes are easy to track.
2. `LIFECYCLE_DISPLAY_LABELS: Readonly<Record<string, string>>` — mirrors
   `_LIFECYCLE_PHASE_LABELS` in `teleclaude/cli/tui/widgets/todo_row.py:47-60`. Use the exact
   mapping documented in the "Current codebase state" table above. Phases with no display
   label (e.g., `requirements_human_approval`) are absent from the map; the cascade treats
   "no entry" the same as the TUI's `lifecycle_phase_label()` returning `None` — no prepare-lane
   indicator is emitted, and the cascade falls through to the next priority.

Cascade (first match wins):
1. **Prepare-lane lifecycle phase active**: `lifecycle_phase` is in `PREPARE_LANE_PHASES`
   **and** has an entry in `LIFECYCLE_DISPLAY_LABELS` → emit
   `prepare:{LIFECYCLE_DISPLAY_LABELS[lifecycle_phase]}`. Examples grounded in the table:
   - `lifecycle_phase: "input_assessment"` → emit `prepare:discovery`.
   - `lifecycle_phase: "plan_drafting"` → emit `prepare:planning`.
   - `lifecycle_phase: "prepared"` → emit `prepare:ready`.
   No `dor:` accompaniment is emitted (the regenerated `TodoInfo` does not declare
   `dor_score`).
2. **Integration phase active**: `integration_phase` is non-null **or** `integration_phase` is
   null and `finalize_status` is one of the recognized integration-readiness values →
   emit `integration:{value}`, where:
   - `integration_phase === "started"` → `integration:started`
   - `integration_phase === "delivered"` → `integration:delivered`
   - `integration_phase` null and `finalize_status === "ready"` → `integration:ready`
   - `integration_phase` null and `finalize_status === "handed_off"` → `integration:queued`
3. **Work phase active**: `build_status` non-null and not `"pending"` → emit `build:{value}`,
   plus `review:{value}` (when `review_status` present), `findings:{count}` (when
   `findings_count > 0`), and `deferrals:{value}` (when `deferrals_status` present). No `dor:`
   accompaniment is emitted (same reason).
4. **Default (no signals)**: emit an empty list. The frontend has no `dor_score` to surface
   today; if the backend later adds `dor_score` to `TodoDTO` and codegen brings it back onto
   `TodoInfo`, this branch can be extended with a defensive `'dor_score' in todo` narrowing
   without other plan changes.

The cascade must produce **at most one** of the prepare/integration/work category indicators
per todo.

Prepare-lane vs work-lane disambiguation: a `lifecycle_phase` value that is not in
`PREPARE_LANE_PHASES` (e.g., `build_complete`) falls through the prepare branch, which is what
allows work-lane lifecycle values to fall through to step 3 when `build_status` is also set.

Color helper `getPhaseTagColor(value: string)` mapping (input is the **value** portion of
`prefix:value`, i.e., the display label or value emitted by the cascade):
- Green: `complete`, `approved`, `delivered`, `ready`, `prepared`.
- Gold: `input_assessment`, `discovery`, `requirements`, `planning`, `queued`, `started`.
- Red: `blocked`, `failed`.
- Default: an explicit muted/default color for unrecognized values.

Note that the helper accepts both display labels (`discovery`, `planning`, `ready`) and the
canonical raw values that flow through `integration:` / `build:` / `deferrals:` tags
(`started`, `delivered`, `queued`, `complete`, `blocked`, `failed`). The reviewer's existing
SC-4 unit tests at line 552 already test the helper directly with these tokens.

**Why**: SC-3 is keyed on `lifecycle_phase`, the canonical pointer in `TodoDTO`. The previous
plan referenced the removed `prepare_phase` field, which would mean the cascade reads a field that
no longer exists after Task 1 regeneration. The TUI's `lifecycle_phase_label()` /
`integration_phase_label()` pair in `teleclaude/cli/tui/widgets/todo_row.py:66-96` is the grounded
reference for the prepare/integration/finalize-status logic; mirroring it keeps web and TUI behavior
identical. A shared color helper is needed because Task 4 also consumes color decisions.

**Verification** — make these expected-failure tests in
`frontend/lib/__tests__/preparation-panel.test.ts` GREEN by removing their `it.fails` markers:
- The renamed SC-1 cascade test (`deriveTodoPhaseTags reads lifecycle_phase from TodoInfo ...`).
  Note Task 1 already revised the fixture to set `lifecycle_phase: "requirements_review"` so the
  cascade output includes `prepare:requirements`. The behavioral assertion now reads "the
  cascade emits at least one tag including a `prepare:` prefix."
- The remaining SC-3 cascade `it.fails` tests in the `SC-3: phase priority cascade
  (deriveTodoPhaseTags)` describe block, after Task 1's spec revisions:
  - The test that pins prepare-lane → no integration tag (Task 1 renamed; the assertion is
    "at least one `prepare:` tag, no `integration:` tag"). The fixture's
    `lifecycle_phase: "requirements_review"` means the emitted tag is `prepare:requirements`.
  - The integration-active tests (use the `integration:` family — no fixture-shape change beyond
    `prepare_phase` → `lifecycle_phase` rename).
  - The work-active test (Task 1 renamed; the assertion is "the work-phase tag set is emitted").
    The fixture must drop the old `dor_score: 8` (Task 1) and use a work-lane `lifecycle_phase`
    such as `build_complete` along with `build_status: "complete"`.
  - The findings/deferrals work-active test (rename `prepare_phase`; behavioral assertion
    unchanged).
  - The priority-4 fallthrough test (Task 1 reshaped: now asserts the cascade returns `[]` when
    no other phase is present).
- All four named SC-4 `it.fails` color-mapping cases that Task 1 wrote in place of the
  forbidden parametrize block — `returns 'green' for terminal-success values like
  'prepared'`, `returns 'gold' for in-progress values like 'discovery'`, `returns 'red' for
  failure/blocked values like 'blocked'`, and `returns the default muted color for
  unrecognized values`. Implementing `getPhaseTagColor` must satisfy all four named paths.
  The helper accepts plain string tokens, so no `TodoInfo` fixture is constructed in this
  block.
- The empty-array baseline test in SC-3 must remain green.

In addition, **add** these new render-level expected-failure specs to
`frontend/components/__tests__/PreparationView.test.tsx` and make them GREEN within this task
(per the testing policy, adding new tests is allowed):
- `renders a visible phase-indicator element with prefix:value text for a todo with active lifecycle_phase`
  — render a row for a todo with `lifecycle_phase: "input_assessment"`. Assert
  `data-testid="phase-indicator"` is present and its text matches `/^prepare:discovery$/`. This
  test serves as the grounded check that the renderer surfaces the **TUI display label**, not
  the raw lifecycle ID.
- `applies success color token to phase indicators with terminal-success values`
  — render a row for a todo with `lifecycle_phase: "prepared"`. Assert the rendered indicator
  carries the same exposed color token (class name, data attribute, or inline style attribute)
  that the renderer plumbs from `getPhaseTagColor("ready")` (the display label for
  `prepared`). Token comparison is structural, not visual.
- `applies failure color token to phase indicators with failure/blocked values`
  — render a row for a todo whose work-lane cascade emits a `:blocked` value: fixture is
  `lifecycle_phase: "build_complete"` (a work-lane lifecycle value, not a prepare-lane one,
  so step 1 of the cascade does not match), `integration_phase: null`,
  `build_status: "complete"`, `deferrals_status: "blocked"`. The cascade therefore reaches
  step 3 and emits `deferrals:blocked` among the work-phase tags. Assert that the rendered
  indicator carrying the `blocked` value carries the color token that
  `getPhaseTagColor("blocked")` produces (red).

  **Reconciliation reminder (cross-reference the "SC-4 verification reconciliation" header
  above):** the SC-4 verification text names `lifecycle_phase=blocked` as the red example.
  That state is not constructible — the `LifecyclePhase` enum has no `blocked` member — so
  this plan delivers the red rendering through the only contract-grounded path that can
  surface a `:blocked` value today: the work-lane `deferrals_status` field. Plan-drafter
  authority resolves the contradiction; the SC-4 color policy itself is unchanged.
- `applies in-progress color token to phase indicators with in-progress values`
  — render a row for a todo with `lifecycle_phase: "input_assessment"`. Assert the indicator
  carries the color token that `getPhaseTagColor("discovery")` produces (gold). This pins
  SC-4's gold rendering path independent of the success-color test above.

These three render-level color tests cover the SC-4 verification trio (green, red, gold) at the
component level, complementing the helper-only SC-4 unit tests in
`preparation-panel.test.ts:552`. Per the preparation-artifact-quality DoD-driven review-awareness
rule, this prevents a renderer that hardcodes the success token from passing review while
silently failing the blocked/in-progress paths.

**Referenced files**:
- `frontend/lib/preparation/tree.ts` (rewrite `deriveTodoPhaseTags`, add `getPhaseTagColor`,
  add `PREPARE_LANE_PHASES`, add `LIFECYCLE_DISPLAY_LABELS`)
- `teleclaude/cli/tui/widgets/todo_row.py` (read-only — cascade and label reference,
  lines 47-96)
- `teleclaude/types/lifecycle.py` (read-only — prepare-lane phase set reference, lines 51-69)
- `teleclaude/core/next_machine/lifecycle.py` (read-only — `is_settled_ok_phase` reference,
  lines 128-135)
- `frontend/lib/__tests__/preparation-panel.test.ts` (existing SC-3/SC-4 specs — remove
  `it.fails` markers; Task 1 owns the fixture-shape revisions referenced above)
- `frontend/components/__tests__/PreparationView.test.tsx` (add render-level SC-3 visibility
  and SC-4 green/red/gold color-application specs)

---

## Task 4: Status block indicator from `lifecycle_phase` (SC-5, SC-7)

**Requirement criterion (verbatim from `requirements.md` SC-5):**

> Todo nodes display a colored block character instead of a generic folder icon. The block encodes lifecycle status:
>
> - Filled block in green: delivered
> - Filled block in gold: active/in-progress/ready status
> - Empty block in gray: draft/pending status
>
> [inferred] The existing status pill may coexist with or be replaced by the block indicator — this is a visual design decision for the builder.
>
> **Verification**: A delivered todo shows a green filled block. A draft todo shows a gray empty block. An active todo shows a gold filled block.

**Requirement criterion (verbatim from `requirements.md` SC-7):**

> Recently delivered todos (those with a delivered timestamp within the display window) render with the green status block indicator. The delivered timestamp is already available from the backend via `delivered_at`.
>
> **Verification**: A todo with a `delivered_at` timestamp and delivered status renders with the green filled block indicator.

**What**: Add `getTodoStatusBlock(todo: TodoInfo)` to `frontend/lib/preparation/tree.ts`,
returning `{ color: "green" | "gold" | "gray"; filled: boolean }`. The renderer maps that
struct to the visible block character/class.

Rules (in order):
1. Delivered: `status === "delivered"` **or** `delivered_at` present → `{ color: "green",
   filled: true }`.
2. Active lifecycle: `lifecycle_phase` is a prepare-lane value (uses the same
   `PREPARE_LANE_PHASES` set introduced in Task 3) → `{ color: "gold", filled: true }`.
   When `lifecycle_phase === "prepared"`, return `{ color: "green", filled: true }`
   (a settled-success terminal in the prepare lane).
3. Active integration: `integration_phase` is non-null, **or** `finalize_status` is
   `"ready"`/`"handed_off"` → `{ color: "gold", filled: true }`. When `integration_phase ===
   "delivered"`, return `{ color: "green", filled: true }`.
4. Active work: `build_status` is non-null and not `"pending"` → `{ color: "gold", filled: true }`.
5. Status-derived active: `status === "active"` or `status === "ready"` → `{ color: "gold",
   filled: true }` (this disambiguates the existing `status:ready` vs `lifecycle_phase:prepared`
   spec case — bare `status:ready` without a settled lifecycle phase is gold; only the
   `lifecycle_phase:prepared` rule above produces green for the prepare-lane terminal).
6. Default: `{ color: "gray", filled: false }`.

**Why**: The folder icon is semantically empty. A shared helper centralizes the block decision so
the renderer stays thin and the unit tests pin the rule rather than the rendered character. Using
`lifecycle_phase` (and the same prepare-lane set as Task 3) keeps Task 3 and Task 4 consistent;
splitting them onto different lifecycle fields would fragment the contract.

**Verification** — make these expected-failure tests in
`frontend/lib/__tests__/preparation-panel.test.ts` GREEN by removing their `it.fails` markers:
- All six SC-5/SC-7 `it.fails` block-state cases, including the disambiguation case
  (`status:ready` alone → gold; `lifecycle_phase:prepared` → green). Update each fixture's
  `prepare_phase` reference to `lifecycle_phase` and drop any `dor_score` field in line with
  the Task 1 cross-cut. The disambiguation behavioral assertion is preserved on the renamed
  field.

In addition, **add** these new render-level expected-failure specs to
`frontend/components/__tests__/PreparationView.test.tsx` and make them GREEN within this task:
- `renders a status-block element with the success color for a delivered todo`
  — assert a row for a todo with `delivered_at` set has `data-testid="status-block"` and the
  green color token.
- `renders an empty status-block element with the muted color for a draft todo`
  — assert a row for a todo with no active signals has `data-testid="status-block"` and the
  gray/empty token.

**Referenced files**:
- `frontend/lib/preparation/tree.ts` (add `getTodoStatusBlock`)
- `frontend/lib/__tests__/preparation-panel.test.ts` (existing SC-5/SC-7 specs)
- `frontend/components/__tests__/PreparationView.test.tsx` (add render-level SC-5/SC-7 visibility
  specs)

---

## Task 5: Column alignment metadata (SC-6)

**Requirement criterion (verbatim from `requirements.md` SC-6):**

> Slug and property columns are visually aligned across todo rows within a project, producing scannable vertical columns. Properties do not shift horizontally based on slug length.
>
> [inferred] The TUI uses dot-leader padding between slug and columns with computed column widths. The web implementation achieves equivalent visual alignment using an appropriate CSS or layout technique.
>
> **Verification**: Two todos with different slug lengths have their phase indicators starting at the same horizontal position. The alignment is visually consistent across all visible todos.

**What**: Compute per-project alignment metadata in `buildPreparationTree` and expose it on the
project node so the renderer can keep phase columns vertically aligned across todo rows.

Minimum contract:
- `PreparationProjectNode.maxSlugLength: number`.
- The value covers all visible todos in that project, including nested descendants exposed via
  Task 2.

The renderer (Task 6) reserves a slug column wide enough for `maxSlugLength` characters so phase
indicators start at the same horizontal offset across rows.

**Why**: The renderer needs a shared width baseline to keep property columns stable when slug
lengths vary. Computing this in the tree layer makes alignment deterministic and testable instead
of relying on incidental DOM layout.

**Verification** — make this expected-failure test GREEN:
- `project node exposes maxSlugLength so consumers can align phase columns` in
  `frontend/lib/__tests__/preparation-panel.test.ts`.

In addition, **add** this new render-level expected-failure spec to
`frontend/components/__tests__/PreparationView.test.tsx` and make it GREEN within this task:
- `renders todo rows with a fixed-width slug column derived from project maxSlugLength`
  — assert that two todo rows with different slug lengths share the same computed slug-column
  width (e.g., `data-slug-col-width` attribute or CSS variable populated from the project
  metadata). Assert on the structural attribute the renderer consumes, not on visual pixels — the
  Playwright smoke in Task 7 owns the rendered-pixel alignment check.

**Referenced files**:
- `frontend/lib/preparation/tree.ts` (compute and expose metadata)
- `frontend/lib/__tests__/preparation-panel.test.ts` (existing SC-6 spec)
- `frontend/components/__tests__/PreparationView.test.tsx` (add render-level SC-6 layout spec)

---

## Task 6: PreparationView hierarchy flattening and TreeNode rendering updates (SC-2, SC-3, SC-4, SC-5, SC-6)

**Requirement criteria (verbatim from `requirements.md` — this task is the renderer-side delivery
for SC-2 through SC-6 component-level visibility):**

> **SC-2: Dependency-ordered tree**
>
> Todos within a project are organized as a dependency graph, not a flat list. [inferred] Group membership establishes parent-child hierarchy. The `after` field establishes ordering via topological sort within sibling sets. Cross-group dependencies influence root ordering [inferred from TUI reference implementation]. Cyclic or external dependencies fall back to input order without errors [inferred].
>
> **Verification**: A project with todos A→B (A after B) renders B before A. A todo with `group=X` renders nested under X. Cyclic or external dependencies fall back to input order without errors.

> **SC-3: Structured phase display with priority**
>
> Phase indicators show `prefix:value` pairs with the current workflow state, not just letter abbreviations. The display follows a priority cascade (first match wins):
> 1. Prepare-lane lifecycle phase active (`lifecycle_phase` is a prepare-lane value): Show the lifecycle display stage aligned with the TUI lifecycle labeling.
> 2. Integration phase active (`integration_phase` is non-null, or integration readiness/queue state is available through finalize status): Show the integration lifecycle stage.
> 3. Work phase active (build status is non-pending): Show build, review, findings, and deferrals values.
> 4. None of the above: Show DOR score if available.
>
> **Verification**: A todo with `lifecycle_phase=input_assessment` shows the lifecycle indicator. A todo with `lifecycle_phase=build_complete`, `build_status=complete`, and no active integration phase shows the work phase columns. The phase cascade produces at most one category of display per todo.

> **SC-4: Color semantics**
>
> Phase values use consistent color coding aligned with the TUI:
> - Success states (e.g., complete, approved, delivered, ready, prepared): green
> - In-progress states (e.g., active work, discovery, requirements, planning, queued): gold/amber
> - Failure/blocked states (e.g., blocked, failed): red
>
> **Verification**: A todo with `lifecycle_phase=prepared` renders its indicator in green. A todo with `lifecycle_phase=blocked` renders in red. A todo with `lifecycle_phase=input_assessment` renders in gold.

> **SC-5: Status block indicator**
>
> Todo nodes display a colored block character instead of a generic folder icon. The block encodes lifecycle status:
> - Filled block in green: delivered
> - Filled block in gold: active/in-progress/ready status
> - Empty block in gray: draft/pending status
>
> **Verification**: A delivered todo shows a green filled block. A draft todo shows a gray empty block. An active todo shows a gold filled block.

> **SC-6: Column alignment**
>
> Slug and property columns are visually aligned across todo rows within a project, producing scannable vertical columns. Properties do not shift horizontally based on slug length.
>
> **Verification**: Two todos with different slug lengths have their phase indicators starting at the same horizontal position. The alignment is visually consistent across all visible todos.

**What**: Update `frontend/components/preparation/PreparationView.tsx` and
`frontend/components/preparation/TreeNode.tsx` so the pane renders the hierarchy and metadata from
Tasks 2-5.

Required changes:
1. Expand the flattened node model to support `group` rows and nested todo descendants.
2. Replace the current flat traversal with recursive DFS over project groups, root todos, nested
   child todos, and file rows.
3. Extend expand/collapse behavior so project rows, group rows, and todo rows with child todos/files
   each own their own expansion state.
4. Render todo rows with the block indicator from `getTodoStatusBlock`, attaching
   `data-testid="preparation-todo-node"` on the row surface and `data-testid="status-block"` on
   the block element. The block must use the color token from the helper so SC-5/SC-7 component
   tests can assert on it.
5. Replace the current phase-tag rendering with visible `prefix:value` indicators colored via
   `getPhaseTagColor`, attaching `data-testid="phase-indicator"`. Each indicator's color is exposed
   as a class name or data attribute so SC-4 component tests can assert on it without prose-locking.
6. Add stable row metadata (`data-node-id`, `data-node-type`, `data-node-depth`) plus
   `data-testid="preparation-group-node"` for grouped container rows.
7. Use the project alignment metadata (`maxSlugLength`) so root and nested todo rows share the same
   phase-column start. Reserve the column width via a CSS technique (fixed-width grid column,
   `min-width`, or similar) that the SC-6 component test can assert on structurally.
8. Remove legacy duplicate DOR/findings displays once the new tag cascade is rendered.

**Why**: The data-layer tree changes are not user-visible until the pane flattener and row renderer
actually consume them. This task is the bridge between the grounded tree model and the delivered UI
behavior — it makes SC-2 through SC-6 visible to end users.

**Verification**:
- Keep the existing module smoke in place.
- Make these existing render-level expected-failure SC-2 specs in
  `frontend/components/__tests__/PreparationView.test.tsx` GREEN by removing the `it.fails`
  markers:
  - `renders explicit group nodes at the project level instead of flattening grouped todos into peer rows` (line 230)
  - `renders grouped todos as nested children under their group node in dependency order` (line 271)
  - `collapses and re-expands a group node without affecting peer root todos` (line 320)
  - `orders root nodes so a group containing a dependency renders before its dependent ungrouped todo` (line 342)
- Make GREEN the SC-3, SC-4, SC-5, SC-6, SC-7 render-level expected-failure specs added in
  Tasks 3, 4, and 5 (phase-indicator visibility + color application; status-block visibility +
  color encoding for delivered and draft; fixed-width slug column).

**Referenced files**:
- `frontend/components/preparation/PreparationView.tsx` (recursive flattening, expand/collapse,
  prop plumbing)
- `frontend/components/preparation/TreeNode.tsx` (row rendering, block indicator, phase tags,
  metadata)
- `frontend/components/__tests__/PreparationView.test.tsx` (existing render-level hierarchy specs;
  newly added Task 3/4/5 specs)

---

## Task 7: Browser smoke setup and unskipped Playwright pass (SC-8)

**Requirement criterion (verbatim from `requirements.md` SC-8):**

> The enriched preparation pane must pass a Playwright smoke test exercising the changed rendering path. The smoke test verifies the tree renders, phase indicators appear, and status indicators use the correct visual encoding.
>
> **Verification**: A Playwright test at `frontend/e2e/preparation.spec.ts` exercises the preparation view (accessible at `/?panel=preparation` or equivalent route) with representative todo data and confirms the visual elements are present.

**What**: Deliver an unskipped Playwright pass. The current `frontend/e2e/preparation.spec.ts` has
three `test.skip` scaffolds, no `@playwright/test` dependency installed, no `playwright.config.ts`,
and no fixture data wiring. SC-8 requires the smoke to pass — the previous plan's "keep the skip
when blocked" path is incompatible with the criterion and is rejected here.

This task is grounded in the Playwright third-party docs indexed in this fix round:
- `docs/third-party/playwright/install.md` (install, browser binary, package.json script)
- `docs/third-party/playwright/config.md` (`playwright.config.ts` shape, `webServer`, `use`)
- `docs/third-party/playwright/selectors-and-assertions.md` (`getByTestId`, `expect.toBeVisible`,
  `boundingBox()` and the visibility precondition).

The builder MUST deliver, in this task:

1. **Install Playwright** in `frontend/package.json`. Per the indexed install snippet, pin an
   exact version (no `^`/`~`) so the runner version and the Chromium binary revision agree:
   ```sh
   cd frontend && pnpm add -D -E @playwright/test
   cd frontend && pnpm exec playwright install --with-deps chromium
   ```
   Use `pnpm exec playwright …` (not `npx playwright …`) per the third-party doc, so the CLI
   version stays aligned with `package.json`. Add a `test:e2e` script:
   ```json
   "test:e2e": "playwright test"
   ```
2. **Create `frontend/playwright.config.ts`**. Mirror the canonical shape in
   `docs/third-party/playwright/config.md`:
   - `testDir: "./e2e"`.
   - A `webServer` clause that auto-starts the local server (`pnpm dev`) on a deterministic
     port, waits for it, tears it down after tests, and uses
     `reuseExistingServer: !process.env.CI`. Set `timeout: 120_000` (the third-party doc's
     recommended floor for cold Next.js dev startup).
   - **`webServer.env` must inject the test-only fixture flag for the spawned dev server**:
     `env: { ...process.env, NEXT_PUBLIC_E2E_FIXTURES: "1" }`. Without this, the dev server
     started by Playwright is indistinguishable from a normal dev run and the fixture loader
     short-circuits (per the 3a guard), leaving the smoke without representative data.
     Setting the env in `webServer.env` (rather than expecting the developer to export it
     in the shell) is what makes `pnpm test:e2e` work on a clean clone with no manual setup.
   - `use.baseURL` set to the same port the `webServer` clause exposes.
   - `projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }]`.
3. **Provide representative todo data** for the smoke via a **test-only fixture mode** with
   explicit security containment (the only sanctioned approach here; the alternative
   network-mock path is also acceptable and inherits the same containment rules — see point 3d
   below). The fixtures must include at least two todos with different slug lengths, at least
   one with `lifecycle_phase` set to a prepare-lane value (e.g., `input_assessment` so the
   indicator renders as `prepare:discovery`), and at least one with `delivered_at` populated,
   so the smoke tests have signal to assert on.

   **Data-flow entry point:** The preparation pane's todo data flows through
   `frontend/lib/hooks/useProjects.ts` → `fetchProjects()` → `GET /api/projects`.
   The fixture mode intercepts at the `useProjects` hook level: when the env guard passes
   (3a) and the URL contains `?fixtures=smoke`, the hook returns the static fixture data
   from `frontend/lib/preparation/__fixtures__/smoke.ts` instead of calling `fetchProjects`.
   The builder creates `frontend/lib/hooks/useFixtureProjects.ts` (or inlines the conditional
   in `useProjects.ts`) — the entry point MUST be a single named function with the env guard
   at the top so the production path is never reached in fixture mode and the fixture path is
   dead code in production. The `PreparationView` component consumes `useProjects` as it does
   today — the fixture substitution is transparent to the renderer.

   Containment rules apply because this fixture path injects in-memory data into the rendered
   preparation pane:

   - **3a. Compile-time gate (production exclusion)**: the fixture loader and any code path
     that reads `?fixtures=` from the URL MUST be guarded by
     `process.env.NODE_ENV !== "production"` **and** `process.env.NEXT_PUBLIC_E2E_FIXTURES === "1"`
     (a build-time public env var, set only in test runs and dev). The guard is enforced by an
     early-return at the entrypoint of the fixture loader so the loader is dead code in any
     production build. Add a single-line code comment at the guard explaining why both checks
     are required (defense in depth: NODE_ENV protects against a build misconfiguration; the
     dedicated env var prevents accidental exposure in dev).
   - **3b. No user-controlled data**: the fixture set is a **static import** of a TS module
     under `frontend/lib/preparation/__fixtures__/smoke.ts`. The query parameter (`fixtures=smoke`)
     selects which named static fixture to use; it is **never** parsed for arbitrary data.
     Validate the param against an allowlist (`["smoke"]`) and reject any unknown value by
     ignoring the param and falling through to the normal data path. This preserves the
     web-interface invariant that core data flows through the daemon source of truth — the
     fixture path only substitutes for the daemon during gated test/dev runs.
   - **3c. Auth boundary preserved**: the fixture path does not bypass authentication.
     Authenticated routes remain authenticated. If the preparation pane is behind auth, the
     Playwright test signs in (or runs in an authenticated test context per
     `docs/project/spec/identity-and-auth.md`) before activating the fixture query param. The
     fixture mode replaces _data_, not _identity_.
   - **3d. Alternative network-mock path**: if the builder elects an MSW-equivalent network
     mock layered on the Playwright run instead of the query-param fixture path, the same
     containment applies: the mock module must be loaded only when
     `process.env.NEXT_PUBLIC_E2E_FIXTURES === "1"` so it can never ship in a production
     bundle, and auth flows must not be replaced. Document the chosen approach in
     `quality-checklist.md`.
   - **3e. Validation point documentation**: the security review lane will verify the fixture
     guard. Record in `quality-checklist.md` under "Security boundary": the file path of the
     entrypoint that contains the env-guard, the expected behavior in production builds (the
     fixture loader returns immediately, the regular daemon code path is the only data
     source), and the test that confirms the guard (a unit test that asserts the loader
     short-circuits when `NODE_ENV === "production"`).

4. **Activate and complete the smoke cases** in `frontend/e2e/preparation.spec.ts`. Replace
   each `test.skip` with `test`. Every smoke case below must navigate using the
   fixture-selecting query parameter:
   ```ts
   await page.goto("/?panel=preparation&fixtures=smoke");
   ```
   The `fixtures=smoke` selector is the only sanctioned trigger for the static fixture
   module (per 3b above); without it the fixture loader falls through to the daemon path
   and the smoke is non-deterministic. If the preparation pane requires authentication, the
   test signs in first (per 3c) and then issues the navigation above.

   Required smoke cases — the existing three assertions stay, and the SC-5 visual-encoding
   case is added (no longer optional):

   1. **Tree renders.** `page.getByTestId("preparation-todo-node")` resolves to a non-empty
      set of locators after navigation; assert `.first()` `toBeVisible()`. Pins SC-2/SC-8
      basic visibility.
   2. **Status block characters render.** Locate `page.getByTestId("status-block")` for
      each fixture todo; assert the elements are visible and that the rendered text content
      is the block character the renderer emits (`█` for filled, `□` for empty — whichever
      pair the renderer settles on in Task 4/Task 6 must match the assertion). Pins SC-5
      character rendering.
   3. **Phase column alignment.** Locate `page.getByTestId("phase-indicator")` for two
      todos with different slug lengths in the fixture set. For each: anchor with
      `await expect(locator).toBeVisible()` (per the third-party selectors-and-assertions
      doc — `boundingBox()` on a non-visible element returns `null` and breaks the test
      flakily). Read both `boundingBox().x` values and assert they match within ±1px.
      Pins SC-6 rendered-pixel alignment.
   4. **Status-block visual encoding for delivered, active, and draft rows.** This case
      is mandatory — SC-8's verification text requires the smoke to confirm "status
      indicators use the correct visual encoding." The fixture set must include exactly
      three named rows the smoke can target: a delivered row (e.g., slug
      `smoke-delivered-row` with `delivered_at` populated), an active row (e.g., slug
      `smoke-active-row` with `lifecycle_phase: "input_assessment"`), and a draft row
      (e.g., slug `smoke-draft-row` with no active signals — bare `status: "draft"`).
      For each: locate the row by a stable selector (e.g.,
      `page.locator('[data-testid="preparation-todo-node"][data-slug="smoke-delivered-row"]')`),
      then locate the row's `status-block` descendant. Assert the rendered color encoding
      Task 6 plumbs from `getTodoStatusBlock`:

      - Delivered row's status-block carries the green color token (the same class name
        or `data-color`/CSS-variable attribute the renderer applies for
        `{ color: "green", filled: true }`).
      - Active row's status-block carries the gold color token.
      - Draft row's status-block carries the gray/muted color token.

      Token comparison is structural (class name or data attribute), not visual pixel
      diff. The selector that exposes the token (`data-color="green"`, a stable Tailwind
      class like `text-success`, etc.) is decided in Task 6 and Task 7 asserts on
      whatever the renderer commits to — the smoke must read the same attribute as the
      component-level SC-5 tests so structural drift is caught at both layers.

   The 1px tolerance from case 3 stays. Do not remove or weaken any of these four
   assertions.
5. **Wire the row hooks** the smoke depends on: `data-testid="preparation-todo-node"`,
   `data-testid="status-block"`, `data-testid="phase-indicator"`. Task 6 adds these on the
   component side; Task 7 confirms they are present on the rendered DOM under the fixture data.
6. **Run the suite locally** before commit:
   ```sh
   cd frontend && pnpm test:e2e
   ```
   All three (or four) smoke tests must pass. Record the run output and the exercised path in
   `todos/frontend-preparation-pane/quality-checklist.md` under the Build section.

**Why**: SC-8 explicitly requires a passing Playwright smoke. The previous plan's conditional-skip
fallback contradicted the requirement and would have left the work unverified at the browser
boundary required by Definition of Done (Section 3 Testing — Browser Smoke Verification). The
project already runs Next.js with a tsx server (`frontend/package.json` `dev` script), so a
`webServer` clause in `playwright.config.ts` removes the runnable-server blocker. The fixture-mode
approach removes the populated-daemon blocker. The compile-time guard plus allowlisted-param
selection preserves the web-architecture invariant that core data flows through the daemon source
of truth in any code path that ships to users (DOR Gate 6). Together they make the smoke
deterministic and runnable from a clean clone, without weakening the security boundary the web
interface depends on.

If the builder discovers a concrete blocker that cannot be resolved within scope (for example,
the daemon WebSocket cannot be cleanly bypassed even in dev mode), the builder must surface the
blocker to the orchestrator rather than ship a skipped smoke — a skipped SC-8 fails Definition
of Done.

**Verification**:
- `cd frontend && pnpm test:e2e` exits with code 0 and reports all four preparation smoke
  tests passing (no `skipped` results in the report for `preparation.spec.ts`). The four
  cases are: tree renders, status block characters, phase column alignment, and status-block
  visual encoding (green/gold/gray for delivered/active/draft).
- `frontend/playwright.config.ts` exists and contains:
  - a `webServer` block with `timeout: 120_000`,
  - a `webServer.env` clause that sets `NEXT_PUBLIC_E2E_FIXTURES: "1"` for the spawned dev
    server (so the fixture loader is active during the smoke run, per 3a above),
  - a `use.baseURL` that matches the `webServer` port.
- Every smoke case in `frontend/e2e/preparation.spec.ts` navigates with the
  `?fixtures=smoke` selector. Grep `frontend/e2e/preparation.spec.ts` and confirm every
  `page.goto(...)` invocation includes `fixtures=smoke`.
- `frontend/package.json` declares `@playwright/test` (exact-pinned) in `devDependencies` and a
  `test:e2e` script.
- The fixture loader's compile-time guard is in place: a unit test in
  `frontend/lib/preparation/__tests__/fixture-mode.test.ts` (new) asserts the loader returns
  the daemon-backed data path when `process.env.NODE_ENV === "production"` regardless of the
  query param, and asserts an unknown `fixtures=` value is ignored. Mark this test as a regular
  `it()` (not expected-failure) — it pins the security guard the moment the loader is added.
- `frontend/lib/preparation/__fixtures__/smoke.ts` exports a fixture set that includes the
  three named rows the smoke targets (`smoke-delivered-row` with `delivered_at` populated,
  `smoke-active-row` with `lifecycle_phase: "input_assessment"`, `smoke-draft-row` with
  bare `status: "draft"`) plus the two-different-slug-length pair the alignment case
  requires. The fixture set's slugs are stable so the test selectors cannot drift.
- `quality-checklist.md` records the exact command run, the resulting pass count
  (must be four passing cases, zero skipped), the chosen fixture/test-mode path, and the
  security-boundary entry described in 3e.

**Referenced files**:
- `frontend/package.json` (add `@playwright/test` exact-pinned dev dependency, `test:e2e` script)
- `frontend/playwright.config.ts` (new)
- `frontend/e2e/preparation.spec.ts` (un-skip the three existing cases, add the mandatory
  fourth SC-5 visual-encoding case, and add `fixtures=smoke` to every `page.goto`)
- `frontend/components/preparation/PreparationView.tsx` (read-only here — hooks added in Task 6)
- `frontend/components/preparation/TreeNode.tsx` (read-only here — hooks added in Task 6)
- `frontend/lib/preparation/__fixtures__/smoke.ts` (new — static fixture module)
- `frontend/lib/preparation/fixture-mode.ts` (new — env-guarded loader, allowlist for query
  param values; named per builder convention if a different file path makes more sense, but the
  loader entry MUST be a single named function with the env guard at line 1)
- `frontend/lib/preparation/__tests__/fixture-mode.test.ts` (new — unit test for the guard)
- `docs/third-party/playwright/install.md` (read-only — pinning, install command)
- `docs/third-party/playwright/config.md` (read-only — `playwright.config.ts` shape)
- `docs/third-party/playwright/selectors-and-assertions.md` (read-only — selectors and stable
  layout assertions)
- `docs/project/design/architecture/web-interface.md` (read-only — daemon-as-source-of-truth
  invariant)
- `docs/project/spec/identity-and-auth.md` (read-only — auth boundary the fixture path must not
  cross)
- `todos/frontend-preparation-pane/quality-checklist.md` (record evidence and security boundary)

---

## Task ordering

Recommended build order: 1 → 2 → 3 → 4 → 5 → 6 → 7

- Task 1 lands the `lifecycle_phase` rename and aligns all fixtures so subsequent tasks consume a
  stable type. It is the only task that must run first.
- Tasks 2, 3, 4, and 5 all live in `frontend/lib/preparation/tree.ts` and operate on the renamed
  type. They are independently testable but Task 4 reuses the prepare-lane set introduced in Task
  3, so 3 → 4 keeps the dependency clean.
- Task 6 depends on Tasks 2-5 because the renderer consumes their helpers and metadata.
- Task 7 depends on Task 6 because the Playwright smoke asserts on the row hooks and visual
  encoding the renderer ships.
