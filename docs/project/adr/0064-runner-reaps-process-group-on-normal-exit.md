---
visibility: 'public'
number: '64'
date: '2026-07-07'
description: 'The telec code test/lint runner reaps its child process group on the normal-return path too, not only on abnormal exit — closing the xdist session_timeout leak where a suite-spawned descendant survives a normal (exit 2, no signal) return under start_new_session terminal detachment. Reverses ADR-0050 in part.'
---

# ADR-0064: The telec runner reaps the process group on normal exit — ADR

## Context

ADR-0050 established process-group orphan prevention at the telec subprocess
boundary: `_run_in_process_group` launches the child as a session/process-group
leader (`start_new_session=True`) and reaps the group on abnormal exit (a caught
`SIGINT`/`SIGTERM`, or a propagating exception). It explicitly decided against a
normal-return reap, reasoning that "human-run `make test` already gets correct
teardown from terminal job control."

That rationale holds only for a human running `make test` in an interactive
terminal. The `telec code test` path runs the same runner with
`start_new_session=True`, which detaches the child from the controlling terminal —
so no terminal job control exists to reap the group on the normal path. Under xdist
`session_timeout` (`xdist.dsession.Interrupted`), pytest returns a normal exit code
(2) with no signal to the runner; neither abnormal-exit branch fires, and a
suite-spawned descendant that outlives pytest survives in the ownerless process
group, reparented to PID 1. This was reproduced under controlled probes.

## Decision

The runner reaps the child process group on the normal-return path as well as the
two abnormal-exit paths. The reap runs after the child's normal `wait()` returns
and before the runner returns the exit code, reusing the existing idempotent
group-teardown: on a clean run the group is already empty and the teardown is a
guarded no-op; on a `session_timeout`-interrupted normal return it reaps any leaked
descendant. Return-code propagation and the signal/exception paths are unchanged.

## Consequences

- The xdist `session_timeout` normal-exit leak is closed: a `telec code test`/
  `lint` run interrupted by the suite ceiling no longer orphans a suite-spawned
  descendant.
- Every clean run performs one additional group-teardown call — a guarded no-op
  against an already-empty group, a negligible cost paid on the normal path.
- The reap stays in the normal-path (`else`) arm, not a shared `finally`: the
  signal arm re-sends the terminating signal to the runner itself after its own
  reap, and a `finally` reap would entangle with that self-terminate and
  double-reap the exception arms.
- A `SIGKILL` to the telec process itself remains undefendable in userspace
  (unchanged from ADR-0050); that limitation stands.

## Alternatives Considered

- **Harness-only hygiene (reap only within tests / fix leaking tests).** Rejected
  as the sole defense: it cannot cover the general case of a suite-spawned
  descendant outliving pytest on a normal interrupt, and it leaves the runner
  boundary — the one place that owns the process group — without a backstop.
  Fixing individual leaking tests is complementary, but does not close the
  runner-level gap.
- **Reap in a shared `finally`.** Rejected: it double-reaps the exception arms and
  entangles with the signal arm's self-terminate; the normal-path `else` arm is the
  correct, minimal placement.
