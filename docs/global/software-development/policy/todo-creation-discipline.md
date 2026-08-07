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
- **The same check answers which project owns it.** A todo is filed against the
  project that owns the code the work would change, which is not always the
  project the symptom appeared in — platform behavior misbehaving inside a side
  project is a platform defect. The creating door defaults to the invoking
  working directory, so the creator states the owner explicitly when the two
  differ. A creator that cannot tell which project owns the work asks rather
  than defaulting.
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
- **Small, self-contained code work is executed in-context, never filed.** When a
  change is bounded enough that deriving it costs less than dispatching it — a
  handful of lines, the approach already known, nothing left to settle — the
  agent executes it immediately on `main` and routes the commit to review like
  any other. The gate is the human's presence in the session, which the agent
  detects; it is neither a separate approval step nor a requirement that the
  human edit or commit anything. The discriminator is whether anything remains to
  be **decided**, never the change's importance: a five-line tightening of a
  quality check is in-context work, and a two-line change whose correctness is
  genuinely contested is not. The lifecycle carries work that needs a plan, a
  builder, and a handoff; work needing none of those pays only the overhead.
- **A minimal FYI does not require amending the intent artifact at all.** When
  what's owed is a breadcrumb — not a scope change, not a new decision — the
  right vehicle is the todo's `log` artifact (see
  `project/spec/domain/workflow`), not a rewrite of `input`/`prd`/
  `implementation-plan`. Rewriting an intent artifact for a one-line FYI forces
  an unnecessary drift-review cycle over content that never needed one.
- **Process-layer changes are never filed on inference.** When the work's
  intent implies a behavioral delta to the process layer itself (lifecycle
  state machines, gate composition, review lanes, todo/state semantics), the
  todo is filed only on a human decision from the live conversation — otherwise
  it is not filed; escalate the proposal instead
  (`software-development/policy/process-change-authority`).

- **"Who created this todo" is answered from the creation record, never
  inferred.** Every todo carries a mechanically stamped creation record —
  `entry_point` (which door: `tui`/`cli`/`web`/`agent`/`split`),
  `lineage` (the complete chain: human root plus the acting agent session when
  one was the hands), `human_involved`, and door-specific `context`. Read it;
  do not reconstruct provenance from account identity. The lineage root is the
  authority the work ran under — it is never evidence of who authored the work.
- **Agents declare human involvement at filing.** An agent filing from a
  conversation a human was part of — saw it, asked for it, or shaped it —
  passes `--human-involved`. Omitting it marks the todo agent-initiated for
  the human's audit; the deliberate bias is a false alarm over a hidden
  autonomous filing.

<!-- planned:todo-prepare-entry-audit -->

- **Every todo enters preparation through a creation audit.** The prepare
  worker audits the durable record before deriving intent. Creator identity and
  `human_involved` affect the authority of individual claims, never whether the
  audit runs.
- **Creation evidence is mechanical, never a creator checklist.** The platform
  exposes the creation record and the actual source consultations and todo
  queries available from the creating context. A creator cannot supply,
  rewrite, or attest to that evidence. Missing evidence stays visibly missing;
  convincing prose never substitutes for it.
- **The prepare worker establishes truth rather than policing ceremony.** It
  checks ownership, obvious overlap, authority for process-layer intent, and
  whether required pending documentation supports the filing. It repeats
  missing grounding itself and reconciles the `input` to what the evidence
  supports. It may notify the creator of a correction, but never waits for or
  treats the creator's reply as evidence.
- **Admission is bound to the audited input.** The audit records the input
  digest it judged, the evidence it consulted, its corrections, and its
  disposition. Changing `input` invalidates admission and requires a new audit.
  A defensible filing proceeds after correction. It is retired only when the
  audit establishes a duplicate, the wrong owning project, unauthorized
  process intent, or no defensible intent left.
- **Creation audit does not own hold.** Hold remains scheduling and ownership
  state. The audit neither sets nor clears it, and admission does not depend on
  hold state.

<!-- /planned:todo-prepare-entry-audit -->

## Rationale

Ownership belongs in the creation-time check because filing where the code does
not live produces work nobody can deliver: the orchestrator that picks it up has
no access to the code the fix would touch, so the record is re-filed into the
owning project later, carrying its conclusions across a boundary they were never
derived behind.

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
is a process violation reviewers and orchestrators should flag. So is a todo
created for work small enough to execute in-context: the overhead of a plan, a
dispatched builder, and a review round is the cost, and it is paid by everyone
waiting behind it in the queue.

<!-- planned:todo-prepare-entry-audit -->

The lifecycle runner does not advance a todo beyond prepare entry until a
creation audit is current for the live `input` digest. Prepare owns remediation
and disposition; downstream Definition of Ready and Definition of Done reviews
do not re-litigate creation quality.
<!-- /planned:todo-prepare-entry-audit -->

## Exceptions

- `task` owes the same minimal check as every kind — no carve-out. It has no
  kind-specific home for the deep judgment, unlike `feature`, `bug`, and
  `change`: that reconciliation (does this yield to, supersede, or depend on
  existing work) is not built for `task` and remains a separately-scoped gap.
  See `software-development/spec/todo-kind-task`.
