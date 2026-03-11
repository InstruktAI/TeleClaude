# Implementation Plan: prepare-phase-tiering

## Overview

Add tiered routing to the prepare state machine so well-defined inputs skip
unnecessary ceremony, fix `split_todo()` to inherit parent progress, and
refine review auto-remediation boundaries to distinguish factual corrections
from scope expansions.

The approach modifies the existing `INPUT_ASSESSMENT` phase handler to perform
tier evaluation before dispatching, adds tier persistence to `state.yaml`,
introduces phase-skip recording, and extends `split_todo()` to propagate
approved artifacts to children. Documentation updates follow mechanically
from the code changes.

## Atomicity Assessment

**Verdict: Atomic.** The code changes are ~250 lines across 3 source files.
Documentation changes are mechanical text edits. The detail level in
requirements is very high — the approach is fully known. Splitting would
create coordination overhead for tightly coupled changes (tier routing
interacts with split inheritance per R8: "a child born from an approved
parent is by definition Tier 2 or Tier 3").

## Tasks

### Task 1: Add tier fields to state schema

**What:** Add `tier`, `tier_rationale`, and `skipped_phases` fields to:
- `TodoState` in `teleclaude/types/todos.py`
- `DEFAULT_STATE` in `teleclaude/core/next_machine/core.py`

```python
# types/todos.py — new fields on TodoState
tier: int = 0  # 0=not assessed, 1=full, 2=abbreviated, 3=direct-build
tier_rationale: str = ""
skipped_phases: list[dict[str, str]] = Field(default_factory=list)
```

```python
# core.py — DEFAULT_STATE additions
"tier": 0,
"tier_rationale": "",
"skipped_phases": [],
```

**Why:** R2 requires tier persistence. R3 requires skip recording. Adding
defaults ensures backward compatibility — existing `state.yaml` files
without these fields merge cleanly via `read_phase_state()` which does
`merged = copy.deepcopy(DEFAULT_STATE); merged.update(state)`.

**Verification:** Load an existing `state.yaml` (no tier field) via
`read_phase_state()` → returns `tier=0`. `TodoState.model_validate()`
accepts dicts with and without the new fields.

**Referenced files:**
- `teleclaude/types/todos.py`
- `teleclaude/core/next_machine/core.py` (lines 896-929)

---

### Task 2: Implement tier assessment function

**What:** Add `_assess_input_tier(cwd: str, slug: str) -> tuple[int, str]`
in `teleclaude/core/next_machine/core.py` that reads `input.md`, evaluates
its quality, and returns `(tier, rationale)`.

Assessment logic (deterministic, derived from R1):

- **Tier 3 signals** (ALL must be true): input describes only mechanical
  changes (rename, config edit, formatting), no behavioral change, no new
  architecture, total input is under ~200 words, and references only
  existing files. Returns `(3, "Mechanical change: ...")`.

- **Tier 2 signals** (ALL must be true): input contains specific file paths,
  explicit success criteria or constraints, references codebase patterns,
  and reads like requirements (detail-dense, not exploratory). The "what"
  is fully known. Returns `(2, "Concrete input: ...")`.

- **Tier 1 (default)**: anything that doesn't meet Tier 2 or 3 criteria.
  Returns `(1, "Standard pipeline: ...")`.

The function reads `input.md` content and applies these heuristics
structurally (checking for file path patterns, numbered requirements,
success criteria sections, etc.). It does NOT use an LLM — it is a
deterministic text analysis function.

**Why:** R1 requires deterministic assessment at entry. A dedicated function
keeps assessment logic testable and isolated from state machine flow. The
heuristics err toward higher tiers (more ceremony) when uncertain — Tier 3
requires zero-ambiguity confidence per the risk mitigation in requirements.

**Verification:** Unit tests feed three representative `input.md` texts
(one per tier) and assert correct tier. Repeated calls with same input
return same tier (determinism).

**Referenced files:**
- `teleclaude/core/next_machine/core.py`

---

### Task 3: Wire tier assessment into the prepare state machine

**What:** Modify the prepare flow in three places:

**3a. `_prepare_step_input_assessment()` (line 2985):**

Before dispatching discovery, check if tier is already set in state. If
`state["tier"] == 0` (not assessed), call `_assess_input_tier()` and persist
the result:

```python
tier = int(state.get("tier", 0))
if tier == 0:
    tier, rationale = _assess_input_tier(cwd, slug)
    state["tier"] = tier
    state["tier_rationale"] = rationale
    await asyncio.to_thread(write_phase_state, cwd, slug, state)
```

Then route based on tier:

- **Tier 1:** existing behavior — check for requirements.md, dispatch
  discovery if missing.
- **Tier 2:** promote input to requirements (copy `input.md` content as
  `requirements.md` basis), record skips for `triangulation` and
  `requirements_review`, set `requirements_review.verdict = "approve"`,
  advance `prepare_phase` to `PLAN_DRAFTING`.
- **Tier 3:** record skips for all preparation phases, stamp grounding as
  valid, set `prepare_phase` to `PREPARED`. Return the PREPARED terminal
  message. No workers dispatched.

**3b. Skip recording (R3):**

When a phase is bypassed, append to `skipped_phases`:
```python
state["skipped_phases"].append({
    "phase": "triangulation",
    "reason": f"tier_{tier}",
    "skipped_at": datetime.now(UTC).isoformat(),
})
```

**3c. Re-entry respect (R2):**

In `next_prepare()` (line 3506), the existing logic already reads
`prepare_phase` from state.yaml and dispatches accordingly. For Tier 2,
the persisted `prepare_phase=plan_drafting` with
`requirements_review.verdict=approve` causes the machine to route correctly
on re-entry — no additional re-entry logic needed beyond what already
exists. For Tier 3, `prepare_phase=prepared` causes the machine to return
the PREPARED terminal. The tier field itself is never re-evaluated once set.

**3d. Backward compatibility (R9):**

`_derive_prepare_phase()` (line 2948) handles the case where
`prepare_phase` is empty or invalid. When `tier=0` (default for legacy
todos), the assessment step in `_prepare_step_input_assessment()` runs
normally — assigning a tier and then routing. This means legacy todos
seamlessly enter the tiered world on their next `telec todo prepare` call.

**Why:** This is the core routing change. The prepare state machine must
use the tier to determine which phases to run (R1), record skip statuses
for bypassed phases (R3), promote input for Tier 2 (R4), and pass through
for Tier 3 (R5). Re-entry must respect existing tier (R2). Legacy todos
must continue working (R9).

**Verification:**
- Tier 1: `telec todo prepare` on an ambiguous input → dispatches discovery
  (identical to current behavior).
- Tier 2: `telec todo prepare` on a concrete input → `skipped_phases`
  contains triangulation + requirements_review, `prepare_phase` is
  `plan_drafting`, `requirements_review.verdict` is `approve`.
- Tier 3: `telec todo prepare` on a mechanical input → `prepare_phase` is
  `prepared`, all phases in `skipped_phases`, no workers dispatched.
- Re-entry: second `telec todo prepare` call on Tier 2 item → does not
  re-assess, continues from `plan_drafting`.
- Legacy: existing todo with no tier field → assessed as Tier 1, full
  pipeline runs.

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 2985-3011, 3506-3575,
  2948-2977)

---

### Task 4: Implement split state inheritance

**What:** Modify `split_todo()` in `teleclaude/todo_scaffold.py` (line 157)
to inherit parent progress instead of always seeding `input.md`:

```python
# After reading parent state
parent_state = read_phase_state(str(project_root), parent_slug)
req_review = parent_state.get("requirements_review", {})
req_approved = isinstance(req_review, dict) and req_review.get("verdict") == "approve"
plan_review = parent_state.get("plan_review", {})
plan_approved = isinstance(plan_review, dict) and plan_review.get("verdict") == "approve"

has_requirements = (parent_dir / "requirements.md").exists()
has_plan = (parent_dir / "implementation-plan.md").exists()
```

Then when scaffolding children:

- **Parent has only input.md** (current behavior): seed child `input.md`,
  start at discovery. No changes needed.

- **Parent has approved requirements.md** (`req_approved and has_requirements`):
  - Read parent `requirements.md` content
  - After `create_todo_skeleton()`, overwrite child's `requirements.md`
    with the parent's content (the drafter will subset it)
  - Set child state: `requirements_review.verdict = "approve"`,
    `prepare_phase = "plan_drafting"`, `tier = 2`

- **Parent has approved implementation-plan.md** (`plan_approved and has_plan`):
  - Also copy `requirements.md` and `implementation-plan.md`
  - Set child state: both review verdicts `approve`,
    `prepare_phase = "prepared"`, `tier = 3`

Note: the actual subsetting of requirements/plan per child is done by the
drafter who calls `split_todo()`. The function copies the full parent
artifacts; the drafter then edits each child's copy to contain only the
relevant subset. This matches the existing pattern where `seed_input`
provides the full parent input and the drafter subsets it.

**Why:** R8 requires children to start where the parent left off. The
`refactor-large-files` failure showed 8x ceremony waste. The tier assignment
on children creates the interaction between R8 and R1: children with
inherited approved requirements are by definition Tier 2, and children with
inherited approved plans are by definition build-ready.

**Verification:**
- Split parent with only `input.md` → children start at discovery (unchanged).
- Split parent with approved `requirements.md` → children have
  `requirements.md` copied, `prepare_phase=plan_drafting`, tier=2.
- Split parent with approved `implementation-plan.md` → children have both
  artifacts, `prepare_phase=prepared`, tier=3.
- Parent state is reset to container state (existing behavior preserved).

**Referenced files:**
- `teleclaude/todo_scaffold.py` (lines 157-250)

---

### Task 5: Add independent verification mandate to discovery procedure

**What:** Update three documentation files:

**5a. `docs/global/software-development/procedure/maintenance/next-prepare-discovery.md`:**

Add a new sub-step after step 1 (Read and ground):

> **1c. Verify measurable claims**
>
> Before writing requirements, independently verify every measurable claim
> in `input.md` against the live repository. Numbers (file counts, line
> counts, import counts), file paths, and threshold values must be checked
> with concrete tools (`wc -l`, `find`, `grep`). If a claim does not match
> reality, correct it to match the codebase. Mark corrections with
> `[verified: input said X, codebase shows Y]`. This is a factual
> correction, not a scope change, provided the correction aligns with the
> stated intent.

**5b. `docs/global/software-development/procedure/lifecycle/review-requirements.md`:**

In step 3 (Auto-remediate localized findings), add to "Allowed in-place
fixes":

> - Correcting verifiably wrong measurements (file count, line count,
>   file path) to match the live codebase when the stated intent is
>   unchanged. The discriminator: does the correction change the *intent*
>   of the work, or does it correct a *measurement* that supports the
>   same intent?

**5c. `docs/global/software-development/procedure/lifecycle/review-plan.md`:**

In step 8 (Auto-remediate localized findings), add the same factual
correction carve-out.

**Why:** R6 mandates independent verification. R7 refines the
auto-remediation boundary. Both address observed failures where a wrong
number cascaded through the pipeline (discovery didn't check) and then
blocked on review (reviewer flagged the correction as scope expansion).

**Verification:** Read updated docs → verification mandate present in
discovery procedure, factual correction carve-out present in both review
procedures with the discriminator test.

**Referenced files:**
- `docs/global/software-development/procedure/maintenance/next-prepare-discovery.md`
- `docs/global/software-development/procedure/lifecycle/review-requirements.md`
- `docs/global/software-development/procedure/lifecycle/review-plan.md`

---

### Task 6: Update design and procedure documentation for tier routing

**What:** Update the following documents to reflect tier-aware routing:

**6a. `docs/project/design/architecture/prepare-state-machine.md`:**
- Add tier assessment to the state diagram (new decision node after
  INPUT_ASSESSMENT: "tier?" with branches to Tier 1 flow, Tier 2
  shortcut, Tier 3 bypass).
- Add `tier`, `tier_rationale`, `skipped_phases` to the state.yaml schema
  description.
- Update the states reference table: INPUT_ASSESSMENT now also performs
  tier assessment.
- Add tier description to the invariants section: "Tier assignment is
  durable and deterministic — same inputs produce the same tier."
- Add lifecycle events: `prepare.tier_assessed` with tier value.

**6b. `docs/project/design/architecture/lifecycle-state-machines.md`:**
- Update Phase A description to note tier-aware routing: "Phase A supports
  three tiers of preparation depth based on input quality assessment."

**6c. `docs/global/software-development/procedure/maintenance/next-prepare.md`:**
- Update step 2 instruction types to include tier-conditional routing:
  "INPUT ASSESSMENT now performs tier evaluation. Tier 2 items skip
  discovery and requirements review. Tier 3 items reach PREPARED without
  dispatching any workers."

**6d. `docs/global/software-development/procedure/maintenance/next-prepare-draft.md`:**
- Add note in step 1 (Read and ground): "For Tier 2 items, requirements
  were promoted from input.md — they may lack the structure of
  discovery-produced requirements. Ground more carefully in the codebase."

**6e. `docs/global/software-development/procedure/maintenance/next-prepare-gate.md`:**
- Add note: "Tier 2 items arrive without discovery-phase artifacts. The
  gate validates the same DOR gates but accepts that discovery was skipped
  by tier assessment. Tier 3 items never reach the gate."

**6f. `docs/global/software-development/procedure/lifecycle/prepare.md`:**
- Add tier overview to the phase description.

**6g. `docs/global/software-development/policy/definition-of-ready.md`:**
- Add tier-aware enforcement note: "For Tier 2 items, gates 1-3 are
  satisfied by the tier assessment itself (the input already demonstrates
  clear intent, appropriate scope, and verification paths). For Tier 3
  items, all gates are auto-satisfied — the work is mechanical."

**Why:** R7 (in-scope item 7) explicitly requires all affected
documentation to reflect tier-aware routing. The risk of documentation
drift was called out: "if any is missed, agents following stale procedures
may not respect tiers."

**Verification:** Each updated doc references tier routing. The prepare
state machine design doc shows the assessment step with tier-conditional
paths in the state diagram.

**Referenced files:**
- `docs/project/design/architecture/prepare-state-machine.md`
- `docs/project/design/architecture/lifecycle-state-machines.md`
- `docs/global/software-development/procedure/maintenance/next-prepare.md`
- `docs/global/software-development/procedure/maintenance/next-prepare-draft.md`
- `docs/global/software-development/procedure/maintenance/next-prepare-gate.md`
- `docs/global/software-development/procedure/lifecycle/prepare.md`
- `docs/global/software-development/policy/definition-of-ready.md`

---

### Task 7: Update CLI help text

**What:** Update help/usage text in `teleclaude/cli/telec.py`:

- `telec todo split` usage: add note about state inheritance behavior
  ("Children inherit parent's approved artifacts and start at the phase
  the parent reached").
- `telec todo prepare` description in CLI_SURFACE or usage output: add
  note about tier-based routing ("Evaluates input quality and routes to
  appropriate pipeline depth").

**Why:** CLI help text feeds agent system prompts. Stale help text means
agents won't know about tier routing or split inheritance. The requirements
note this as [inferred] in-scope item 7.

**Verification:** `telec todo split --help` mentions inheritance.
`telec todo prepare --help` mentions tier assessment.

**Referenced files:**
- `teleclaude/cli/telec.py` (lines 2589-2635 for split, and prepare
  handler/usage)

---

### Task 8: Write unit tests

**What:** Create test files with the following test cases:

**`tests/unit/core/test_prepare_tiering.py`** (new):

1. `test_assess_tier_1_ambiguous_input` — vague input with no file paths
   or success criteria → tier 1.
2. `test_assess_tier_2_concrete_input` — input with specific files, clear
   constraints, success criteria → tier 2.
3. `test_assess_tier_3_mechanical_input` — rename/config-only input with
   zero ambiguity → tier 3.
4. `test_assess_tier_deterministic` — same input twice → same tier both
   times.
5. `test_tier_2_skips_to_plan_drafting` — mock `_prepare_step_input_assessment`
   with concrete input → state has `prepare_phase=plan_drafting`,
   `skipped_phases` contains triangulation and requirements_review.
6. `test_tier_3_reaches_prepared` — mock with mechanical input → state has
   `prepare_phase=prepared`, all phases skipped, no worker dispatched.
7. `test_tier_reentry_no_reassessment` — state already has `tier=2` →
   assessment function is not called again.
8. `test_backward_compat_no_tier_field` — state.yaml without tier field →
   `read_phase_state` returns `tier=0`, assessment runs normally.
9. `test_skipped_phases_recorded` — after Tier 2 routing, `skipped_phases`
   has entries with phase name, reason, and timestamp.

**`tests/unit/test_todo_scaffold_split.py`** (new):

1. `test_split_input_only_parent` — parent with only input.md → children
   have input.md, start at discovery (prepare_phase empty or
   input_assessment).
2. `test_split_approved_requirements_parent` — parent with approved
   requirements → children have requirements.md, `requirements_review.
   verdict=approve`, `prepare_phase=plan_drafting`, `tier=2`.
3. `test_split_approved_plan_parent` — parent with approved plan →
   children have both artifacts, `plan_review.verdict=approve`,
   `prepare_phase=prepared`, `tier=3`.
4. `test_split_parent_becomes_container` — parent state has
   `breakdown.todos` set to child slugs (existing behavior preserved).
5. `test_split_parent_artifacts_cleaned` — parent directory only retains
   input.md and state.yaml (existing behavior preserved).

All tests use `tmp_path` fixtures for filesystem isolation. State machine
tests mock `asyncio.to_thread`, `compose_agent_guidance`, and the database.

**Why:** Testing policy requires tests for new behavior. These tests cover
the core behavioral contracts: tier assessment heuristics, state machine
routing per tier, phase skip recording, split inheritance, and backward
compatibility.

**Verification:** `pytest tests/unit/core/test_prepare_tiering.py -v` and
`pytest tests/unit/test_todo_scaffold_split.py -v` pass. All tests exercise
the behavioral contracts described above.

**Referenced files:**
- `tests/unit/core/test_prepare_tiering.py` (new)
- `tests/unit/test_todo_scaffold_split.py` (new)
- `tests/unit/__init__.py` (may need creation)
- `tests/unit/core/__init__.py` (may need creation)

---

### Task 9: Rebuild indexes and final verification

**What:** Run `telec sync` to rebuild documentation indexes after all
documentation changes. Run pre-commit hooks to verify lint, type check,
and tests all pass.

**Why:** Doc indexes are generated artifacts. Changed procedures must be
re-indexed so agents discover updated tier-aware content. Pre-commit hooks
are the primary verification path per testing policy.

**Verification:** `telec sync` succeeds without errors. `git commit` with
pre-commit hooks passes (lint, typecheck, tests). No regressions in
existing behavior.

**Referenced files:**
- `docs/index.yaml` (generated)
- All modified files pass lint and type checks
