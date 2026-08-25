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

A maintenance sweep is the backstop for new or bypassed lifecycle doors. It
detects settled-slug/live-marker divergence wherever documentation material
lives, including repository-root snippets outside a candidate branch, and
faults the divergence to the integrator with the evidence needed to resolve it.

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

#### UC-LMR7: The divergence sweep finds settled material outside delivery candidates

```gherkin
Given a settled todo still has live pending markers or ownership metadata in documentation sources
And the material may live outside every integration candidate branch
When lifecycle maintenance sweeps for state and marker divergence
Then it detects the settled slug wherever the material lives
And faults the divergence to the integrator with the slug, source path, line, and reason
And unrelated live and pending material is not rewritten
```

#### UC-LMR8: Integration pre-applies candidate delivery before bookkeeping

```gherkin
Given a snippet has pending material owned by the current integration candidate
And delivery bookkeeping has not yet recorded the candidate as delivered
When the candidate merge is prepared in the integration worktree
Then reconciliation treats the current candidate as delivered
And stages the reconciled snippet paths before the commit prompt is returned
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
Given an integration candidate merge was conflicted
And the operator has resolved the conflicts but not committed them
When the integration flow prepares the conflict-resolution commit
Then candidate-scoped reconciliation runs again
And the reconciled paths are staged before the commit prompt is returned
And unrelated stale material is not folded into the candidate commit
```

### Cross-context references

- workflow — owns todo fate, identity, and reversal transitions and invokes
  reconciliation before making those movements durable.
- integration — owns candidate delivery reconciliation and receives divergence
  faults from the maintenance sweep.
- context — owns pending-material parsing, resolution, rendering, and source
  mutation primitives used by lifecycle callers.

## Known caveats

- Reconciliation is slug-scoped at write time. The maintenance sweep detects
  unrelated divergence but does not silently fold it into the current caller's
  operation.
- A pending region shared by multiple slugs becomes current only after every
  owner has resolved its fate.
- Reassigning material during a split or regroup requires an explicit resulting
  owner for every pending carrier; ambiguous ownership faults rather than being
  guessed.
