# DOR Report (Updated Draft): agent-file-locking-heartbeat

## Current Assessment

Status: `needs_decision` (gate rerun required after decision confirmation)

This todo now has a coherent architecture and implementation flow. It is close to
Ready, pending explicit confirmation of two policy decisions below.

## What Is Now Solid

1. Intent/outcome are explicit and testable.
2. Actor responsibilities are clear.
3. Contention path is deterministic (`heartbeat -> +3m retry -> halt/report`).
4. Liveness invariant is explicit (`dead owner cannot own lease`).
5. Commit ownership is explicitly retained by agent.

## Decision Checkpoints To Confirm

1. Coverage boundary

- Confirm v1 applies to all in-scope editing agents, not a subset.

2. Stop-idle release semantics

- Confirm 30s post-stop inactivity release applies as standard rule.

## Ready Signal After Confirmation

Once those two decisions are confirmed, this item should re-run gate and is expected
to be promotable to Ready.

## Suggested Next Action

1. Confirm the two policy checkpoints.
2. Execute `next-prepare-gate` for final pass/fail decision.
