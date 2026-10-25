---
description: 'What an orchestrator writes: the process state of its slug, plus what its entry procedure assigns it; every other change reaches the repository through the session its state machine routes it to.'
visibility: 'public'
---

# Orchestrator Jurisdiction — Policy

## Rules

- **An orchestrator writes the process state of its slug.** It advances the
  state machine, dispatches and assesses the sessions the machine routes, and
  maintains the todo's artifacts, stamps, log and lifecycle state.
- **Phase work reaches the repository through the session the machine routes it
  to.** A dispatched worker produces its phase's code, tests, configuration and
  scripts; when that work needs a change, the orchestrator returns it to that
  worker with the evidence and governing addresses
  (`general/procedure/orchestration`).
- **An entry procedure may assign its orchestrator further writes.** What it
  names — phase authoring the orchestrator performs itself, or a change it
  executes on `main` — is inside the orchestrator's jurisdiction under that
  procedure's own review routing, and nothing beyond what it names is.
- **The active slug is the focus.** Changes elsewhere in the repository belong to
  their own owners and are taken as intended.

## Rationale

Every change keeps the session whose brief and review cover it. An orchestrator
that writes a worker's output places that change outside the review its phase
routes it through, and leaves the worker reasoning over state it did not
produce. Where one session drives a whole lifecycle by design, its entry
procedure carries that authoring together with its independent review, so the
same chain of custody holds.

## Scope

- Every session holding an orchestrator role in a lifecycle state machine, in
  every project.

## Enforcement

- Phase and commit reviewers read the todo log and the commits made under the
  claim; a change produced outside the session its machine routed it to, and
  outside what the entry procedure assigns, is a scope finding.

## Exceptions

- None.

## See Also

- ~/.teleclaude/docs/general/procedure/orchestration.md
