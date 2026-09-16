---
description: Lifecycle marker resolution across todo fate changes, identity movement, and reversal, with caller-owned fault reporting and a divergence backstop.
---

# Lifecycle Marker Reconciliation — Spec

## What it is

Lifecycle marker reconciliation keeps a todo's pending documentation material
and lifecycle state coherent as one logical transition. Pending material
includes `delivered_by` ownership, planned additions, planned replacements,
and companion files.

Three closed classes of lifecycle moment touch pending material:

- **Fate resolution:** delivery promotes the pending contract; abandonment
  removes planned additions, restores the current side of planned changes, and
  discards pending companions.
- **Identity movement:** rename, split, and regroup operations move every
  ownership label and companion filename with the material they reassign.
- **Fate reversal:** reactivation restores the exact material to pending;
  retraction and kickback preserve it as pending.

The caller that moves the slug owns reconciliation for that moment. It resolves
the affected material before making the lifecycle movement durable and reports
any failure to the intelligence driving that caller with the slug, source path,
line, and reason. A lifecycle movement never silently diverges from its pending
documentation state and never turns mechanical reconciliation into a human
task.

Delivery reconciliation promotes each planned addition, selects the replacement
side of each planned change, replaces each parent with its companion, and clears
the delivered slug from `delivered_by`. Abandonment reconciliation selects the
current side of each planned change and removes material owned only by the
abandoned slug. Every operation is slug-scoped: unrelated pending material stays
byte-identical, and repeating a completed reconciliation makes no further
change.

For integrated candidates, repository-root main is the sole documentation
reconciliation surface. The integration worktree publishes candidate code but
does not fold pending documentation. After that candidate commit is confirmed on
origin/main, candidate finalization synchronizes repository-root main, folds the
candidate slug there, publishes the folded root, and records only that final
confirmed SHA as delivered.

The integrator detects settled-slug/live-marker divergence on entering
integration, wherever documentation material lives in its project, including
repository-root snippets outside a candidate branch. Detection covers every
settled status; automatic repair covers only a delivered slug, because that is
the only status with a defined terminal fold. A settled slug of any other status
is reported for the integrator to resolve and is left untouched.
The integrator handles a delivered-slug fault as a separate recovery operation
after the repository root is synchronized and safe to mutate: it reconciles
only that delivered slug, publishes the resulting cleanup through its
canonical-main writer path, and leaves the original delivery record unchanged.

`telec sync` validates snippet shape and builds and deploys indexes; it does not
perform lifecycle-driven reconciliation.

## Canonical fields

### Use cases

#### UC-LMR1: Delivery resolves only the candidate's planned-change block

```gherkin
Given a live parent snippet contains a planned-change block for the current candidate
And the same parent contains a planned-change block for another slug
When delivery reconciliation runs for the current candidate
Then the current candidate's block is replaced by its replacement content
And all three marker lines for the current candidate are removed
And the other slug's planned-change block is left unchanged
And a second reconciliation run makes no further change
```

#### UC-LMR2: Fate resolution promotes every pending carrier for delivery

```gherkin
Given an active todo owns planned additions, planned changes, companion files, or delivered_by entries
When a lifecycle caller delivers that todo
Then each planned addition becomes live content
And each planned change selects its replacement content
And each companion replaces its parent
And the delivered slug is cleared from delivered_by
And pending material owned by other slugs remains byte-identical
```

#### UC-LMR3: Fate resolution abandons every pending carrier

```gherkin
Given an active todo owns planned additions, planned changes, companion files, or delivered_by entries
When a lifecycle caller abandons that todo
Then each owned planned addition is removed with its content
And each owned planned change keeps its current content
And each owned companion is discarded without replacing its parent
And the abandoned slug is cleared from delivered_by
And pending material owned by other slugs remains byte-identical
```

#### UC-LMR4: Identity movement carries pending ownership atomically

```gherkin
Given pending documentation material is owned by a todo slug
When a lifecycle caller renames that todo or reassigns its material through a split or regroup
Then every delivered_by entry and in-body marker follows the resulting owner
And every companion filename follows the resulting owner
And no pending material remains addressable only through the prior owner
And the identity movement is not made durable when ownership reconciliation fails
```

#### UC-LMR5: Fate reversal restores or preserves pending material

```gherkin
Given a todo's pending documentation material has been captured with its retained lifecycle state
When the todo is reactivated after abandonment
Then the exact captured material is restored as pending under the reactivated slug
And no captured material is promoted to the live contract
But when a todo is retracted or kicked back without abandonment
Then its existing pending material remains unchanged
```

#### UC-LMR6: Reconciliation failure faults the lifecycle caller

```gherkin
Given a lifecycle movement requires pending documentation reconciliation
And an affected source cannot be resolved or written safely
When the caller attempts the lifecycle movement
Then the caller receives a fault naming the slug, source path, line, and reason
And the movement does not report successful reconciliation
And the fault remains owned by the intelligence driving that lifecycle moment
```

#### UC-LMR7: The integrator finds settled material outside delivery candidates

```gherkin
Given a settled todo still has live pending markers or ownership metadata in documentation sources
And the material may live outside every integration candidate branch
When the integrator enters integration and checks for state and marker divergence
Then it detects the settled slug wherever the material lives
And holds the divergence with the slug, source path, line, and reason
And when the faulted slug is delivered and repository-root main is synchronized and safe to mutate, the integrator runs a new slug-scoped delivery reconciliation as a recovery operation
And it commits and publishes only that recovery result without changing the settled todo's recorded delivery commit
And a failed recovery leaves the divergence fault active with its failure evidence
And unrelated live and pending material is not rewritten
```

#### UC-LMR8: Integration pre-applies candidate delivery before bookkeeping

```gherkin
Given repository-root main contains pending material owned by an integration candidate
And the candidate commit has been published from the integration worktree and confirmed on origin/main
When the integrator finalizes the candidate on repository-root main
Then it synchronizes repository-root main with the confirmed candidate
And it reconciles that slug against the repository-root documentation set
And it publishes and confirms the folded repository-root head before delivery is recorded
```

#### UC-LMR9: Partial ownership remains pending after delivery

```gherkin
Given pending material is owned by the current candidate and at least one other active slug
When reconciliation delivers the current candidate
Then the current candidate is removed from the ownership metadata
And the remaining active owners stay pending
And the material does not become current until its remaining owners resolve
```

#### UC-LMR10: Conflict resolution repeats candidate-scoped reconciliation

```gherkin
Given an integration candidate required conflict resolution before its commit was published
And the resolved candidate commit is confirmed on origin/main
When repository-root main synchronizes that candidate for finalization
Then candidate-scoped reconciliation runs against repository-root main
And unrelated pending material remains unchanged
And the folded repository-root head is published and confirmed before delivery is recorded
```

### Cross-context references

- workflow — owns todo fate, identity, and reversal transitions and invokes
  reconciliation before making those movements durable.
- integration — owns candidate delivery reconciliation, detects divergence on
  entry, and resolves it through its separate recovery transition.
- context — owns pending-material parsing, resolution, rendering, and source
  mutation primitives used by lifecycle callers.

## Known caveats

- Reconciliation is slug-scoped at write time. The integrator detects unrelated
  divergence but does not silently fold it into the current caller's operation.
- A pending region shared by multiple slugs becomes current only after every
  owner has resolved its fate.
- Reassigning material during a split or regroup requires an explicit resulting
  owner for every pending carrier; ambiguous ownership faults rather than being
  guessed.

## See Also

- docs/project/adr/0092-divergence-detection-belongs-to-the-acting-role.md — why detection runs inside the role that repairs it rather than on an unattended schedule.
- docs/project/adr/0090-root-fold-finalizes-a-pushed-candidate.md — why repository-root folding follows the confirmed candidate push and precedes delivery recording.
