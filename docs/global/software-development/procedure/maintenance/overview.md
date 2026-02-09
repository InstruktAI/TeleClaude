---
id: 'software-development/procedure/maintenance/overview'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Maintenance operating model: practical rules for stability, backlog quality, and continuous operational learning.'
---

# Maintenance Overview — Procedure

## Goal

Establish a lightweight maintenance operating model that keeps a small application stable without creating process overhead.

This procedure defines how to run maintenance so you avoid repeated failures, backlog drift, and avoidable release flakiness.

## Preconditions

- The team agrees stability is more important than maximizing parallel work.
- Weekly maintenance ownership is assigned.
- Bug and backlog tracking are active (for example GitHub issues + project roadmap/todo flow).

## Steps

1. Use the maintenance procedures in this folder as one integrated system:
   - cadence,
   - bug triage,
   - backlog hygiene,
   - release rhythm,
   - incident learning,
   - deprecation planning.
2. Run weekly maintenance without skipping.
3. Keep active work intentionally small.
4. Convert incidents into prevention actions.
5. Remove obsolete paths and stale process as part of maintenance, not as side work.

## Outputs

- Predictable weekly maintenance execution.
- Backlog that stays decision-ready.
- Fewer repeated incidents.
- Safer, less flaky release behavior.
- Cleaner transitions when retiring legacy paths.

## Recovery

If maintenance stops working (too heavy, frequently skipped, unclear ownership):

1. Simplify first; do not add more process.
2. Reduce mandatory artifacts to the minimum useful set.
3. Reassign clear ownership.
4. Resume with weekly cadence before expanding scope again.
