---
date: '2026-10-07'
description: 'DeepSeek stack convergence judges fit only on what a package requires of the runtime itself; requirements on libraries the runtime bundles are reported as advisories, and the verification gate decides whether such a set works.'
number: '112'
visibility: 'internal'
---

# ADR-0112: DeepSeek Fit Judges Runtime Requirements Only — ADR

## Context

DeepSeek stack convergence chooses the newest runtime, TUI and plugin versions
that fit each other, without pinning and without dropping a plugin. Plugin
manifests declare two kinds of compatibility requirement:

- requirements on the runtime itself, through the runtime's own packages or the
  declared runtime engine;
- requirements on libraries the runtime bundles, such as its framework and
  schema libraries.

The runtime's own startup check judges only the first kind.

Plugin releases are routinely built against bundled-library prereleases that the
current runtime release does not yet ship. On the installed release candidate,
the checkpoint plugin 0.6.23 declares framework and schema library prereleases
newer than the ones the runtime ships, yet its runtime requirements name that
release line. It started cleanly in the TUI profile, completed a turn and
recorded checkpoints. Judged with library requirements as hard constraints, no
compatible set exists. Judged on runtime requirements, the set fits.

Declared compatibility does not prove that a set works in either reading. The
convergence verification gate runs the adopted set and restores the snapshot
when a check fails.

## Decision

Fit judges only the requirements a package declares on the runtime itself,
under strict semantic-version matching. Requirements on libraries the runtime
bundles are checked against the versions the candidate runtime brings and
reported as advisories in the run's report. They never reject a candidate. The
verification gate, with snapshot restore, decides whether a set whose library
advisories are unmet is kept.

## Consequences

- Newly released plugin fixes become adoptable as soon as they fit the runtime,
  instead of waiting for a runtime release that ships the libraries they name.
- A plugin that does need a newer bundled library can fail in a code path the
  gate's turns never exercise. Such a set may be kept, and the report names
  every advisory it carries.
- Fit stays stricter than the runtime's own startup check on prereleases, so
  every adopted set still passes that check.
- The gate is load-bearing for library compatibility; weakening its checks
  weakens this decision.

## Alternatives Considered

- **Library requirements as hard constraints.** This rejected a set that runs,
  and would keep refusing plugin releases built against libraries newer than the
  runtime ships. That defeats adopting newly released fixes, which is the
  purpose of convergence.
- **Prefer, among fitting versions, those whose library requirements also
  hold.** This selects older plugin releases over newer fixes whenever a
  library lags, which trades fixes for a declaration the runtime itself does not
  enforce.
- **Also judging the declared Node engine.** The machine's Node runtime is
  outside the DeepSeek stack that convergence installs, and the gate's startup
  checks already fail a set that Node cannot run.
