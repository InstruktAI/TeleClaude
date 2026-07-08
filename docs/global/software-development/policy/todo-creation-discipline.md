---
description: 'When to create a new todo versus fold work into what already exists — a minimal check at creation, amendment-in-place for not-yet-built work, and the kind-specific homes that own the deep landscape judgment.'
---

# Todo Creation Discipline — Policy

## Required reads

- @~/.teleclaude/docs/general/policy/documentation-discipline.md

## Rules

- **A minimal check precedes every todo creation.** Before running `telec todo
create`, scan `telec todo list` for an obviously related or overlapping
  candidate. This is cheap and bounded — a look at slugs and, for a plausible
  match, the `input` — never a deep landscape reconciliation. The creator's job
  stops at "does something like this already, obviously, exist" — not "is this
  genuinely the same scope, does it supersede, does it depend."
- **Deep judgment is never the creating caller's job.** Whether a premise
  yields to, supersedes, or merely depends on existing work is decided
  in-context, by the kind-specific phase already built for it, never by
  whoever is about to type `telec todo create`:
  - `feature` — intake step 1.6 (`software-development/procedure/lifecycle/prepare/intake`).
  - `bug` — diagnose Step 1 (`software-development/procedure/lifecycle/prepare/diagnose`), a
    stricter, race-safe duplicate-defect retirement, because near-simultaneous
    reports of the same defect cannot be caught at creation time.
  - `change` — the equivalent landscape check in plan-draft
    (`software-development/procedure/lifecycle/prepare/plan-draft`, step 1c).
- **Amendment-in-place beats a new sibling for small, not-yet-built work.** A
  `change`, `bug`, or `feature` that has not yet started build accepts a small
  addendum by amending its own intent artifact (`input`/`prd`) directly —
  which routes through the platform's existing drift-review, not by spawning a
  dependent or grouped sibling todo. A new todo is warranted when the addition
  is independently shippable, substantial in its own right, or the candidate
  it would otherwise fold into is already mid-build or finalizing.
- **A minimal FYI does not require amending the intent artifact at all.** When
  what's owed is a breadcrumb — not a scope change, not a new decision — the
  right vehicle is the todo's `log` artifact (see
  `project/spec/domain/workflow`), not a rewrite of `input`/`prd`/
  `implementation-plan`. Rewriting an intent artifact for a one-line FYI forces
  an unnecessary drift-review cycle over content that never needed one.
- **Process-layer changes are never filed on inference.** When the work's
  intent implies a behavioral delta to the process layer itself (lifecycle
  state machines, gate composition, review lanes, todo/state semantics), the
  todo's content carries an explicit human-approval declaration or it is not
  filed — escalate the proposal instead (`software-development/policy/process-change-authority`).

<!-- planned:todo-creation-record -->

- **"Who created this todo" is answered from the creation record, never
  inferred.** Every todo carries a mechanically stamped creation record —
  `entry_point` (which door: `tui`/`cli`/`web`/`agent`/`deferral`/`split`/`kickback`),
  `lineage` (the complete chain: human root plus the acting agent session when
  one was the hands), `human_involved`, and door-specific `context`. Read it;
  do not reconstruct provenance from account identity. The lineage root is the
  authority the work ran under — it is never evidence of who authored the work.
- **Agents declare human involvement at filing.** An agent filing from a
  conversation a human was part of — saw it, asked for it, or shaped it —
  passes `--human-involved`. Omitting it marks the todo agent-initiated for
  the human's audit; the deliberate bias is a false alarm over a hidden
  autonomous filing.

<!-- /planned:todo-creation-record -->

## Rationale

Two mechanisms already existed for this — intake step 1.6 for `feature`, diagnose
Step 1 for `bug` — but neither was ever stated as a general rule, and `change`
had no equivalent at all. That gap is not hypothetical: it produced a live
incident where a small addendum to an unstarted `change` was answered with a
new dependent todo instead of an amendment to the existing one, discovered only
after the fact. Stating the rule once, generally, and pointing at the
kind-specific homes that already implement it, closes the gap without asking
any of those three procedures to duplicate each other's mechanics.

## Scope

All todo creation, every kind, every creator — human or agent.

## Enforcement

A todo created for work that plainly duplicates or should have amended
existing not-yet-built work, without the minimal check having been performed,
is a process violation reviewers and orchestrators should flag.

## Exceptions

- `task` owes the same minimal check as every kind — no carve-out. It has no
  kind-specific home for the deep judgment, unlike `feature`, `bug`, and
  `change`: that reconciliation (does this yield to, supersede, or depend on
  existing work) is not built for `task` and remains a separately-scoped gap.
  See `software-development/spec/todo-kind-task`.
