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
  or after a fetch — and owes it on no canonical-main commit. TeleClaude
  declares this binding. Recording and execution follow
  `local/projects/teleclaude/spec/feature/integration/post-commit-maintenance`.
- **Execution.** The action runs after its toolchain prerequisites. It selects
  the baseline revision when it runs, materializes that exact revision, and
  converges the owning checkout's cache. A current generation is an idempotent
  success, so advances recorded while an extraction runs cost no further
  extraction. Repeated activations retain their individual maintenance
  records.
- **Observation.** A query pins the complete published generation and answers
  from it, naming its revision, the baseline revision, the state of Blueprint
  maintenance, and the files in which the asking checkout differs from it.
  Only when no complete generation exists does it wait, within its bound, for
  outstanding maintenance. An absent or unreadable generation yields explicit
  unavailability and a maintenance recovery reference. Canonical and worktree
  callers read the same generation; each answer describes its own caller's
  difference.
- **Failure and recovery.** A failed extraction leaves the prior complete
  generation answering and records a failed maintenance action. Retry retains
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

```gherkin
Scenario Outline: A canonical-main activation converges the shared Blueprint
Given a code-enabled project with installed commit-boundary maintenance
And the project keeps the default canonical-main Blueprint binding
When canonical main advances through <activation>
Then an agent observing maintenance sees a Blueprint obligation for that advance
And successful completion leaves a complete Blueprint for committed canonical main selected by the action

Examples:
| activation |
| a source-code commit |
| a documentation-only commit |
| an empty commit |
| a merge commit |
| a fast-forward merge |
```

#### UC-BPF2: Extraction excludes uncommitted and branch-only work

#### UC-BPF3: Successive activations converge without rolling the cache backward

#### UC-BPF6: Failure recovery converges forward

#### UC-BPF7: On-demand recovery reuses the maintenance action

#### UC-BPF8: Projects without code do not acquire Blueprint maintenance

#### UC-BPF10: A worktree started from remote main finds the Blueprint of its revision

```gherkin
Scenario Outline: A remote-main advance converges the shared Blueprint
Given a code-enabled project binds its Blueprint maintenance to remote-main activation
When the checkout's remote main advances through <advance>
Then an agent observing maintenance sees a Blueprint obligation for that advance
And successful completion leaves a complete Blueprint for the remote main revision the checkout observed
And a commit on canonical main that is not yet pushed owes no Blueprint maintenance

Examples:
| advance |
| a push from the canonical checkout |
| a push from the integration worktree |
| a fetch of revisions another computer pushed |
```

#### UC-BPF11: A Blueprint behind the asking checkout answers and names the difference

```gherkin
Given the published Blueprint was extracted from an earlier revision than an agent's slug worktree
When the agent asks for the blast radius of a file it changed
Then the answer gives the dependents from the published Blueprint
And it names the Blueprint's revision and the worktree's revision
And it lists the files in which the worktree differs from the Blueprint's revision, its own uncommitted changes included
```

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
