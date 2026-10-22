---
description: Automatic canonical-main Blueprint maintenance and transparent current-baseline
  queries through the shared maintenance executor.
visibility: internal
---

# Blueprint Freshness — Spec

## Required reads

@~/.teleclaude/docs/sdlc/spec/codebase-blueprint.md

## What it is

Agents receive structural blast-radius answers for committed canonical main
without arranging generation. The workflow-owned maintenance executor converges
the shared Blueprint after every canonical-main activation and supplies its
failure and recovery outcomes. The general baseline and consumption contract is
`sdlc/spec/codebase-blueprint`.

## Canonical fields

- **Owner.** Workflow owns canonical-main activation, queued maintenance, and
  recovery. The Blueprint's structural extraction and affected traversal retain
  their existing owner and graph data seam. This boundary follows
  `sdlc/policy/domain-ownership`.
- **Activation.** A code-enabled project owes Blueprint maintenance on every
  canonical-main commit and merge, including an empty commit. Canonical-root
  integration activation uses the same executor as a direct commit. Worktree
  branches consume the shared cache without activating it.
- **Execution.** The action runs after its toolchain prerequisites and before
  daemon restart. It selects committed canonical main, materializes that exact
  revision, and converges the owning checkout's cache. A current generation is
  an idempotent success. Repeated activations can share an already extracted
  current revision while retaining their individual maintenance records.
- **Observation.** A successful query pins one complete generation matching
  committed canonical main at its freshness observation. Pending maintenance is
  observed within the query's bounded wait. Failure, missing maintenance, or
  expiry yields explicit unavailability and a maintenance recovery reference.
  Both canonical and worktree callers receive this guarantee.
- **Failure and recovery.** A failed extraction leaves the prior complete
  generation intact and records a failed maintenance action. Retry retains the
  original activation identity and converges to current committed main.
  On-demand maintenance performs the same action while preserving earlier
  failure records under its own contract. Query observation starts no writer.

Execution serialization and coherent publication follow
`sdlc/policy/code-quality-practices`; failure visibility and reuse of the
maintenance substrate follow `sdlc/principle/design-fundamentals`.

### Installed release baseline

For an installed release checkout under
`local/projects/teleclaude/spec/feature/reconciliation/release-checkout`, the
maintenance source query selects the installed commit. Extraction, query
freshness and replay use that same selection. A different local main tip does
not change the installed checkout's baseline. The canonical-main rules above
remain the baseline for other projects and checkouts.

### Use cases

#### UC-BPF1: Every canonical-main advance receives automatic maintenance

#### UC-BPF2: Extraction excludes uncommitted and branch-only work

#### UC-BPF3: Successive activations converge without rolling the cache backward

#### UC-BPF5: An agent gets no stale blast-radius answer

```gherkin
Given an agent asks for the structural dependents of a changed file
And no complete Blueprint matching the requested checkout's current baseline can be established
When the query returns
Then it reports the result as unavailable with the applicable maintenance recovery reference
And it does not present older dependents as the current answer
```

#### UC-BPF6: Failure recovery converges forward

#### UC-BPF7: On-demand recovery reuses the maintenance action

#### UC-BPF8: Projects without code do not acquire Blueprint maintenance

#### UC-BPF9: An agent queries the installed release's Blueprint

```gherkin
Scenario: Use the installed release as the query baseline
  Given the installed release and local main contain different source
  When an agent asks for the Blueprint affected view of a changed file through the installed runtime
  Then the result reflects the installed release's source
  And changes present only in local main do not affect the result
```

## See Also

- docs/local/spec/domain/workflow.md — workflow ownership.
- docs/local/spec/feature/integration/post-commit-maintenance.md —
  activation records, execution, and replay.
- docs/local/spec/feature/integration/on-demand-maintenance.md —
  manual recovery and earlier-failure reporting.
- docs/local/design/architecture/checkpoint-system.md —
  shared action selection and execution boundaries.
