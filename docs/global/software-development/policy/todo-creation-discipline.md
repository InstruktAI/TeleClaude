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

- **Every created todo is audited when preparation begins.** The audit checks
  the durable record rather than classifying the creator. Before the todo's
  input becomes authority for derived artifacts, the prepare worker establishes
  that the owning project is correct, the bounded overlap check was performed,
  required governing contracts were consulted, required pending documentation
  exists for functionality work, and the input faithfully carries the intent
  available at creation.
- **Creation evidence is observed, never attested.** Where the creating context
  exposes actual source consultations and todo queries, the audit reads those
  observations. Missing observations remain missing; the prepare worker repeats
  the check itself and reconciles the input to what it finds. A creator-written
  checklist or later assurance never substitutes for observed evidence.
- **The audit repairs before it retires.** Correctable omissions are corrected
  in place and preparation continues. Retirement is reserved for a confirmed
  duplicate, work filed against an owner that cannot be corrected in place, an
  unauthorized process intent, or an input for which no defensible intent
  remains. Scheduling and `hold` state are orthogonal to this judgment.
- **The audit reads the current input.** Run it against the live input at prepare
  entry. If the input changes during preparation, repeat the audit before
  deriving from the revision. A `task` receives the same bounded creation audit
  before its task lane begins; this does not pretend that deep task-landscape
  reconciliation is already implemented.

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

Creation is deliberately cheap, so its claims cannot become preparation truth
without a second reading. Putting that reading at prepare entry uses the worker
that already has to understand the input and landscape, while evidence from the
creating context makes skipped checks visible without trusting self-report.
Repeating the audit after an input rewrite prevents later preparation from
inheriting a reading of different intent.

## Scope

All todo creation, every kind, every creator — human or agent.

## Enforcement

A todo created for work that plainly duplicates or should have amended
existing not-yet-built work, without the minimal check having been performed,
is a process violation reviewers and orchestrators should flag. So is a todo
created for work small enough to execute in-context: the overhead of a plan, a
dispatched builder, and a review round is the cost, and it is paid by everyone
waiting behind it in the queue.

## Exceptions

- `task` owes the same minimal check as every kind — no carve-out. It has no
  kind-specific home for the deep judgment, unlike `feature`, `bug`, and
  `change`: that reconciliation (does this yield to, supersede, or depend on
  existing work) is not built for `task` and remains a separately-scoped gap.
  See `software-development/spec/todo-kind-task`.
