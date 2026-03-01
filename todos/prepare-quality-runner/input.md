# Prepare Quality Runner — Input

## Context

We want maintenance automation that keeps todo preparation quality high without
manual babysitting. The current process relies on ad-hoc `next_prepare` passes.
That creates drift and uneven quality across `requirements.md` and
`implementation-plan.md`.

## Objective

Create a pipeline cartridge that reacts to todo lifecycle events and maintains
preparation quality:

1. audits todo quality when artifacts change or new todos land,
2. improves preparation artifacts in-place when safe (structural fixes only),
3. writes `dor-report.md` for each assessed todo,
4. updates `state.yaml` with a quality score and verdict,
5. resolves the notification projection via EventDB.

`input.md` is optional context, not a hard prerequisite.

## Architectural direction (Mar 1 2026)

**Pipeline cartridge, not a standalone handler.** The event platform core is delivered.
This runner integrates as a `Cartridge` in the event processing pipeline.

Events it processes (via Pipeline → Cartridge.process()):

- `domain.software-development.planning.artifact_changed`
- `domain.software-development.planning.todo_created`
- `domain.software-development.planning.todo_dumped`
- `domain.software-development.planning.todo_activated`
- `domain.software-development.planning.dependency_resolved`

What it produces:

- DOR score + verdict written to `state.yaml` and `dor-report.md`
- Notification lifecycle updates via `EventDB` (claim → resolve or leave unresolved)
- Emits `domain.software-development.planning.dor_assessed` event for downstream consumers
- Idempotent via slug + commit hash — same state = no-op

This is TeleClaude's first domain-logic cartridge. It proves the cartridge pattern
before external domain cartridges follow.

## Expected result

- Every active todo has current, high-quality preparation artifacts.
- Weak todos are either structurally improved above threshold or explicitly flagged.
- The runner reacts to events via the pipeline. Signal in, action out.
- The EventDB tracks the full journey: event received, notification projected,
  agent claimed, assessment written, notification resolved.
