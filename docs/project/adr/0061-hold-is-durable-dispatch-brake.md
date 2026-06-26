---
id: project/adr/0061-hold-is-durable-dispatch-brake
type: adr
domain: project
scope: project
description: Hold is the durable autonomous-dispatch brake for any active todo; manual close and explicit hold requests persist it independently of kind, phase, and autostart policy.
---

# ADR-0061: Hold is the durable dispatch brake — ADR

## Context

ADR-0036 made manual session close an explicit halt by writing the todo's normal
hold field before closing the driven session. ADR-0053 then scoped hold to the
work lane for autostart-enabled kinds: autostart-disabled kinds did not write,
render, or act on hold, and prepare-lane holds were inert.

That scoped model breaks the operator intent hold is meant to carry. A human can
manually close a lifecycle session because they want dispatch to stop now, but
the runner can still redispatch prepare work when the stored flag is ignored.
An authorized `telec todo update <slug> --hold` can also report success while
persisting nothing for kinds whose autostart is disabled. Both outcomes make
hold unreliable as dispatch control.

The system already has one durable hold field, one hold audit, live-holder
deduplication, and active-runner cleanup on session end. The fix is to make that
existing hold authoritative instead of adding a parallel claim hold or
prepare-only gate.

## Decision

`state.hold=true` is the durable autonomous-dispatch brake for any active todo,
regardless of kind, lifecycle phase, or autostart policy. When a todo is held,
the lifecycle runner does not autonomously dispatch analyze, prepare, work,
task-prepare, or task-run sessions for it until the hold is released.

A manual human close of a lifecycle-driving session writes the existing todo
hold and hold audit before the close is requested. This applies in every
lifecycle phase, including prepare. A normal agent self-close, successful
lifecycle completion, prepared cleanup, finalize cleanup, or ordinary session
end does not write hold; those paths only clear stale live-runner claims through
the existing session-end cleanup.

An authorized explicit hold request through `telec todo update <slug> --hold`
or the matching API request always persists `state.hold=true` and the manual
hold audit for any active todo kind. It does not clear `active_runner`; hold
controls future autonomous dispatch, while session-close cleanup controls the
live claim. This lets an authorized operator or agent hold the todo first, close
the current claiming session second, and then take over only after the live
holder is gone.

Manual lifecycle start is the release-and-start operator path. A TUI/operator
prepare or work operation first verifies that no other live holder owns the
todo. Only after that check succeeds may it clear the hold and adopt or dispatch
the lifecycle session. If a live holder exists, the operation is refused and the
hold remains intact. The create-session door used by the New Session modal stays
a live-holder dedup path: it may create a lifecycle command session for a held
but unclaimed slug, but hold release belongs to the lifecycle command/operation
path once that path successfully claims or dispatches.

ADR-0053 is superseded for hold persistence, render, and dispatch effect. Its
historical rationale remains as the discarded autostart-scoped design.

## Consequences

- Hold has one meaning everywhere: no autonomous lifecycle dispatch until
  release.
- Manual close becomes a predictable halt for prepare and work sessions alike.
- Direct CLI/API `--hold` requests are durable for all active todo kinds.
- Active-runner cleanup stays unchanged: closing or killing a session still
  clears the claim separately from hold.
- Manual start remains possible, but it is claim-gated and clears hold only on a
  successful operator start path.
- Previously inert residual holds may now become visible and effective. This is
  intentional: a stored hold represents explicit operator intent, not dormant
  autostart metadata.

## Alternatives Considered

- **Keep ADR-0053's autostart-scoped hold.** Rejected: it lets prepare sessions
  respawn after manual close and makes explicit `--hold` requests silently fail
  for autostart-disabled kinds.
- **Introduce a separate claim hold or prepare-only hold.** Rejected: the system
  already has durable hold state, audit, and dispatch eligibility machinery.
  A parallel gate would split operator intent across two concepts.
- **Clear active_runner when setting hold.** Rejected: hold is dispatch control,
  not claim ownership. A live session remains the claimant until it exits or is
  closed through the existing cleanup path.
- **Let manual start ignore hold without clearing it.** Rejected: it would leave
  a successful operator start in a state that still appears held and can block
  later autonomous follow-up after the manual session exits.
