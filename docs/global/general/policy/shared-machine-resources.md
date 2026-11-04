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
- **An orchestrator closes each round clean.** When a round of delegated work
  ends, the orchestrator removes the finished checkouts' regenerable output,
  and every brief that creates a checkout tells the delegate to clean up what
  it creates.
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
  session that has ended is the creating orchestrator's to remove.

## Rationale

Each isolated checkout builds its own full output, and parallel work
multiplies it: one evening of parallel builders and reviewers left about
125 GiB of Rust build output on a 500 GB disk. When the volume filled, writes
failed in unrelated applications and a virtual machine stopped. That harm
lands outside the session that caused it, where restoring the files repairs
nothing. Output is regenerable, so removing it costs only a rebuild; keeping it
costs everyone on the machine.

## Scope

All agents, all sessions, all projects, on every machine they run on.

## Enforcement

The machine's `disk-headroom` job measures free space on a schedule, notifies
the human when it runs low and, below a hard floor, removes regenerable build
output from checkouts no running process uses. Reviewers and orchestrators treat
a finished checkout left with its build output as a process miss.

## Exceptions

None.
