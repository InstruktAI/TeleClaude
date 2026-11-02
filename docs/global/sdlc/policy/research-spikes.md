---
description: 'A decision that rests on third-party behavior not recorded as verified waits for a spike that verifies it; how the deciding agent files the spike, waits, and resumes.'
delivered_by: [spike-todo-kind]
---

# Research Spikes — Policy

## Rules

### The trigger

- **A decision rests on verified third-party behavior or waits.** When a
  decision in architecture, a plan or a diagnosis rests on how a third party
  behaves — a vendor API, a CLI, a protocol, a library — and neither the
  project's nor the global third-party documentation records that behavior as
  verified (`general/spec/third-party-docs`), the deciding agent neither
  decides on memory nor tests the behavior itself. It files a spike
  (`sdlc/spec/todo-kind-spike`) and the decision waits for it.
- **Documentation already verified is the answer.** A verified fact in the
  project or global third-party documentation settles the question; no spike is
  filed for it. A fact recorded without its verification does not settle it.
- **One spike per question.** The spike's `input` states the question in
  third-party terms, the upstream party it concerns, and the decision and the
  todo waiting on it. A plausible duplicate found by the creation check is
  joined, not refiled (`sdlc/policy/todo-creation-discipline`).

### Waiting

- **The waiting todo depends on the spike.** The deciding agent adds the spike
  to its todo's `after` set (`telec todo update <slug> --after …`, carrying the
  existing edges), and records in the todo's `log` which decision waits on which
  spike.
- **The phase stops where the decision is.** The preparation phase whose
  decision needs the answer does not complete, and the todo does not enter work,
  until the spike has run. The deciding agent leaves the phase open and departs
  under `general/principle/session-lifecycle`; the lifecycle takes the todo up
  again once the spike is delivered.
- **A spike that ends in error keeps its dependents waiting.** Its hold is
  resolved through the task lane, never by removing the dependency to proceed
  on unverified behavior.

### Resuming

- **The resumed phase reads the answer, then decides.** The session that takes
  the todo up again reads its `log`, the spike's `log` and the third-party
  documentation the spike wrote, and writes the conclusion for its decision
  into its own artifact — the `architecture`, the `implementation-plan` or the
  `diagnosis`. What the spike recorded as unverified stays visible there as an
  assumption.

## Rationale

- A decision taken on remembered or locally poked third-party behavior is
  correct only by accident, and the next agent repeats the guess
  (`general/principle/grounding`). A verified fact written into third-party
  documentation is reused by every later agent.
- A spike is a separate todo so the investigation neither blocks nor bloats
  the session that needs it, and so the dependent has a durable gate to wait
  on.
- A conclusion written by the waiting job into its own artifact keeps every
  preparation artifact single-authored by the phase that owns it; the spike
  supplies facts, the phase decides.

## Scope

- Every agent deriving architecture, a plan or a diagnosis in an sdlc project,
  and every agent resuming a todo that waited on a spike.

## Enforcement

- Preparation reviewers treat a decision resting on third-party behavior that
  neither third-party documentation records as verified, and that no spike
  answered, as a grounding finding against the artifact.
- The prepare machine refuses to advance a todo past its current phase while a
  spike it depends on is undelivered.

## Exceptions

- Behavior that cannot be verified with throwaway resources: the spike records
  the gap and completes, and the dependent decides with the gap stated as an
  assumption.
