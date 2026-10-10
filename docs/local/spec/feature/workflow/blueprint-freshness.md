---
description: Automatic canonical-main Blueprint maintenance and transparent current-baseline queries through the shared maintenance executor.
visibility: internal
delivered_by:
  - blueprint-main-maintenance
---

# Blueprint Freshness — Spec

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

### Use cases

#### UC-BPF1: Every canonical-main advance receives automatic maintenance

```gherkin
Scenario Outline: A canonical-main activation converges the shared Blueprint
Given a code-enabled project with installed commit-boundary maintenance
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

```gherkin
Given an agent has uncommitted edits in the canonical checkout and branch-only work in a todo worktree
When automatic Blueprint maintenance extracts committed canonical main
Then the resulting graph describes the selected committed revision
And neither uncommitted nor branch-only structure enters that generation
```

#### UC-BPF3: Successive activations converge without rolling the cache backward

```gherkin
Given more than one canonical-main advance is awaiting Blueprint maintenance
When the maintenance executor settles those obligations
Then an agent sees each obligation reach its own recorded outcome
And the shared Blueprint converges to the latest committed main revision observed by the actions
And an obligation finding that revision already current completes without extraction
```

#### UC-BPF5: Unavailable current evidence is explicit

```gherkin
Scenario Outline: A query cannot establish a current complete generation
Given the current Blueprint is unavailable because <condition>
When an agent asks for structural dependents
Then the query reports unavailability and the applicable maintenance recovery reference
And it returns no older dependents as a successful current answer

Examples:
| condition |
| extraction failed |
| generation was interrupted before publication |
| the query wait bound expired |
| maintenance was never recorded |
| committed canonical main cannot be resolved |
| the activated graph cannot be read |
```

#### UC-BPF6: Failure recovery converges forward

```gherkin
Given an earlier Blueprint obligation failed and canonical main has advanced again
When the owning agent replays that failed maintenance action
Then the outcome retains the earlier obligation's activation identity
And successful recovery activates a complete generation for committed main selected by the replay
And it does not replace a current generation with an older revision
```

#### UC-BPF7: On-demand recovery reuses the maintenance action

```gherkin
Given a code-enabled project's shared Blueprint is behind committed canonical main
When an agent runs on-demand maintenance from the canonical checkout on main
Then Blueprint maintenance converges the shared cache to committed main
And repeating the run with nothing changed completes without extracting again
```

#### UC-BPF8: Projects without code do not acquire Blueprint maintenance

```gherkin
Given a project has no code capability
When its canonical main advances or an agent runs on-demand maintenance
Then the project performs no Blueprint extraction or cache publication
```

## See Also

- docs/local/spec/domain/workflow.md — workflow ownership.
- docs/local/spec/feature/integration/post-commit-maintenance.md —
  activation records, execution, and replay.
- docs/local/spec/feature/integration/on-demand-maintenance.md —
  manual recovery and earlier-failure reporting.
- docs/local/design/architecture/checkpoint-system.md —
  shared action selection and execution boundaries.
