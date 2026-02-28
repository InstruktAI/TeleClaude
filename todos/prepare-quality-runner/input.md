# Prepare Quality Runner — Input

## Context

We want maintenance automation that keeps todo preparation quality high without
manual babysitting. The current process relies on ad-hoc `next_prepare` passes.
That creates drift and uneven quality across `requirements.md` and
`implementation-plan.md`.

## Objective

Create an event-driven handler that reacts to todo lifecycle events and maintains
preparation quality:

1. audits todo quality when artifacts change or new todos land,
2. improves preparation artifacts in-place when safe,
3. writes `dor-report.md` for each assessed todo,
4. updates `state.yaml` with a quality score and verdict,
5. resolves the triggering notification with the assessment result.

`input.md` is optional context, not a hard prerequisite.

## Architectural direction (Feb 27 2026)

**Event-driven, not scheduled.** This runner is a notification consumer, not a cron job.

Events it consumes (via notification service):

- `todo.artifact_changed` — requirements.md or implementation-plan.md modified
- `todo.created` / `todo.dumped` — new todo scaffolded or brain-dumped
- `todo.activated` — moved from icebox to active roadmap
- `todo.dependency_resolved` — a blocking dependency was delivered

What it produces (as notification resolutions):

- DOR score + verdict attached to the notification
- If artifacts improved: may trigger new `todo.artifact_changed` (deduplicated via
  idempotency key — same slug + same commit hash = no-op)
- If blocked: `needs_decision` with specific blockers, notification stays unresolved

Depends on: notification-service (the event bus that routes signals to this handler).

This is TeleClaude's first internal dog-fooding consumer of the notification service.
It proves the pattern before external integrations.

## Expected result

- Every active todo has current, high-quality preparation artifacts.
- Weak todos are either improved above threshold or explicitly flagged for human review.
- The runner reacts to events, not schedules. Signal in, action out.
- The notification service tracks the full journey: event received, agent claimed,
  assessment complete, resolution attached.
