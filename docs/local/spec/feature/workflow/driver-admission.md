---
description: Which session may become a todo's lifecycle orchestrator on one computer,
  how concurrent starts of one todo are decided, and what a losing start and a losing
  lifecycle runner pass do.
visibility: internal
---

# Driver Admission — Spec

## Required reads

- @docs/local/spec/domain/workflow.md

## What it is

Driver admission decides whether a start may make a session the lifecycle
orchestrator of a todo. A start reaches it through a session create door
launching an orchestrator role for the todo, or through a `telec todo prepare`
or `telec todo work` operation that claims the todo for its calling session in
place. On one computer a todo has at most one live orchestrator, whatever lane
each start asks for.

## Canonical fields

### Holders

A todo is held when either of these exists in its project on this computer:

- an open session carrying a lifecycle driver role whose working slug is the
  todo. A session counts from the moment it is created, while it is still
  initializing; a closing or closed session does not count.
- a live session named as the todo's `active_runner`.

### Deciding concurrent starts

- Starts of one todo on one computer are decided one at a time. Each start
  checks the todo's holders and, when it finds none, records its own ownership
  fact before the next start of that todo is checked: a create door creates its
  session, and an operation claims the todo for its calling session.
- A start that finds a holder is refused with a driver-start conflict naming
  that holder, and creates or claims nothing.
- A start that arrives while another start of the same todo is being decided
  does not wait: it is refused as busy, naming the session that other start
  creates or claims, and creates or claims nothing.
- Starts of different todos are never decided against each other.
- Task-runner, reviewer and worker-child starts are outside driver admission
  and keep their own checks.

### Losing starts

- A `telec todo prepare` or `telec todo work` operation whose start loses fails,
  whether it would have claimed the todo in place or started an orchestrator
  session: with the driver-start conflict naming the holder when it lost to a
  holder, or with the busy refusal naming the other start's session when it
  arrived while that start was being decided.
- A lifecycle runner pass whose start of a todo loses, to a holder or to a start
  of that todo still being decided, counts that todo as already driven, starts
  nothing for it, and continues with the other todos it selected. Neither the
  pass nor the event that woke it fails. A later pass evaluates the todo again.
- A dispatch repeated after its own earlier start was accepted records that
  started session as the todo's driver instead of starting another.

<!-- planned:single-orchestrator-across-computers -->

### Across computers

For a project on the GitHub workflow store, every computer holding a checkout
sees the same todos, and one todo has at most one live orchestrator across all
of them.

- A start on any computer is also admitted by the fleet's master before its
  session is created or its caller claimed. The starting computer keeps its own
  decision for the todo while it asks, and its caller waits for the answer only
  within a bounded budget.
- The master decides one start of a todo at a time. The todo is held when the
  master's own sessions hold it or the todo's `active_runner` claim holds it.
- A claimed session holds the todo while it is open, not closing, and drives
  that todo, or while a start of it for that todo is being decided on its
  computer. Each computer answers this for the sessions it ran. The master asks
  every computer the platform knows, configured or discovered: the computer
  that ran the session decides; a session no computer ran does not hold the
  todo; a computer that does not answer leaves the claim held.
- A computer treats a claim for a session it never ran as held, and never
  clears it.
- Only the master writes the claim while a start can be admitted for the todo.
  Another computer asks it to release a claim for a session that computer ran,
  and the master clears claims it judges ended in its lifecycle runner passes.
  Reactivating a removed todo restores the claim its removal set aside.
- A start that finds the todo held is refused with the driver-start conflict
  naming the holding session and the computer running it, or the computers that
  did not answer, and creates or claims nothing.
- A start the master cannot decide — no unique live master holding the
  project, no answer from it, or no decision within the budget — is refused
  naming why, and creates or claims nothing. A lifecycle runner pass counts
  that todo as skipped and continues; a lifecycle operation fails with that
  refusal.

<!-- /planned:single-orchestrator-across-computers -->

## Known caveats

- A start whose session never leaves initializing — its bootstrap failed —
  holds the todo until that session is ended; the bootstrap failure is
  published for a person to act on.

<!-- planned-change:single-orchestrator-across-computers -->

- Admission covers one computer. Computers that see one todo through a shared
  workflow store do not decide their starts against each other.

<!-- change:single-orchestrator-across-computers -->

- Across computers, a claim stays held while the computer running its session
  does not answer the master, and every start of a GitHub-backed todo is
  refused while the master is unreachable.
- A computer on a release without cross-computer admission still decides its
  own starts by its own registry until it is updated.

<!-- /planned-change:single-orchestrator-across-computers -->

## See Also

- docs/local/adr/0133-concurrent-driver-starts-serialize-in-process-at-the-start-doors.md
- docs/local/adr/0134-a-colliding-driver-start-is-refused-without-waiting.md
- docs/local/adr/0052-orchestrator-dedup-registry-authoritative.md

<!-- planned:single-orchestrator-across-computers -->

- docs/local/adr/0135-github-backed-driver-starts-are-admitted-by-the-mesh-master.md
- docs/local/adr/0136-only-the-master-writes-a-github-backed-claim.md
- docs/local/adr/0137-a-github-backed-claim-is-settled-per-todo.md

<!-- /planned:single-orchestrator-across-computers -->
