---
description: Automatic Blueprint maintenance on the project's declared baseline — canonical main by default, remote main where the project binds it — and queries that answer from the published Blueprint while naming how the asking checkout differs from it.
visibility: internal
---

# Blueprint Freshness — Spec

## Required reads

@~/.teleclaude/docs/sdlc/spec/codebase-blueprint.md

## What it is

Agents receive structural blast-radius answers without arranging generation.
The workflow-owned maintenance executor converges the shared Blueprint to the
project's baseline after each activation the project binds it to and supplies
its failure and recovery outcomes. Every answer says which revision it reflects
and how the asking checkout differs from it. The general baseline and
consumption contract is `sdlc/spec/codebase-blueprint`.

## Canonical fields

- **Owner.** Workflow owns activation, queued maintenance, and recovery. The
  Blueprint's structural extraction and affected traversal retain their
  existing owner and graph data seam. This boundary follows
  `sdlc/policy/domain-ownership`.
- **Baseline selection.** The project's effective checkpoint model decides the
  baseline: when its Blueprint action is bound to remote-main activation, the
  baseline is the checkout's remote-tracking main; otherwise it is committed
  canonical main. Extraction, the query's report of the current baseline,
  replay and on-demand recovery all read that one selection.
- **Canonical-main activation.** By default a code-enabled project owes
  Blueprint maintenance on every canonical-main commit and merge, including an
  empty commit. Canonical-root integration activation uses the same executor
  as a direct commit. Worktree branches consume the shared cache without
  activating it.
- **Remote-main activation.** A project that binds its Blueprint action to
  remote-main activation owes it whenever the checkout's remote-tracking main
  advances — after a push from the canonical checkout or any of its worktrees,
  or after a fetch — and owes it on no canonical-main commit. Recording and
  execution follow
  `local/projects/teleclaude/spec/feature/integration/post-commit-maintenance`.
- **Execution.** The action runs after its toolchain prerequisites. It selects
  the baseline revision when it runs, materializes that exact revision, and
  converges the owning checkout's cache. An obligation whose baseline revision
  is already published when it runs is an idempotent success; an advance
  observed after an extraction started is extracted by a later obligation.
  Repeated activations retain their individual maintenance records.
- **Observation.** Workflow publishes the baseline selection and the state of
  outstanding or failed Blueprint maintenance for queries to read; how a query
  answers from them is `sdlc/spec/codebase-blueprint` (Fallback).
- **Failure and recovery.** A failed extraction leaves the prior complete
  generation published and records a failed maintenance action. Retry retains
  the original activation identity and converges to the current baseline.
  On-demand maintenance performs the same action while preserving earlier
  failure records under its own contract, which also brings a checkout whose
  remote-tracking main has not advanced since the binding was declared to its
  baseline. Query observation starts no writer.

Execution serialization and coherent publication follow
`sdlc/policy/code-quality-practices`; failure visibility and reuse of the
maintenance substrate follow `sdlc/principle/design-fundamentals`.

### Use cases

#### UC-BPF1: Every canonical-main advance receives automatic maintenance

#### UC-BPF2: Extraction excludes uncommitted and branch-only work

#### UC-BPF3: Successive activations converge without rolling the cache backward

#### UC-BPF5: An agent gets no stale blast-radius answer

#### UC-BPF6: Failure recovery converges forward

#### UC-BPF7: On-demand recovery reuses the maintenance action

#### UC-BPF8: Projects without code do not acquire Blueprint maintenance

#### UC-BPF9: An agent retrieves Blueprint results for a person

## Known caveats

- A release that predates remote-main activation cannot read a project
  declaration naming it, and treats the overlay as unreadable
  (`local/projects/teleclaude/design/architecture/checkpoint-system`,
  Invariant 22). A computer running such a release, or rolled back to one,
  therefore regenerates the Blueprint on every canonical-main commit until it
  runs a release that supports the declaration.

## See Also

- docs/local/spec/domain/workflow.md — workflow ownership.
- docs/local/spec/feature/integration/post-commit-maintenance.md —
  activation records, execution, and replay.
- docs/local/spec/feature/integration/on-demand-maintenance.md —
  manual recovery and earlier-failure reporting.
- docs/local/design/architecture/checkpoint-system.md —
  shared action selection and execution boundaries.
- docs/local/adr/0156-teleclaudes-blueprint-follows-remote-main-as-each-checkout-observes-it.md —
  why TeleClaude follows remote main.
