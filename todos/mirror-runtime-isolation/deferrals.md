# Deferrals: mirror-runtime-isolation

## A6: Conditional DB split

- Item: `database.mirrors_path` split and mirror-DB routing.
- Reason: The gate is explicitly conditional on post-deployment A5 evidence across 3+ consecutive reconciliation cycles. That evidence cannot be produced inside this build worktree.
- Suggested outcome: `NEW_TODO`
- Trigger: Create the follow-up todo only if deployed `mirror.reconciliation.complete` metrics fail any A5 threshold.
- Notes: The current build ships the gate, metrics, pruning, identity, tombstones, and backfill needed to make that decision with evidence instead of speculation.
- Resolution: `NOOP`
- Processed on: `2026-03-09`
- Rationale: The follow-up is intentionally conditional on deployed A5 evidence across 3 or more reconciliation cycles. That evidence is not available in this build worktree, so no new todo is created now.
