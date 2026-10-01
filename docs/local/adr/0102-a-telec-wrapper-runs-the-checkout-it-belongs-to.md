---
visibility: internal
number: 0102
date: 2026-09-25
description: The code a telec invocation runs is selected by the wrapper's own location — the global command runs the installation, a checkout's bin/telec runs that checkout, and worktree code runs only against a scratch home.
---

# A Telec Wrapper Runs the Checkout It Belongs To — ADR

## Context

Two needs pull on which code a `telec` invocation runs.

A change must be graded against itself. Lint lanes, guardrail allowlists, artifact
and configuration schemas, and the rendered command surface have to come from the
checkout that carries the change, or a worktree is judged by rules its change never
touched. The editable install registers an import finder pinned to the installation
that outranks `PYTHONPATH` and `sys.path`, so the only lever that selects a checkout's
code is the directory the wrapper hands to `uv run --directory`.

The live home is shared state. Every delivered process on the machine reads the same
configuration documents, database and daemon. When undelivered code writes there,
restoring the file does not undo the harm: other processes have already read the
value, and a daemon restart in that window fails to boot.

Commit `e6e4b8b8c` served the first need by selecting the checkout from the caller's
working directory. That made every ordinary call inside a slug worktree — status
checks, todo reads, anything an agent runs while standing there — execute undelivered
code against the live home. A worktree loader that migrated configuration on read
wrote a key the delivered validator rejects into the live machine configuration, and
every `telec` call on the canonical checkout failed until the line was removed.

## Decision

The wrapper selects the code from its own location, never from the caller's working
directory.

- The global `telec` runs the installed canonical checkout. It is the runtime command
  for everyone, from any directory.
- A checkout's own `bin/telec` runs that checkout. Exercising one's own change is an
  explicit act that names the worktree's wrapper.
- From a slug worktree, that wrapper runs only against a home that resolves somewhere
  other than the live home, and is refused before any worktree code runs otherwise.
- `telec code` keeps grading a worktree's change with the worktree's own code, so the
  quality lanes still judge a change against itself while the command the agent types
  stays the global one.

## Consequences

- An ordinary call from inside a worktree behaves exactly like the same call from the
  canonical checkout, so standing in a worktree can no longer reach live state with
  undelivered code.
- Agents' bookkeeping instructions do not change. Only exercising one's own change
  names a form of its own: the worktree's `bin/telec` with a scratch home.
- Nothing runs worktree code against the live daemon. A daemon has no per-worktree
  instance and the daemon socket does not follow the home, so daemon-side behavior is
  verified after delivery, as the test moratorium already provides.
- Protection is placed at the invocation boundary rather than at each writer, so a
  writer added later is covered without anyone remembering to guard it.

## Alternatives Considered

- **Keep working-directory selection and guard each writer.** A refusal in the
  configuration write layer covers only the writers someone enumerated; the database,
  state files and any future writer stay exposed, and the guard must be rediscovered
  for each new one.
- **Split by command: `telec code` and help run the caller's checkout, everything else
  the installation.** Keeps worktree code off live state, but every agent has to know
  which commands run which code, and a hand-driven probe of any other command cannot
  exercise the change at all.
- **A daemon per worktree.** Would make daemon-side behavior testable from a worktree,
  at the cost of a second runtime per todo; rejected.
