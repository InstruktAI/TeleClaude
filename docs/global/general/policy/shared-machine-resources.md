---
description: Free disk space is shared by every process on the machine; whoever creates a checkout or build output keeps it bounded, removes it when its work ends, and keeps a floor of headroom before starting a build.
---

# Shared Machine Resources — Policy

## Rules

- **Disk headroom belongs to the whole machine.** Every agent, the human's
  applications and their virtual machines write to the same volume. An agent
  keeps at least 20 GiB free while it works, whichever project it serves.
- **Whoever creates a checkout owns its output.** A session that creates a
  worktree, clone, review copy, temporary `HOME` or scratch directory removes
  its regenerable output when that checkout's work ends: Rust `target/`,
  `node_modules`, `.venv`, build and test caches, temporary homes. It removes
  the checkout itself once nothing needs it. Committed work and anything not
  regenerable stay.
- **Delegation carries the duty.** A session that delegates work which creates
  checkouts names that cleanup in the brief, and when a round of delegated work
  ends, removes the regenerable output its finished delegates left behind.
- **Measure before building in a new place.** Before a build, install or full
  test run in a checkout that has no build output yet, check the volume's free
  space. With less than 20 GiB free, clean up output this session owns first;
  if that does not restore 20 GiB, stop and report the free space and the
  largest regenerable directories rather than building.
- **Reuse before duplicating.** Work that needs only evidence a build already
  produced, such as a hook run or CI result for the same commit, cites that
  evidence instead of rebuilding in another checkout.
- **Clean what you own.** A session removes only output it or its delegates
  created, never another live session's checkout or build output. Output of a
  session that has ended is the delegating session's to remove.

## Rationale

Each isolated checkout builds its own full output, and parallel work
multiplies it: a handful of concurrent builders and reviewers can produce
enough regenerable build output to fill a machine's volume within hours. When
the volume fills, writes fail in unrelated applications and their virtual
machines stop. That harm lands outside the session that caused it, where
restoring the files repairs nothing. Output is regenerable, so removing it
costs only a rebuild; keeping it costs everyone on the machine.

The 20 GiB floor is an operating reserve, not a promise that any build fits. A
full build of one Rust workspace writes a few GiB of output, so the reserve
leaves room for a round of parallel builds and for the human's applications and
virtual machines to keep writing, while staying small against a typical
volume. Stopping at the floor turns a machine that would fill into one session
reporting the shortfall.

## Scope

All agents, all sessions, all projects, on every machine they run on.

## Enforcement

Reviewers treat a finished checkout left with its build output as a process
miss.

## Exceptions

None.
