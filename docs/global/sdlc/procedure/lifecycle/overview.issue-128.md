---
activation_trigger: Use when you need to prime as an orchestrator or need to know how orchestration works.
description: 'Software development lifecycle. Three-stage model: prepare, work, integrate.'
visibility: public
---

# Lifecycle Overview — Procedure

## Goal

The software development lifecycle follows a three-stage model. Preparation and
work each have a driver holding the item, an authoring child and a dedicated
reviewer child. Integration is carried by the integrator. Each stage
starts through the `telec todo` CLI.

### 1. Prepare (`telec todo prepare`)

The preparation driver (`sdlc/procedure/lifecycle/prepare/overview-v2`) holds
the item and coordinates sequential authorship and independent review:

- **Author** — the dispatched author (`sdlc/procedure/lifecycle/prepare/intake-v2`)
  independently completes the specification and its owning pending contracts.
- **Review** — after the completed-target handoff, the dedicated reviewer derives
  the governing obligations and assesses the complete revision under
  `sdlc/procedure/lifecycle/review` and the readiness policies.
- **Remediate** — the author independently disposes the finished verdict and
  returns a completed revision for re-review; genuine disputes follow isolated
  adjudication under the shared review contract.
- **Wait** — a fork the person owns uses the waiting act naming that person and
  question, releases the claim and ends the driver.
- **Prepared** — readiness records the independently approved body revision;
  a bug is prepared only to an established cause.

Outputs are the specification, reviewed pending contracts, and completed
review and disposition records in the existing item log.

### 2. Work (`telec todo work`)

The work driver (`sdlc/procedure/lifecycle/work/overview-v2`) coordinates the
builder (`sdlc/procedure/lifecycle/work/build-v2`) and dedicated reviewer
(`sdlc/procedure/lifecycle/work/review-build`):

- **Build** — the builder independently implements and self-checks the complete
  prepared outcome, handing off each coherent commit and stopping for review.
- **Review** — the dedicated reviewer assesses each finished commit in the
  context of the full goal. After all units, it reviews the resulting whole
  delivery and cross-unit behavior through every applicable lane.
- **Remediate** — the builder independently returns a complete correction or
  evidenced rejection after the verdict; review then closes findings and checks
  the changed surface within the same scope.
- **Stamp** — the driver records the exact independent report at the approved
  integration head, with every valid blocking finding resolved.
- **Kickback or wait** — a wrong specification returns to preparation with the
  branch preserved; a human-owned fork uses the waiting act and releases the
  claim before the driver ends.

### 3. Integrate (`telec todo integrate`)

Merge candidates to canonical main:

- **Squash merge** — single commit capturing full delivery intent
- **Conflict resolution** — resolve in integration worktree
- **Push** — advance `origin/main`
- **Delivery bookkeeping** — todo list update and worktree cleanup

### Principles

- **Serial execution**: one phase runs, completes, then the next begins
- **Deterministic handoffs**: every phase ends with an act that names its outcome
- **Independent judgment**: the reviewer has neither authored nor shaped the
  target; eligibility and replacement follow the shared review contract
- **Quality gates**: pre-commit hooks enforce standards; the independent reviewer
  assesses conformance and completeness; the driver records the supported outcome
- **Sequential handoffs**: complete production, complete independent verdict,
  complete remediation; an isolated adjudicator assesses only genuine unresolved
  disputes under the existing review contract

## Preconditions

- `telec todo show {slug}` shows item.

## Steps

1. Run `telec todo prepare {slug}` to start the preparation driver; it leaves
   the item prepared.
2. Run `telec todo work {slug}` to start the work driver; it leaves the item
   ready at a stamped commit.
3. The integrator admits the ready item and merges it to canonical main
   (`telec todo integrate {slug}`).

## Outputs

- Delivered work item merged to main.
- Updated todo list and delivery records.

## Recovery

- Each driver resumes from durable state: a driver started again for an item it
  holds receives its instruction, and one started for an item it no longer holds
  ends.
- Legacy-project import is one-shot. After the first successful import, TeleClaude stays DB-backed and does not re-read the markdown indexes on later calls.

## See also

- ~/.teleclaude/docs/sdlc/procedure/lifecycle/prepare/overview-v2.md
- ~/.teleclaude/docs/sdlc/procedure/lifecycle/work/overview-v2.md
- ~/.teleclaude/docs/sdlc/procedure/lifecycle/integrate.md
