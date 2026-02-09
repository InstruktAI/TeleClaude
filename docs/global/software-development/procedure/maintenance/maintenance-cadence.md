---
id: 'software-development/procedure/maintenance/maintenance-cadence'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Weekly and monthly maintenance cadence for small teams that need high stability with low process overhead.'
---

# Maintenance Cadence — Procedure

## Goal

Run a sustainable maintenance rhythm that keeps service health, backlog quality, and operational confidence stable over time.

## Preconditions

- One person owns each weekly maintenance pass.
- Service-control commands are known and available.
- Bug intake and backlog systems are active.

## Steps

1. Run weekly maintenance pass (30–60 minutes):
   - Check current health (`make status`, recent logs).
   - Triage new bugs.
   - Clean backlog states.
   - Record top risks for next week.
2. Run monthly maintenance pass (60–120 minutes):
   - Review incident patterns.
   - Review dependency/update risk.
   - Remove stale operational noise.
3. Run quarterly simplification pass:
   - Remove deprecated paths.
   - Collapse duplicate or stale procedures.
   - Keep the maintenance system lean.

Weekly pass checklist:

- Service health checked.
- New bugs triaged and assigned.
- Blocked items older than 7 days forced to decision.
- Active work size back under limit.
- One short maintenance note written.

Monthly pass checklist:

- Repeat incident patterns reviewed.
- One prevention improvement selected.
- Dependency and environment risk reviewed.
- Process friction points reduced.

## Outputs

- Stable weekly maintenance signal.
- Smaller, cleaner active backlog.
- Explicit risk notes instead of implicit worry.
- Reduced repeat-incident frequency.

## Recovery

If cadence slips for multiple weeks:

1. Restart from weekly pass only.
2. Freeze non-essential process additions.
3. Triage and backlog cleanup first, optimization later.
4. Reintroduce monthly/quarterly layers after weekly discipline is restored.
