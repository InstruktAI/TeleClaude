---
description: Lifecycle marker resolution across todo fate changes, identity movement, and reversal, with caller-owned fault reporting and a divergence backstop.
---

# Lifecycle Marker Reconciliation — Spec

## What it is

Lifecycle marker reconciliation keeps a todo's pending documentation material
and lifecycle state coherent as one logical transition. Pending material
includes `delivered_by` ownership, planned additions, planned replacements,
companion files, and retirement companions — empty companions beside a snippet
or beside a command artifact under the repository's agent-artifact sources.

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
side of each planned change, replaces each parent with its non-empty companion,
deletes each parent together with its retirement companion, and clears the
delivered slug from `delivered_by`. A retirement whose parent still carries
another slug's pending material faults instead of deleting it. Abandonment
reconciliation selects the current side of each planned change and removes
material owned only by the abandoned slug, discarding a retirement companion
and leaving its parent live. Every operation is slug-scoped: unrelated pending
material stays byte-identical, and repeating a completed reconciliation makes
no further change.

<!-- planned:removal-abandons-sole-pending-snippets -->

Abandonment removes a pending document whose `delivered_by` names the abandoned
slug and no other, with everything it contains. A pending document that also
names another slug only loses the abandoned slug's membership and stays
pending.
<!-- /planned:removal-abandons-sole-pending-snippets -->

For integrated candidates, repository-root main is the sole documentation
reconciliation surface. The integration worktree publishes candidate code but
does not fold pending documentation. After that candidate commit is confirmed on
origin/main, candidate finalization synchronizes repository-root main, folds the
candidate slug there, publishes the folded root, and records only that final
confirmed SHA as delivered.

The integrator detects settled-slug/live-marker divergence on entering
integration, wherever documentation material lives in its project, including
repository-root snippets outside a candidate branch. Detection covers every
settled status; automatic repair covers only a delivered slug. A settled slug of
any other status is reported for the integrator to resolve and is left
untouched.
The integrator handles a delivered-slug fault as a separate recovery operation
after the repository root is synchronized and safe to mutate: it reconciles
only that delivered slug, publishes the resulting cleanup through its
canonical-main writer path, and leaves the original delivery record unchanged.

Source validation checks snippet shape and publication builds and deploys
indexes; neither performs lifecycle-driven reconciliation.

## Canonical fields

### Use cases

#### UC-LMR1: Delivery resolves only the candidate's planned-change block

#### UC-LMR2: Fate resolution promotes every pending carrier for delivery

#### UC-LMR3: Fate resolution abandons every pending carrier

#### UC-LMR4: Identity movement carries pending ownership atomically

#### UC-LMR5: Fate reversal restores or preserves pending material

#### UC-LMR6: Reconciliation failure faults the lifecycle caller

#### UC-LMR7: The integrator finds settled material outside delivery candidates

#### UC-LMR8: Integration pre-applies candidate delivery before bookkeeping

#### UC-LMR9: Partial ownership remains pending after delivery

#### UC-LMR10: Conflict resolution repeats candidate-scoped reconciliation

#### UC-LMR11: A recorded reconciliation commit stands when its commit command reports failure

#### UC-LMR12: Delivery retires a whole file through its empty companion

#### UC-LMR13: Retirement refuses to delete another slug's pending material

#### UC-LMR14: Reconciled snippets satisfy the project's own formatter

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

- docs/local/adr/0092-divergence-detection-belongs-to-the-acting-role.md — why detection runs inside the role that repairs it rather than on an unattended schedule.
- docs/local/adr/0090-root-fold-finalizes-a-pushed-candidate.md — why repository-root folding follows the confirmed candidate push and precedes delivery recording.
