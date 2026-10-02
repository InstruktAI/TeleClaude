---
description: Durable agent reminders for goal alignment, cooperative peer-response
  yield, stale-intent invalidation, cancellation, and locally owned prescribed profiles.
---

# Agent Reminder — Policy

## Rules

### A reminder is a claim on the next move

Arming, keeping, and cancelling answer one question: does the next move belong
to this agent?

- **Mine, now** — act. No reminder.
- **Not mine** — do not arm; cancel if armed. It makes no difference whether the
  move passed to a human, an orchestrator, or nobody.
- **Mine, but gated** — arm. A gate certain to resolve at a known time is
  one-shot; a gate externally owned and unbounded is recurring.

Cancel at the transition — the moment the move stops being yours, while you are
still thinking about the work. A later firing is the fallback for a missed
cancellation, not the cleanup path.

### A reminder carries intent, not authority

- It is durable intent left for your future self — not a liveness heartbeat,
  human authorization, proof of delivery, or proof that input was processed.
- Before acting on a firing, read everything that arrived after its armed time.
  If later input changed or superseded the intent, discard it and re-evaluate
  from current state. Re-establish relevance, source truth, and any required
  authorization at execution time; never act on the stored copy.
- A firing whose intent is already satisfied or obsolete owes no output
  (`general/policy/no-output-turn`). A one-shot has already consumed itself; a
  recurring firing cancels its own slug first. Retiring a reminder is always an
  explicit cancel — the sentinel retires nothing.

### Yield; never wait in a terminal

Never occupy a terminal or tool runtime to wait for time, input, a
notification, or external completion — no `sleep`, wait commands, polling loops,
or long-lived tool cells. Arm the reminder you need and yield; the reminder or
the incoming event re-enters the session through its normal input path. Never
reimplement reminders with detached processes, transport messages, or
runtime-specific timers.

### Identity and lifecycle

- Identity is `(authenticated session, intent-revealing slug)`. Distinct intents
  use distinct slugs and may coexist.
- Setting a live slug again atomically replaces it; the earlier schedule cannot
  fire after replacement succeeds.
- Cancel one slug when its subgoal is satisfied; cancel all only when every
  outstanding intent is obsolete. Cancellation is session-scoped and idempotent.
- Relative reminders may be one-shot or recurring; absolute-time reminders are
  one-shot. Recurrence is explicit, never inferred from an intent that sounds
  ongoing.
- Prescribed slugs are reserved and declared beside their owner
  (`general/spec/reminder-profile-declaration`); the role-owned profiles live in
  the coordinate and integrate procedures.

#### Reminder: goal-drive

- **Owner:** this policy.
- **Parameters:** optional `--intent`.
- **Activation anchor / arm condition:** before the first substantive autonomous
  action of sustained work. Not after a procedure has delegated execution and
  prescribed its own watcher; a terminal or human-gated procedure state makes it
  inapplicable and requires immediate cancellation.
- **Duration / recurrence:** recurring, five minutes of session inactivity. The
  schedule slides to the last activity, so it never fires while the agent works.
- **Intent:** defaults to `Reassess whether the current work remains aligned with
the goal. If aligned, continue; otherwise correct course or stop.`; `--intent`
  overrides with agent-authored text.
- **Firing behavior:** check for later input, then reassess only the active goal.
  Not a debrief or housekeeping trigger.
- **Cancellation:** the moment the next move stops being this agent's — goal
  delivered, abandoned, or handed off. A firing that finds the goal retired
  cancels the slug, then ends with exactly `NOOP`.
- **Invocation:** `telec reminders set goal-drive [--intent <intent>]`.

#### Reminder: halt-to-respond

- **Owner:** this policy.
- **Parameters:** none.
- **Activation anchor:** the owning session's next agent stop after arming —
  the stop that ends the answer turn.
- **Duration:** none; that stop makes the reminder due directly.
- **Recurrence:** one-shot.
- **Arm condition:** non-human input that requires an answer reaches the session
  while it holds unfinished work of its own, and the answer neither completes
  nor supersedes that work. Arming is the last action of the answer turn; the
  turn then ends with the answer, or with exactly `NOOP` when the input asks for
  none. A session holding no interrupted work does not arm it.
- **Intent:** `Resume the work interrupted to answer the non-human input, unless
intervening input made that work stale.`
- **Firing behavior:** check for later input first; resume the interrupted work
  while it is still this session's and still current, otherwise end with
  exactly `NOOP`.
- **Cancellation:** cancel before the answer turn ends when that turn itself
  resumed or finished the interrupted work, or when later input made it stale
  or handed it off. A firing consumes it.
- **Invocation:** `telec reminders set halt-to-respond`.

## Rationale

Agent runtimes do not reliably keep local timers across turn closure; a
platform-owned reminder makes future intent durable while the semantic decision
stays with the agent. Intent-revealing slugs keep reminders readable, multiple
slugs keep subgoals independent, and cancellation keeps finished work from
returning as zombie activity.

Retirement is explicit because a turn receives whatever arrives in it; a
turn-scoped silence cannot say which reminder it meant, so reading cancellation
out of it would retire reminders the agent still wanted.

Yielding keeps the session receptive to the human. A terminal is an execution
surface, not a scheduler.

Answering non-human input mid-work leaves the interrupted work with no owner of
its next move once the answer turn ends. The stop that ends that turn is the one
event certain to follow the answer, so a reminder anchored on it returns the
work without firing inside the answer or after a guessed delay, as a timed
reminder would.

## Scope

Every agent session using the platform reminder service. Infrastructure
heartbeats, leases, peer refresh, cache health, and operation heartbeats are
outside it.

## Enforcement

Reviewers and supervising sessions apply these rules to transcripts; sustained
work with no `goal-drive` armed, and any blocking wait, are the common findings.

## Exceptions

- Short interactive work that completes in a few tool calls does not arm
  `goal-drive`.
