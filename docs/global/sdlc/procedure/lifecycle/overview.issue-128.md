---
activation_trigger: Use when you need to prime as an orchestrator or need to know how orchestration works.
description: 'Software development lifecycle. Three-stage model: prepare, work, integrate.'
visibility: public
---

# Lifecycle Overview — Procedure

## Goal

The software development lifecycle follows a three-stage model. Preparation and
work are each carried by a driver that holds the item and judges, and one child
it dispatches that authors; integration is carried by the integrator. Each stage
starts through the `telec todo` CLI.

### 1. Prepare (`telec todo prepare`)

The preparation driver (`sdlc/procedure/lifecycle/prepare/overview-v2`) turns
the intent in the item's body into a fleshed-out spec in that body:

- **Derive** — the smallest complete authorized outcome and the existing path
  for comparable outcomes, before reading any draft
- **Author** — the dispatched author (`sdlc/procedure/lifecycle/prepare/intake-v2`)
  writes the spec into the body and authors its durable contract changes as
  pending snippets
- **Challenge** — the driver challenges necessity, proportionality and missing
  behavior with evidence; the author disposes every challenge
- **Ask** — a fork the person owns becomes one question while the item waits
- **Prepared** — the driver records readiness at the exact body revision it
  judged; a bug is prepared only to an established cause

Outputs: the spec in the item's body, its reviewed pending contracts, and the
log of derivation, challenges and readiness.

### 2. Work (`telec todo work`)

The work driver (`sdlc/procedure/lifecycle/work/overview-v2`) delivers the
prepared spec through the builder it dispatches
(`sdlc/procedure/lifecycle/work/build-v2`):

- **Derive** — the invariants the build is held to, before reading the
  builder's note
- **Build** — the builder implements the spec on the item's branch and commits
  as it goes; each commit publishes the branch
- **Scrutinize** — every published commit reaches the driver, which reviews the
  delta and places findings bound to commits; the builder answers each
- **Stamp** — the driver executes every applicable review lane
  (`sdlc/policy/definition-of-done-lanes`) against the whole delta and stamps
  the integration head, which makes the item ready
- **Kickback** — a spec that is wrong or unbuildable returns the item to
  preparation, keeping its branch

### 3. Integrate (`telec todo integrate`)

Merge candidates to canonical main:

- **Squash merge** — single commit capturing full delivery intent
- **Conflict resolution** — resolve in integration worktree
- **Push** — advance `origin/main`
- **Delivery bookkeeping** — todo list update and worktree cleanup

### Principles

- **Serial execution**: one phase runs, completes, then the next begins
- **Deterministic handoffs**: every phase ends with an act that names its outcome
- **Judge and author are distinct**: the driver judges what its child wrote and
  never what it wrote itself
- **Quality gates**: pre-commit hooks enforce standards; the driver's review
  validates completeness
- **Tandem for decisions, single for execution**: material discovery and design decisions receive independent peer falsification; once a decision is settled, one agent owns execution, with no peer ceremony added to fleshed-out mechanical work

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
