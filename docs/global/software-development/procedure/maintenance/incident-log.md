---
id: 'software-development/procedure/maintenance/incident-log'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Incident logging procedure focused on root cause quality, prevention actions, and repeat-incident reduction.'
---

# Incident Log — Procedure

## Goal

Capture incidents in a way that produces real prevention, not just history.

## Preconditions

- A place exists to store incident entries.
- Incident owner is assigned when event occurs.
- Team agrees to log meaningful incidents within 24 hours.

## Steps

1. Record incident facts quickly:
   - time window,
   - symptom,
   - user impact,
   - immediate fix.
2. Document root cause with explicit confidence.
3. Add one concrete prevention action.
4. Assign owner and due date for prevention.
5. Verify recovery and close loop in next maintenance pass.

Required incident fields:

- title,
- date/time,
- user-visible symptom,
- impact,
- root cause,
- immediate fix,
- prevention action,
- owner,
- verification.

## Outputs

- Searchable incident history.
- Actionable prevention backlog.
- Better learning quality across maintenance cycles.

## Recovery

If incident log becomes shallow or stale:

1. Reject vague entries and rewrite root cause clearly.
2. Enforce prevention owner + due date.
3. Escalate repeat incidents that recur within 30 days.
4. Review open prevention actions weekly until closed.
