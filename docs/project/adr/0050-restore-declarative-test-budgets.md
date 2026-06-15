---
date: '2026-06-15'
description: 'Restore the declarative pytest budget layer (per-test timeout, session_timeout, xdist -n auto) that the spec-anchored-testing transition removed alongside the custom hang machinery. The machinery ban stays; only the cheap native config returns. Per-test signal budget names a hung test by node id; the session ceiling is a graceful between-tests stop, not an in-flight dump.'
number: '50'
visibility: 'public'
---

# ADR-0050: Restore the Declarative Test-Budget Layer — ADR

## Context

ADR-0046 (spec-anchored testing) deleted the custom hang machinery — the
watchdog, the subprocess reaper, and the per-worker in-flight tracker — because
that scaffolding was agent-authored, expensive, and let real regressions ship.
That deletion was correct. Its consequence over-rotated: the same change also
removed the _declarative_ budget layer — pytest-native per-test `timeout`, the
`session_timeout` suite ceiling, and xdist `-n auto` parallelism — which is cheap
native configuration, not custom machinery. The result was a harness with no
per-test budget, no wall-clock ceiling, and no parallelism, where a hung test
could stall the suite with no named cause, and a killed runner could orphan
xdist `execnet` workers (reparented to PID 1).

## Decision

- Restore the declarative budget layer as a single `[tool.pytest.ini_options]`
  source: `timeout=5` with `timeout_method="signal"` (per-test budget),
  `session_timeout=40` (suite wall-clock ceiling), and `-n auto` (xdist
  parallelism). The custom hang machinery stays deleted.
- The per-test signal budget is the in-flight diagnostic surface: it forcibly
  stops a hanging test and names it by node id with a dumped traceback, per
  worker. That is the one point a running test is interrupted.
- The `session_timeout` ceiling is a graceful between-tests stop — pytest-timeout
  sets it only after a test protocol returns, emitting `session-timeout: N sec
exceeded`. It never hard-kills a running test and does **not** dump each
  worker's in-flight test; producing that dump would require the deleted
  in-flight tracker, which is not reintroduced.
- Budgets are non-negotiable constants. A test that exceeds its budget is fixed,
  split, or retiered — never granted a larger number.
- Orphan prevention is handled at the telec subprocess boundary: the test/make
  runner launches its child as a session/process-group leader and tears the
  group down on abnormal exit. No normal-path wrapper is added; human-run
  `make test` already gets correct teardown from terminal job control.

## Consequences

- A hung test is named at the 5s per-test budget rather than disappearing into a
  bare `Interrupted`; the session ceiling is a runaway guard, not the diagnostic
  point. A run that ends in a bare `Interrupted` with no named cause is a
  test-infrastructure defect.
- The suite runs in parallel again; tests that cannot run in parallel are fixed,
  not serialized.
- The per-test signal budget is sensitive to severe CPU starvation: a test that
  is normally well under 5s can breach the budget under extreme load. The
  contract treats a genuine breach as a test to fix, never as a reason to raise
  the number.
- A killed or `SIGTERM`/`SIGINT`-interrupted `telec code test` no longer orphans
  `execnet` workers. A `SIGKILL` to the telec process itself remains undefendable
  in userspace — defending it would require the deleted reaper/supervisor, so it
  stays out of scope as a named limitation.
